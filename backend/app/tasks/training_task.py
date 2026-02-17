"""Celery task for ML training of traffic light optimization.

This module provides a Celery task that runs ML training in an isolated SUMO
instance, publishing progress updates via Redis Pub/Sub for real-time monitoring.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import redis
from celery.result import AsyncResult
from stable_baselines3.common.callbacks import BaseCallback

from app.celery_app import celery_app
from app.ml.environment import TrafficLightEnv
from app.ml.trainer import Algorithm, MetricsLoggingCallback, TrafficLightTrainer
from app.services.osm_service import SIMULATION_NETWORKS_DIR

logger = logging.getLogger(__name__)

# Base directory for trained models
MODELS_DIR = Path(__file__).parent.parent.parent.parent / "simulation" / "models"


def get_redis_client() -> redis.Redis:
    """Get a Redis client for publishing updates.

    Returns:
        Redis client instance
    """
    from app.celery_app import CELERY_BROKER_URL

    # Parse Redis URL to get connection params
    # Format: redis://host:port/db
    return redis.from_url(CELERY_BROKER_URL)


@dataclass
class TrainingProgress:
    """Progress data for training task updates.

    Attributes:
        task_id: Celery task ID
        status: Current status (pending, started, running, completed, failed)
        timestep: Current training timestep
        total_timesteps: Total timesteps for training
        progress: Progress as a fraction (0.0 to 1.0)
        episode_count: Number of completed episodes
        mean_reward: Mean reward from recent episodes
        message: Human-readable status message
        model_path: Path to saved model (on completion)
        error: Error message (on failure)
    """

    task_id: str
    status: str
    timestep: int | None = None
    total_timesteps: int | None = None
    progress: float | None = None
    episode_count: int | None = None
    mean_reward: float | None = None
    message: str | None = None
    model_path: str | None = None
    error: str | None = None
    created_at: str | None = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "task_id": self.task_id,
            "status": self.status,
            "timestep": self.timestep,
            "total_timesteps": self.total_timesteps,
            "progress": self.progress,
            "episode_count": self.episode_count,
            "mean_reward": self.mean_reward,
            "message": self.message,
            "model_path": self.model_path,
            "error": self.error,
            "created_at": self.created_at,
        }


class CancellationCallback(BaseCallback):
    """Callback to check for task cancellation during training.

    This callback checks if the Celery task has been revoked and stops
    training gracefully if so.
    """

    def __init__(self, task_id: str, check_interval: int = 100, verbose: int = 0) -> None:
        """Initialize the cancellation callback.

        Args:
            task_id: Celery task ID to monitor
            check_interval: Check for cancellation every N steps
            verbose: Verbosity level
        """
        super().__init__(verbose)
        self.task_id = task_id
        self.check_interval = check_interval
        self._step_count = 0

    def _on_step(self) -> bool:
        """Check if task has been revoked.

        Returns:
            False if task is revoked (stop training), True otherwise
        """
        self._step_count += 1

        # Only check periodically to avoid overhead
        if self._step_count % self.check_interval != 0:
            return True

        # Check if task is revoked
        result = AsyncResult(self.task_id)
        if result.state == "REVOKED":
            logger.info(f"Task {self.task_id} was revoked, stopping training")
            return False

        return True


class ProgressPublishingCallback(BaseCallback):
    """Callback to publish training progress via Redis Pub/Sub.

    Publishes progress updates at configurable intervals for real-time
    monitoring via SSE.
    """

    def __init__(
        self,
        task_id: str,
        total_timesteps: int,
        redis_client: redis.Redis,
        publish_interval: int = 500,
        verbose: int = 0,
    ) -> None:
        """Initialize the progress publishing callback.

        Args:
            task_id: Celery task ID
            total_timesteps: Total training timesteps
            redis_client: Redis client for publishing
            publish_interval: Publish progress every N steps
            verbose: Verbosity level
        """
        super().__init__(verbose)
        self.task_id = task_id
        self.total_timesteps = total_timesteps
        self.redis_client = redis_client
        self.publish_interval = publish_interval
        self.channel = f"task:{task_id}:updates"
        self._episode_rewards: list[float] = []
        self._current_episode_reward = 0.0

    def _on_step(self) -> bool:
        """Publish progress update.

        Returns:
            Always True (continue training)
        """
        # Track episode rewards
        reward = self.locals.get("rewards", [0])[0]
        self._current_episode_reward += reward

        # Check for episode end
        dones = self.locals.get("dones", [False])
        if dones[0]:
            self._episode_rewards.append(self._current_episode_reward)
            self._current_episode_reward = 0.0

        # Publish progress at intervals
        if self.n_calls % self.publish_interval == 0:
            self._publish_progress()

        return True

    def _publish_progress(self) -> None:
        """Publish current progress to Redis."""
        import numpy as np

        # Calculate mean reward from recent episodes
        recent_rewards = self._episode_rewards[-10:] if self._episode_rewards else []
        mean_reward = float(np.mean(recent_rewards)) if recent_rewards else None

        progress = TrainingProgress(
            task_id=self.task_id,
            status="running",
            timestep=self.num_timesteps,
            total_timesteps=self.total_timesteps,
            progress=self.num_timesteps / self.total_timesteps,
            episode_count=len(self._episode_rewards),
            mean_reward=mean_reward,
            message=f"Training: {self.num_timesteps}/{self.total_timesteps} steps",
        )

        try:
            progress_data = json.dumps(progress.to_dict())
            # Publish for real-time SSE updates
            self.redis_client.publish(self.channel, progress_data)
            # Store in Redis for API polling (expires in 1 hour)
            self.redis_client.setex(f"task:{self.task_id}:progress", 3600, progress_data)
        except Exception as e:
            logger.warning(f"Failed to publish progress: {e}")

    @property
    def episode_rewards(self) -> list[float]:
        """Get recorded episode rewards."""
        return self._episode_rewards.copy()


def _get_network_path(network_id: str) -> Path:
    """Get the path to a SUMO network file.

    Args:
        network_id: ID of the network

    Returns:
        Path to the network file

    Raises:
        FileNotFoundError: If network file doesn't exist
    """
    network_path = SIMULATION_NETWORKS_DIR / f"{network_id}.net.xml"
    if not network_path.exists():
        raise FileNotFoundError(f"Network file not found: {network_path}")
    return network_path


def _generate_model_filename(network_id: str, tl_id: str, algorithm: Algorithm) -> str:
    """Generate a filename for a trained model.

    Args:
        network_id: ID of the network
        tl_id: ID of the traffic light
        algorithm: Algorithm used for training

    Returns:
        Model filename without extension
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{network_id}_{tl_id}_{algorithm.value}_{timestamp}"


