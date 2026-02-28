"""Celery tasks for RL training pipeline."""

import json
import logging
from datetime import datetime
from pathlib import Path

import numpy as np
import redis
from celery import current_task
from stable_baselines3.common.callbacks import BaseCallback

from app.celery_app import celery_app
from app.config import settings

logger = logging.getLogger(__name__)

from app.config import settings

SIMULATION_NETWORKS_DIR = settings.simulation_networks_dir
MODELS_DIR = settings.simulation_models_dir


def _get_redis():
    """Get Redis client."""
    return redis.Redis(host=settings.redis_host, port=settings.redis_port, decode_responses=True)


# ──────────────────────────────────────────────
# SB3 Callbacks (single-agent)
# ──────────────────────────────────────────────


class CancellationCallback(BaseCallback):
    """Check every 100 steps if task has been revoked."""

    def __init__(self, task_id: str, verbose: int = 0):
        super().__init__(verbose)
        self.task_id = task_id
        self._check_interval = 100

    def _on_step(self) -> bool:
        if self.n_calls % self._check_interval == 0:
            if current_task and current_task.is_aborted():
                logger.info(f"Task {self.task_id} cancelled at step {self.num_timesteps}")
                return False
        return True


class ProgressPublishingCallback(BaseCallback):
    """Publish progress to Redis every 500 steps."""

    def __init__(
        self,
        task_id: str,
        total_timesteps: int,
        baseline: dict | None = None,
        traffic_metrics_callback: "TrafficMetricsCallback | None" = None,
        metrics_logging_callback: "MetricsLoggingCallback | None" = None,
        verbose: int = 0,
    ):
        super().__init__(verbose)
        self.task_id = task_id
        self.total_timesteps = total_timesteps
        self.baseline = baseline or {}
        self._publish_interval = 500
        self._redis = None
        self._traffic_metrics = traffic_metrics_callback
        self._metrics_logging = metrics_logging_callback

    def _get_redis(self):
        if self._redis is None:
            self._redis = _get_redis()
        return self._redis

    def _on_step(self) -> bool:
        if self.n_calls % self._publish_interval == 0:
            self._publish_progress()
        return True

    def _publish_progress(self):
        r = self._get_redis()
        progress = min(self.num_timesteps / max(self.total_timesteps, 1), 1.0)

        payload = {
            "task_id": self.task_id,
            "status": "running",
            "timestep": self.num_timesteps,
            "total_timesteps": self.total_timesteps,
            "progress": round(progress, 4),
            "episode_count": len(self.model._episode_num_timesteps) if hasattr(self.model, "_episode_num_timesteps") else 0,
            "mean_reward": self._metrics_logging.mean_reward if self._metrics_logging else 0.0,
            "avg_waiting_time": self._traffic_metrics.avg_waiting_time if self._traffic_metrics else 0.0,
            "avg_queue_length": self._traffic_metrics.avg_queue_length if self._traffic_metrics else 0.0,
            "throughput": self._traffic_metrics.throughput if self._traffic_metrics else 0,
        }

        # Add baseline if available
        if self.baseline:
            payload["baseline_avg_waiting_time"] = self.baseline.get("avg_waiting_time", 0.0)
            payload["baseline_avg_queue_length"] = self.baseline.get("avg_queue_length", 0.0)
            payload["baseline_throughput"] = self.baseline.get("throughput", 0)

        payload_json = json.dumps(payload)
        r.publish(f"task:{self.task_id}:updates", payload_json)
        r.setex(f"task:{self.task_id}:progress", 3600, payload_json)


