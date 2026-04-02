"""Celery tasks for RL training pipeline."""

import json
import logging
from datetime import datetime
from pathlib import Path

import numpy as np
import redis

from app.celery_app import celery_app
from app.config import settings
from app.ml.trainer import TrainingCallback

logger = logging.getLogger(__name__)

SIMULATION_NETWORKS_DIR = settings.simulation_networks_dir
MODELS_DIR = settings.simulation_models_dir


def _get_redis():
    """Get Redis client."""
    return redis.Redis(host=settings.redis_host, port=settings.redis_port, decode_responses=True)


# ──────────────────────────────────────────────
# Custom training callbacks (for LibSignal-style loop)
# ──────────────────────────────────────────────


class CancellationCallback(TrainingCallback):
    """Check at episode end if task has been cancelled via Redis."""

    def __init__(self, task_id: str):
        self.task_id = task_id
        self._redis: redis.Redis | None = None

    def _get_redis(self):
        if self._redis is None:
            self._redis = _get_redis()
        return self._redis

    def on_episode_end(self, episode: int, num_episodes: int, episode_reward: float, info: dict) -> bool:
        r = self._get_redis()
        progress_json = r.get(f"task:{self.task_id}:progress")
        if progress_json:
            progress = json.loads(progress_json)
            if progress.get("status") == "cancelled":
                logger.info(f"Task {self.task_id} cancelled at episode {episode}")
                return False
        return True


class ProgressPublishingCallback(TrainingCallback):
    """Publish progress to Redis at each episode end."""

    def __init__(
        self,
        task_id: str,
        total_timesteps: int,
        baseline: dict | None = None,
    ):
        self.task_id = task_id
        self.total_timesteps = total_timesteps
        self.baseline = baseline or {}
        self._redis: redis.Redis | None = None
        self.progress_history: list[dict] = []
        # Track episode metrics
        self._episode_rewards: list[float] = []
        self._episode_waiting_times: list[float] = []
        self._episode_queue_lengths: list[float] = []
        self._episode_throughputs: list[int] = []

    def _get_redis(self):
        if self._redis is None:
            self._redis = _get_redis()
        return self._redis

    def on_episode_end(self, episode: int, num_episodes: int, episode_reward: float, info: dict) -> bool:
        self._episode_rewards.append(episode_reward)
        self._episode_waiting_times.append(info.get("avg_waiting_time", 0.0))
        self._episode_queue_lengths.append(info.get("avg_queue_length", 0.0))
        self._episode_throughputs.append(info.get("throughput", 0))

        self._publish(episode, num_episodes)
        return True

    def _publish(self, episode: int, num_episodes: int):
        r = self._get_redis()
        # Map episode progress to timestep progress for SSE compatibility
        progress = min((episode + 1) / max(num_episodes, 1), 1.0)
        timestep = int(progress * self.total_timesteps)

        mean_reward = float(np.mean(self._episode_rewards[-10:])) if self._episode_rewards else 0.0
        avg_waiting = float(np.mean(self._episode_waiting_times[-10:])) if self._episode_waiting_times else 0.0
        avg_queue = float(np.mean(self._episode_queue_lengths[-10:])) if self._episode_queue_lengths else 0.0
        throughput = int(np.mean(self._episode_throughputs[-10:])) if self._episode_throughputs else 0

        payload = {
            "task_id": self.task_id,
            "status": "running",
            "timestep": timestep,
            "total_timesteps": self.total_timesteps,
            "progress": round(progress, 4),
            "episode_count": len(self._episode_rewards),
            "mean_reward": mean_reward,
            "avg_waiting_time": avg_waiting,
            "avg_queue_length": avg_queue,
            "throughput": throughput,
        }

        if self.baseline:
            payload["baseline_avg_waiting_time"] = self.baseline.get("avg_waiting_time", 0.0)
            payload["baseline_avg_queue_length"] = self.baseline.get("avg_queue_length", 0.0)
            payload["baseline_throughput"] = self.baseline.get("throughput", 0)

        self.progress_history.append({
            "timestep": timestep,
            "avg_waiting_time": avg_waiting,
            "throughput": throughput,
            "mean_reward": mean_reward,
        })

        payload_json = json.dumps(payload)
        r.publish(f"task:{self.task_id}:updates", payload_json)
        r.setex(f"task:{self.task_id}:progress", 3600, payload_json)

    def get_final_metrics(self, last_n: int = 10) -> dict:
        return {
            "avg_waiting_time": float(np.mean(self._episode_waiting_times[-last_n:])) if self._episode_waiting_times else 0.0,
            "avg_queue_length": float(np.mean(self._episode_queue_lengths[-last_n:])) if self._episode_queue_lengths else 0.0,
            "throughput": int(np.mean(self._episode_throughputs[-last_n:])) if self._episode_throughputs else 0,
        }

    @property
    def mean_reward(self) -> float:
        return float(np.mean(self._episode_rewards[-10:])) if self._episode_rewards else 0.0