def _save_model_metadata(
    model_path: Path,
    network_id: str,
    tl_id: str,
    algorithm: Algorithm,
    total_timesteps: int,
    env: TrafficLightEnv,
) -> None:
    """Save model metadata to a JSON file.

    Args:
        model_path: Path to the model file (without .zip extension)
        network_id: ID of the network
        tl_id: Traffic light ID
        algorithm: Algorithm used
        total_timesteps: Total training timesteps
        env: The training environment (for observation/action space info)
    """
    metadata = {
        "network_id": network_id,
        "tl_id": tl_id,
        "algorithm": algorithm.value,
        "total_timesteps": total_timesteps,
        "observation_dim": env.observation_space.shape[0] if hasattr(env.observation_space, "shape") else 0,
        "action_dim": env.action_space.n if hasattr(env.action_space, "n") else 0,
        "num_phases": getattr(env, "_num_phases", 4),
        "controlled_lanes": getattr(env, "_controlled_lanes", []),
        "trained_on_scenarios": [getattr(env, "scenario", "moderate")],
        "created_at": datetime.now().isoformat(),
    }

    metadata_path = Path(str(model_path) + ".metadata.json")
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2)

    logger.info(f"Saved model metadata to {metadata_path}")


def run_training(
    task_id: str,
    network_id: str,
    traffic_light_id: str,
    algorithm: str = "dqn",
    total_timesteps: int = 10000,
    scenario: str = "moderate",
) -> dict[str, Any]:
    """Run ML training for a traffic light.

    This is the core training logic extracted for testability.
    Creates an isolated SUMO instance, trains the model, and publishes progress.

    Args:
        task_id: Celery task ID (for progress publishing)
        network_id: ID of the SUMO network to train on
        traffic_light_id: ID of the traffic light to optimize
        algorithm: RL algorithm to use ('dqn' or 'ppo')
        total_timesteps: Total timesteps to train for
        scenario: Traffic scenario for training

    Returns:
        dict with training results including model path

    Raises:
        FileNotFoundError: If network file doesn't exist
        ValueError: If algorithm is invalid
    """
    redis_client = get_redis_client()
    channel = f"task:{task_id}:updates"
    env = None

    # Publish started event
    started_progress = TrainingProgress(
        task_id=task_id,
        status="started",
        total_timesteps=total_timesteps,
        message=f"Starting training for {traffic_light_id} on {network_id}",
    )
    redis_client.publish(channel, json.dumps(started_progress.to_dict()))

    try:
        # Validate algorithm
        try:
            algo_enum = Algorithm(algorithm.lower())
        except ValueError:
            raise ValueError(f"Invalid algorithm: {algorithm}. Must be 'dqn' or 'ppo'")

        # Get network path
        network_path = _get_network_path(network_id)

        # Create isolated SUMO environment
        logger.info(f"Creating TrafficLightEnv for {traffic_light_id} on {network_id}")
        env = TrafficLightEnv(
            network_path=str(network_path),
            network_id=network_id,
            tl_id=traffic_light_id,
            gui=False,  # Background task - no GUI
            scenario=scenario,
            algorithm=algo_enum,  # Pass algorithm for reward function selection
        )

        # Create trainer
        trainer = TrafficLightTrainer(env=env, algorithm=algo_enum)

        # Create callbacks
        cancellation_callback = CancellationCallback(task_id=task_id)
        progress_callback = ProgressPublishingCallback(
            task_id=task_id,
            total_timesteps=total_timesteps,
            redis_client=redis_client,
        )
        metrics_callback = MetricsLoggingCallback(log_interval=1000)

        # Train the model
        logger.info(f"Starting training: {total_timesteps} timesteps with {algorithm}")
        trainer.train(
            total_timesteps=total_timesteps,
            callbacks=[cancellation_callback, progress_callback, metrics_callback],
            log_interval=1000,
        )

        # Check if training was cancelled
        result = AsyncResult(task_id)
        if result.state == "REVOKED":
            cancelled_progress = TrainingProgress(
                task_id=task_id,
                status="cancelled",
                timestep=trainer.model.num_timesteps,
                total_timesteps=total_timesteps,
                progress=trainer.model.num_timesteps / total_timesteps,
                message="Training cancelled by user",
            )
            redis_client.publish(channel, json.dumps(cancelled_progress.to_dict()))
            return {"status": "cancelled", "task_id": task_id}

        # Save the model
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        model_filename = _generate_model_filename(network_id, traffic_light_id, algo_enum)
        model_path = MODELS_DIR / model_filename
        trainer.save(model_path)
        full_model_path = str(model_path) + ".zip"

        # Save metadata
        _save_model_metadata(
            model_path=model_path,
            network_id=network_id,
            tl_id=traffic_light_id,
            algorithm=algo_enum,
            total_timesteps=total_timesteps,
            env=env,
        )

        # Publish completed event
        import numpy as np

        episode_rewards = progress_callback.episode_rewards
        mean_reward = float(np.mean(episode_rewards[-10:])) if episode_rewards else None

        completed_progress = TrainingProgress(
            task_id=task_id,
            status="completed",
            timestep=total_timesteps,
            total_timesteps=total_timesteps,
            progress=1.0,
            episode_count=len(episode_rewards),
            mean_reward=mean_reward,
            message="Training completed successfully",
            model_path=full_model_path,
        )
        redis_client.publish(channel, json.dumps(completed_progress.to_dict()))

        logger.info(f"Training completed. Model saved to {full_model_path}")

        return {
            "status": "completed",
            "task_id": task_id,
            "model_path": full_model_path,
            "total_episodes": len(episode_rewards),
            "mean_reward": mean_reward,
        }

    except Exception as e:
        logger.error(f"Training failed: {e}")

        # Publish failed event
        failed_progress = TrainingProgress(
            task_id=task_id,
            status="failed",
            message=f"Training failed: {str(e)}",
            error=str(e),
        )
        redis_client.publish(channel, json.dumps(failed_progress.to_dict()))

        # Re-raise the exception so Celery marks task as failed
        raise

    finally:
        # Always close the environment
        if env is not None:
            try:
                env.close()
                logger.info("Environment closed")
            except Exception as e:
                logger.warning(f"Error closing environment: {e}")


@celery_app.task(bind=True, name="tasks.train_traffic_light")
def train_traffic_light(
    self,
    network_id: str,
    traffic_light_id: str,
    algorithm: str = "dqn",
    total_timesteps: int = 10000,
    scenario: str = "moderate",
) -> dict[str, Any]:
    """Celery task wrapper for ML training.

    This task creates its own isolated SUMO instance for training,
    publishes progress updates via Redis Pub/Sub, and supports cancellation.

    Args:
        network_id: ID of the SUMO network to train on
        traffic_light_id: ID of the traffic light to optimize
        algorithm: RL algorithm to use ('dqn' or 'ppo')
        total_timesteps: Total timesteps to train for
        scenario: Traffic scenario for training ('light', 'moderate', 'heavy', 'rush_hour')

    Returns:
        dict with training results including model path

    Raises:
        FileNotFoundError: If network file doesn't exist
        ValueError: If algorithm is invalid
    """
    task_id = self.request.id
    return run_training(
        task_id=task_id,
        network_id=network_id,
        traffic_light_id=traffic_light_id,
        algorithm=algorithm,
        total_timesteps=total_timesteps,
        scenario=scenario,
    )