class TrafficMetricsCallback(BaseCallback):
    """Accumulate traffic metrics from environment info dicts."""

    def __init__(self, verbose: int = 0):
        super().__init__(verbose)
        self._waiting_times: list[float] = []
        self._queue_lengths: list[float] = []
        self._throughputs: list[int] = []

    def _on_step(self) -> bool:
        infos = self.locals.get("infos", [{}])
        if infos:
            info = infos[0] if isinstance(infos, list) else infos
            self._waiting_times.append(info.get("avg_waiting_time", 0.0))
            self._queue_lengths.append(info.get("avg_queue_length", 0.0))
            self._throughputs.append(info.get("throughput", 0))
        return True

    @property
    def avg_waiting_time(self) -> float:
        return float(np.mean(self._waiting_times[-100:])) if self._waiting_times else 0.0

    @property
    def avg_queue_length(self) -> float:
        return float(np.mean(self._queue_lengths[-100:])) if self._queue_lengths else 0.0

    @property
    def throughput(self) -> int:
        return int(np.sum(self._throughputs[-100:])) if self._throughputs else 0


class MetricsLoggingCallback(BaseCallback):
    """Log mean reward every 1000 steps."""

    def __init__(self, verbose: int = 0):
        super().__init__(verbose)
        self._log_interval = 1000
        self._episode_rewards: list[float] = []
        self._current_reward = 0.0

    def _on_step(self) -> bool:
        reward = self.locals.get("rewards", [0])[0]
        self._current_reward += reward

        dones = self.locals.get("dones", [False])
        if dones[0]:
            self._episode_rewards.append(self._current_reward)
            self._current_reward = 0.0

        if self.n_calls % self._log_interval == 0 and self._episode_rewards:
            mean_reward = float(np.mean(self._episode_rewards[-10:]))
            logger.info(
                f"Step {self.num_timesteps}: mean_reward={mean_reward:.2f}, "
                f"episodes={len(self._episode_rewards)}"
            )
        return True

    @property
    def mean_reward(self) -> float:
        return float(np.mean(self._episode_rewards[-10:])) if self._episode_rewards else 0.0


# ──────────────────────────────────────────────
# Multi-agent callbacks
# ──────────────────────────────────────────────


class MultiCancellationCallback:
    """Check every 100 steps if multi-agent task has been revoked."""

    def __init__(self, task_id: str):
        self.task_id = task_id
        self._check_interval = 100

    def on_step(self, step: int, total_steps: int, infos: dict) -> bool:
        if step % self._check_interval == 0:
            if current_task and current_task.is_aborted():
                logger.info(f"Multi-agent task {self.task_id} cancelled at step {step}")
                return False
        return True

    def on_episode_end(self, episode: int, infos: dict) -> None:
        pass


class MultiProgressCallback:
    """Publish multi-agent progress to Redis every 500 steps."""

    def __init__(
        self,
        task_id: str,
        total_timesteps: int,
        tl_ids: list[str],
        baseline: dict | None = None,
    ):
        self.task_id = task_id
        self.total_timesteps = total_timesteps
        self.tl_ids = tl_ids
        self.baseline = baseline or {}
        self._publish_interval = 500
        self._redis = None

    def _get_redis(self):
        if self._redis is None:
            self._redis = _get_redis()
        return self._redis

    def on_step(self, step: int, total_steps: int, infos: dict) -> bool:
        if step % self._publish_interval == 0:
            self._publish(step, infos)
        return True

    def on_episode_end(self, episode: int, infos: dict) -> None:
        pass

    def _publish(self, step: int, infos: dict):
        r = self._get_redis()
        progress = min(step / max(self.total_timesteps, 1), 1.0)

        # Aggregate metrics across agents
        waiting_times = [infos.get(tl, {}).get("avg_waiting_time", 0.0) for tl in self.tl_ids]
        queue_lengths = [infos.get(tl, {}).get("avg_queue_length", 0.0) for tl in self.tl_ids]
        throughputs = [infos.get(tl, {}).get("throughput", 0) for tl in self.tl_ids]

        payload = {
            "task_id": self.task_id,
            "status": "running",
            "timestep": step,
            "total_timesteps": self.total_timesteps,
            "progress": round(progress, 4),
            "mean_reward": 0.0,
            "avg_waiting_time": float(np.mean(waiting_times)) if waiting_times else 0.0,
            "avg_queue_length": float(np.mean(queue_lengths)) if queue_lengths else 0.0,
            "throughput": int(sum(throughputs)),
        }

        if self.baseline:
            payload["baseline_avg_waiting_time"] = self.baseline.get("avg_waiting_time", 0.0)
            payload["baseline_avg_queue_length"] = self.baseline.get("avg_queue_length", 0.0)
            payload["baseline_throughput"] = self.baseline.get("throughput", 0)

        payload_json = json.dumps(payload)
        r.publish(f"task:{self.task_id}:updates", payload_json)
        r.setex(f"task:{self.task_id}:progress", 3600, payload_json)