# ──────────────────────────────────────────────
# Multi-agent callbacks (unchanged, used by multi-agent trainer)
# ──────────────────────────────────────────────


class MultiCancellationCallback:
    """Check every 100 steps if multi-agent task has been cancelled via Redis."""

    def __init__(self, task_id: str):
        self.task_id = task_id
        self._check_interval = 100
        self._redis: redis.Redis | None = None

    def _get_redis(self):
        if self._redis is None:
            self._redis = _get_redis()
        return self._redis

    def on_step(self, step: int, total_steps: int, infos: dict) -> bool:
        if step % self._check_interval == 0:
            r = self._get_redis()
            progress_json = r.get(f"task:{self.task_id}:progress")
            if progress_json:
                progress = json.loads(progress_json)
                if progress.get("status") == "cancelled":
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
        self._redis: redis.Redis | None = None
        self.last_waiting_time = 0.0
        self.last_queue_length = 0.0
        self.last_throughput = 0
        self.last_mean_reward = 0.0
        self._window_size = 100
        self._waiting_window: list[float] = []
        self._queue_window: list[float] = []
        self._reward_window: list[float] = []
        self._throughput_window: list[int] = []
        self.progress_history: list[dict] = []

    def _get_redis(self):
        if self._redis is None:
            self._redis = _get_redis()
        return self._redis

    def on_step(self, step: int, total_steps: int, infos: dict) -> bool:
        waiting_times = [infos.get(tl, {}).get("avg_waiting_time", 0.0) for tl in self.tl_ids]
        queue_lengths = [infos.get(tl, {}).get("avg_queue_length", 0.0) for tl in self.tl_ids]
        throughputs = [infos.get(tl, {}).get("throughput", 0) for tl in self.tl_ids]
        reward_vals = [infos.get(tl, {}).get("reward", 0.0) for tl in self.tl_ids]

        self._waiting_window.append(float(np.mean(waiting_times)) if waiting_times else 0.0)
        self._queue_window.append(float(np.mean(queue_lengths)) if queue_lengths else 0.0)
        self._reward_window.append(float(np.mean(reward_vals)) if reward_vals else 0.0)
        self._throughput_window.append(int(np.mean(throughputs)) if throughputs else 0)

        if len(self._waiting_window) > self._window_size:
            self._waiting_window = self._waiting_window[-self._window_size:]
            self._queue_window = self._queue_window[-self._window_size:]
            self._reward_window = self._reward_window[-self._window_size:]
            self._throughput_window = self._throughput_window[-self._window_size:]

        self.last_waiting_time = float(np.mean(self._waiting_window))
        self.last_queue_length = float(np.mean(self._queue_window))
        self.last_mean_reward = float(np.mean(self._reward_window))
        self.last_throughput = self._throughput_window[-1] if self._throughput_window else 0

        if step % self._publish_interval == 0:
            self._publish(step)
        return True

    def on_episode_end(self, episode: int, infos: dict) -> None:
        pass

    def get_final_metrics(self) -> dict:
        return {
            "avg_waiting_time": self.last_waiting_time,
            "avg_queue_length": self.last_queue_length,
            "throughput": self.last_throughput,
            "mean_reward": self.last_mean_reward,
        }

    def _publish(self, step: int):
        r = self._get_redis()
        progress = min(step / max(self.total_timesteps, 1), 1.0)

        payload = {
            "task_id": self.task_id,
            "status": "running",
            "timestep": step,
            "total_timesteps": self.total_timesteps,
            "progress": round(progress, 4),
            "mean_reward": self.last_mean_reward,
            "avg_waiting_time": self.last_waiting_time,
            "avg_queue_length": self.last_queue_length,
            "throughput": self.last_throughput,
        }

        if self.baseline:
            payload["baseline_avg_waiting_time"] = self.baseline.get("avg_waiting_time", 0.0)
            payload["baseline_avg_queue_length"] = self.baseline.get("avg_queue_length", 0.0)
            payload["baseline_throughput"] = self.baseline.get("throughput", 0)

        self.progress_history.append({
            "timestep": step,
            "avg_waiting_time": self.last_waiting_time,
            "throughput": self.last_throughput,
            "mean_reward": payload["mean_reward"],
        })

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
    """Single-junction training task (V1 env + custom LibSignal-style loop)."""
    task_id = self.request.id
    r = _get_redis()
    logger.info(f"Starting single-junction training: task={task_id}, network={network_id}, tl={tl_id}, algo={algorithm}")

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

        network_path = str(SIMULATION_NETWORKS_DIR / f"{network_id}.net.xml")
        if not Path(network_path).exists():
            raise FileNotFoundError(f"Network file not found: {network_path}")

        # Create V1 environment (LibSignal-aligned: lane counts + phase one-hot, halting reward)
        env = TrafficLightEnv(
            network_path=network_path,
            network_id=network_id,
            tl_id=tl_id,
            algorithm=algorithm,
            scenario=scenario,
        )

        algo_enum = Algorithm.DQN if algorithm.lower() == "dqn" else Algorithm.PPO
        trainer = TrafficLightTrainer(env=env, algorithm=algo_enum)

        # Run baseline with default fixed-time program
        baseline = trainer.run_baseline(num_episodes=3)

        # Create custom callbacks
        progress_cb = ProgressPublishingCallback(task_id, total_timesteps, baseline)
        callbacks: list[TrainingCallback] = [
            CancellationCallback(task_id),
            progress_cb,
        ]

        # Train
        trainer.train(total_timesteps=total_timesteps, callbacks=callbacks)

        # Save model as .pt (PyTorch)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        model_filename = f"{network_id}_{tl_id}_{algorithm}_{timestamp}.pt"
        model_path = MODELS_DIR / model_filename
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        trainer.save(str(model_path))

        # Save metadata alongside model
        model_meta = {
            "format": "pytorch",
            "network_id": network_id,
            "tl_id": tl_id,
            "algorithm": algorithm,
            "total_timesteps": total_timesteps,
            "observation_dim": int(env.observation_space.shape[0]),
            "action_dim": int(env.action_space.n),
            "num_phases": len(env._green_phases),
            "controlled_lanes": env._controlled_lanes,
            "trained_on_scenarios": [scenario],
            "created_at": datetime.now().isoformat(),
        }
        meta_path = Path(str(model_path) + ".metadata.json")
        with open(meta_path, "w") as f:
            json.dump(model_meta, f, indent=2)

        # Gather final metrics
        rl_metrics = progress_cb.get_final_metrics()

        results = {
            "baseline": baseline or {},
            "trained": {
                "avg_waiting_time": rl_metrics["avg_waiting_time"],
                "avg_queue_length": rl_metrics["avg_queue_length"],
                "throughput": rl_metrics["throughput"],
                "mean_reward": progress_cb.mean_reward,
            },
            "training_config": {
                "algorithm": algorithm,
                "total_timesteps": total_timesteps,
                "scenario": scenario,
            },
            "progress_history": progress_cb.progress_history,
        }
        results_path = Path(str(model_path) + ".results.json")
        with open(results_path, "w") as f:
            json.dump(results, f, indent=2)

        # Publish completion
        completion = {
            "task_id": task_id,
            "status": "completed",
            "timestep": total_timesteps,
            "total_timesteps": total_timesteps,
            "progress": 1.0,
            "model_path": str(model_path),
            "avg_waiting_time": rl_metrics["avg_waiting_time"],
            "avg_queue_length": rl_metrics["avg_queue_length"],
            "throughput": rl_metrics["throughput"],
            "network_id": network_id,
            "tl_id": tl_id,
            "algorithm": algorithm,
            "mean_reward": progress_cb.mean_reward,
        }
        if baseline:
            completion["baseline_avg_waiting_time"] = baseline.get("avg_waiting_time", 0.0)
            completion["baseline_avg_queue_length"] = baseline.get("avg_queue_length", 0.0)
            completion["baseline_throughput"] = baseline.get("throughput", 0)

        r.publish(f"task:{task_id}:updates", json.dumps(completion))
        r.setex(f"task:{task_id}:progress", 3600, json.dumps(completion))

        env.close()
        logger.info(f"Training complete: {model_path}")
        return {"status": "completed", "model_path": str(model_path)}

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
    """Multi-junction training task (unchanged - uses existing multi-agent infrastructure)."""
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
        from app.ml.multi_agent_env_v2 import MultiAgentTrafficLightEnvV2
        from app.ml.multi_agent_trainer import MultiAgentTrainer
        from app.ml.trainer import Algorithm as AlgoEnum

        network_path = str(SIMULATION_NETWORKS_DIR / f"{network_id}.net.xml")
        if not Path(network_path).exists():
            raise FileNotFoundError(f"Network file not found: {network_path}")

        env = MultiAgentTrafficLightEnvV2(
            network_path=network_path,
            network_id=network_id,
            tl_ids=tl_ids,
            algorithm=algorithm,
            scenario=scenario,
        )

        algo_enum = AlgoEnum.DQN if algorithm.lower() == "dqn" else AlgoEnum.PPO
        trainer = MultiAgentTrainer(env=env, algorithm=algo_enum)

        baseline = trainer.run_baseline(num_episodes=3)

        cancellation_cb = MultiCancellationCallback(task_id)
        multi_progress_cb = MultiProgressCallback(task_id, total_timesteps, tl_ids, baseline)
        callbacks = [cancellation_cb, multi_progress_cb]

        trainer.train(total_timesteps=total_timesteps, callbacks=callbacks)

        progress_json = r.get(f"task:{task_id}:progress")
        if progress_json:
            progress = json.loads(progress_json)
            if progress.get("status") == "cancelled":
                env.close()
                logger.info(f"Multi-junction task {task_id} was cancelled")
                return {"status": "cancelled", "task_id": task_id}

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        model_dir = MODELS_DIR / f"{network_id}_multi_{algorithm}_{timestamp}"
        trainer.save(str(model_dir))

        rl_metrics = multi_progress_cb.get_final_metrics()

        results = {
            "baseline": baseline or {},
            "trained": {
                "avg_waiting_time": rl_metrics["avg_waiting_time"],
                "avg_queue_length": rl_metrics["avg_queue_length"],
                "throughput": rl_metrics["throughput"],
                "mean_reward": rl_metrics.get("mean_reward", 0.0),
            },
            "training_config": {
                "algorithm": algorithm,
                "total_timesteps": total_timesteps,
                "scenario": scenario,
            },
            "progress_history": multi_progress_cb.progress_history,
        }
        results_path = model_dir / "results.json"
        with open(results_path, "w") as f:
            json.dump(results, f, indent=2)

        completion = {
            "task_id": task_id,
            "status": "completed",
            "timestep": total_timesteps,
            "total_timesteps": total_timesteps,
            "progress": 1.0,
            "model_path": str(model_dir),
            "avg_waiting_time": rl_metrics["avg_waiting_time"],
            "avg_queue_length": rl_metrics["avg_queue_length"],
            "throughput": rl_metrics["throughput"],
            "network_id": network_id,
            "tl_ids": tl_ids,
            "algorithm": algorithm,
            "mean_reward": 0.0,
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