# ──────────────────────────────────────────────
# Celery tasks
# ──────────────────────────────────────────────


@celery_app.task(bind=True, name="train_traffic_light")
def train_traffic_light(
    self,
    network_id: str,
    tl_id: str,
    algorithm: str = "dqn",
    total_timesteps: int = 10000,
    scenario: str = "moderate",
):
    """Single-junction training task."""
    task_id = self.request.id
    r = _get_redis()
    logger.info(f"Starting single-junction training: task={task_id}, network={network_id}, tl={tl_id}")

    # Store task metadata
    meta = {
        "task_id": task_id,
        "network_id": network_id,
        "tl_ids": [tl_id],
        "algorithm": algorithm,
        "total_timesteps": total_timesteps,
        "scenario": scenario,
        "status": "running",
        "created_at": datetime.now().isoformat(),
    }
    r.set(f"task:{task_id}:meta", json.dumps(meta))
    r.lpush("tasks:list", task_id)

    try:
        from app.ml.environment import TrafficLightEnv
        from app.ml.trainer import Algorithm, TrafficLightTrainer

        # Find network file
        network_path = str(SIMULATION_NETWORKS_DIR / f"{network_id}.net.xml")
        if not Path(network_path).exists():
            raise FileNotFoundError(f"Network file not found: {network_path}")

        # Create environment
        env = TrafficLightEnv(
            network_path=network_path,
            network_id=network_id,
            tl_id=tl_id,
            algorithm=algorithm,
            scenario=scenario,
        )

        # Create trainer
        algo_enum = Algorithm.DQN if algorithm.lower() == "dqn" else Algorithm.PPO
        trainer = TrafficLightTrainer(env=env, algorithm=algo_enum)

        # Run baseline
        baseline = trainer.run_baseline(num_episodes=3)

        # Create callbacks - metrics callbacks first so they have data when progress publishes
        traffic_metrics_cb = TrafficMetricsCallback()
        metrics_logging_cb = MetricsLoggingCallback()
        callbacks = [
            CancellationCallback(task_id),
            traffic_metrics_cb,
            metrics_logging_cb,
            ProgressPublishingCallback(
                task_id, total_timesteps, baseline,
                traffic_metrics_callback=traffic_metrics_cb,
                metrics_logging_callback=metrics_logging_cb,
            ),
        ]

        # Train
        trainer.train(total_timesteps=total_timesteps, callbacks=callbacks)

        # Save model
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        model_filename = f"{network_id}_{tl_id}_{algorithm}_{timestamp}"
        model_path = MODELS_DIR / model_filename
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        trainer.save(str(model_path))

        # Save metadata alongside model
        model_meta = {
            "network_id": network_id,
            "tl_id": tl_id,
            "algorithm": algorithm,
            "total_timesteps": total_timesteps,
            "observation_dim": env.observation_space.shape[0],
            "action_dim": env.action_space.n,
            "num_phases": env._num_phases,
            "controlled_lanes": env._controlled_lanes,
            "trained_on_scenarios": [scenario],
            "created_at": datetime.now().isoformat(),
        }
        meta_path = Path(str(model_path) + ".zip.metadata.json")
        with open(meta_path, "w") as f:
            json.dump(model_meta, f, indent=2)

        # Publish completion
        completion = {
            "task_id": task_id,
            "status": "completed",
            "timestep": total_timesteps,
            "total_timesteps": total_timesteps,
            "progress": 1.0,
            "model_path": str(model_path) + ".zip",
        }
        if baseline:
            completion["baseline_avg_waiting_time"] = baseline.get("avg_waiting_time", 0.0)
            completion["baseline_avg_queue_length"] = baseline.get("avg_queue_length", 0.0)
            completion["baseline_throughput"] = baseline.get("throughput", 0)

        r.publish(f"task:{task_id}:updates", json.dumps(completion))
        r.setex(f"task:{task_id}:progress", 3600, json.dumps(completion))

        env.close()
        logger.info(f"Training complete: {model_path}.zip")
        return {"status": "completed", "model_path": str(model_path) + ".zip"}

    except Exception as e:
        logger.error(f"Training failed: {e}", exc_info=True)
        error_payload = {
            "task_id": task_id,
            "status": "failed",
            "error": str(e),
        }
        r.publish(f"task:{task_id}:updates", json.dumps(error_payload))
        r.setex(f"task:{task_id}:progress", 3600, json.dumps(error_payload))
        raise


@celery_app.task(bind=True, name="train_multi_junction")
def train_multi_junction(
    self,
    network_id: str,
    tl_ids: list[str],
    algorithm: str = "dqn",
    total_timesteps: int = 10000,
    scenario: str = "moderate",
):
    """Multi-junction training task."""
    task_id = self.request.id
    r = _get_redis()
    logger.info(f"Starting multi-junction training: task={task_id}, network={network_id}, tls={tl_ids}")

    meta = {
        "task_id": task_id,
        "network_id": network_id,
        "tl_ids": tl_ids,
        "algorithm": algorithm,
        "total_timesteps": total_timesteps,
        "scenario": scenario,
        "status": "running",
        "created_at": datetime.now().isoformat(),
    }
    r.set(f"task:{task_id}:meta", json.dumps(meta))
    r.lpush("tasks:list", task_id)

    try:
        from app.ml.multi_agent_env import MultiAgentTrafficLightEnv
        from app.ml.multi_agent_trainer import MultiAgentTrainer
        from app.ml.trainer import Algorithm as AlgoEnum

        network_path = str(SIMULATION_NETWORKS_DIR / f"{network_id}.net.xml")
        if not Path(network_path).exists():
            raise FileNotFoundError(f"Network file not found: {network_path}")

        env = MultiAgentTrafficLightEnv(
            network_path=network_path,
            network_id=network_id,
            tl_ids=tl_ids,
            algorithm=algorithm,
            scenario=scenario,
        )

        algo_enum = AlgoEnum.DQN if algorithm.lower() == "dqn" else AlgoEnum.PPO
        trainer = MultiAgentTrainer(env=env, algorithm=algo_enum)

        baseline = trainer.run_baseline(num_episodes=3)

        callbacks = [
            MultiCancellationCallback(task_id),
            MultiProgressCallback(task_id, total_timesteps, tl_ids, baseline),
        ]

        trainer.train(total_timesteps=total_timesteps, callbacks=callbacks)

        # Save models
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        model_dir = MODELS_DIR / f"{network_id}_multi_{algorithm}_{timestamp}"
        trainer.save(str(model_dir))

        completion = {
            "task_id": task_id,
            "status": "completed",
            "timestep": total_timesteps,
            "total_timesteps": total_timesteps,
            "progress": 1.0,
            "model_path": str(model_dir),
        }
        if baseline:
            completion["baseline_avg_waiting_time"] = baseline.get("avg_waiting_time", 0.0)
            completion["baseline_avg_queue_length"] = baseline.get("avg_queue_length", 0.0)
            completion["baseline_throughput"] = baseline.get("throughput", 0)

        r.publish(f"task:{task_id}:updates", json.dumps(completion))
        r.setex(f"task:{task_id}:progress", 3600, json.dumps(completion))

        env.close()
        logger.info(f"Multi-junction training complete: {model_dir}")
        return {"status": "completed", "model_path": str(model_dir)}

    except Exception as e:
        logger.error(f"Multi-junction training failed: {e}", exc_info=True)
        error_payload = {
            "task_id": task_id,
            "status": "failed",
            "error": str(e),
        }
        r.publish(f"task:{task_id}:updates", json.dumps(error_payload))
        r.setex(f"task:{task_id}:progress", 3600, json.dumps(error_payload))
        raise
