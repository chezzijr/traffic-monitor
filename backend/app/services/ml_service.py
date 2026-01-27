"""ML service for traffic light optimization training and inference.

This service provides an interface for training RL agents and using trained models
for traffic light control inference. It manages training jobs in background threads
and handles model persistence.
"""

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

import numpy as np
from stable_baselines3 import DQN, PPO
from stable_baselines3.common.base_class import BaseAlgorithm
from stable_baselines3.common.callbacks import BaseCallback

from app.ml.environment import TrafficLightEnv
from app.ml.trainer import Algorithm, MetricsLoggingCallback, TrafficLightTrainer
from app.services.osm_service import SIMULATION_NETWORKS_DIR

logger = logging.getLogger(__name__)

# Base directory for trained models
# Path: ml_service.py -> services -> app -> backend -> traffic-monitor -> simulation/models
MODELS_DIR = Path(__file__).parent.parent.parent.parent / "simulation" / "models"


class TrainingStatus(str, Enum):
    """Status of a training job."""

    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPING = "stopping"


@dataclass
class TrainingJob:
    """Represents an active or completed training job."""

    network_id: str
    tl_id: str
    algorithm: Algorithm
    total_timesteps: int
    status: TrainingStatus = TrainingStatus.IDLE
    current_timestep: int = 0
    start_time: datetime | None = None
    end_time: datetime | None = None
    error_message: str | None = None
    model_path: str | None = None
    episode_rewards: list[float] = field(default_factory=list)
    episode_lengths: list[int] = field(default_factory=list)


class StopTrainingCallback(BaseCallback):
    """Callback to allow stopping training early."""

    def __init__(self, stop_flag: threading.Event, verbose: int = 0) -> None:
        """Initialize the stop callback.

        Args:
            stop_flag: Threading event that signals when to stop
            verbose: Verbosity level
        """
        super().__init__(verbose)
        self._stop_flag = stop_flag

    def _on_step(self) -> bool:
        """Check if training should stop.

        Returns:
            False if stop requested, True to continue
        """
        return not self._stop_flag.is_set()


class MLServiceState:
    """Thread-safe state management for ML service."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._training_job: TrainingJob | None = None
        self._training_thread: threading.Thread | None = None
        self._stop_flag = threading.Event()
        self._trainer: TrafficLightTrainer | None = None
        self._metrics_callback: MetricsLoggingCallback | None = None
        self._loaded_model: BaseAlgorithm | None = None
        self._loaded_model_path: str | None = None

    @property
    def training_job(self) -> TrainingJob | None:
        with self._lock:
            return self._training_job

    @training_job.setter
    def training_job(self, value: TrainingJob | None) -> None:
        with self._lock:
            self._training_job = value


# Global service state
_state = MLServiceState()


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


def _run_training(
    network_id: str,
    tl_id: str,
    algorithm: Algorithm,
    total_timesteps: int,
) -> None:
    """Run training in a background thread.

    This function is executed in a separate thread and updates the global
    training job state as training progresses.

    Args:
        network_id: ID of the network to train on
        tl_id: ID of the traffic light to optimize
        algorithm: RL algorithm to use
        total_timesteps: Total timesteps to train for
    """
    env = None
    try:
        # Get network path
        network_path = _get_network_path(network_id)

        # Create environment
        env = TrafficLightEnv(
            network_path=str(network_path),
            network_id=network_id,
            tl_id=tl_id,
            gui=False,
        )

        # Create trainer
        trainer = TrafficLightTrainer(env=env, algorithm=algorithm)
        with _state._lock:
            _state._trainer = trainer

        # Create callbacks
        stop_callback = StopTrainingCallback(_state._stop_flag)
        metrics_callback = MetricsLoggingCallback(log_interval=1000)
        with _state._lock:
            _state._metrics_callback = metrics_callback

        logger.info(f"Starting training: {network_id}/{tl_id} with {algorithm.value}")

        # Train the model
        trainer.train(
            total_timesteps=total_timesteps,
            callbacks=[stop_callback],
            log_interval=1000,
        )

        # Check if training was stopped early
        with _state._lock:
            job = _state._training_job
            if job is None:
                return

            if _state._stop_flag.is_set():
                job.status = TrainingStatus.COMPLETED
                job.end_time = datetime.now()
                logger.info("Training stopped by user request")
            else:
                job.status = TrainingStatus.COMPLETED
                job.end_time = datetime.now()
                logger.info("Training completed successfully")

            # Save the model
            MODELS_DIR.mkdir(parents=True, exist_ok=True)
            model_filename = _generate_model_filename(network_id, tl_id, algorithm)
            model_path = MODELS_DIR / model_filename
            trainer.save(model_path)
            job.model_path = str(model_path) + ".zip"

            # Save final metrics
            job.episode_rewards = metrics_callback.episode_rewards
            job.episode_lengths = metrics_callback.episode_lengths
            job.current_timestep = trainer.model.num_timesteps

    except Exception as e:
        logger.error(f"Training failed: {e}")
        with _state._lock:
            job = _state._training_job
            if job is not None:
                job.status = TrainingStatus.FAILED
                job.end_time = datetime.now()
                job.error_message = str(e)

    finally:
        # Cleanup environment
        if env is not None:
            try:
                env.close()
            except Exception as e:
                logger.warning(f"Error closing environment: {e}")

        with _state._lock:
            _state._trainer = None
            _state._metrics_callback = None


def start_training(
    network_id: str,
    tl_id: str,
    algorithm: Algorithm | str = Algorithm.DQN,
    total_timesteps: int = 10000,
) -> dict[str, Any]:
    """Start a training job in the background.

    Args:
        network_id: ID of the network to train on
        tl_id: ID of the traffic light to optimize
        algorithm: RL algorithm to use (DQN or PPO)
        total_timesteps: Total timesteps to train for

    Returns:
        dict with job status

    Raises:
        RuntimeError: If training is already running
        FileNotFoundError: If network file doesn't exist
        ValueError: If algorithm is invalid
    """
    # Convert string algorithm to enum if needed
    if isinstance(algorithm, str):
        try:
            algorithm = Algorithm(algorithm.lower())
        except ValueError:
            raise ValueError(f"Invalid algorithm: {algorithm}. Must be 'dqn' or 'ppo'")

    # Validate network exists
    _get_network_path(network_id)

    with _state._lock:
        # Check if training is already running
        if _state._training_job is not None and _state._training_job.status == TrainingStatus.RUNNING:
            raise RuntimeError("Training is already running. Stop the current job first.")

        # Create new training job
        job = TrainingJob(
            network_id=network_id,
            tl_id=tl_id,
            algorithm=algorithm,
            total_timesteps=total_timesteps,
            status=TrainingStatus.RUNNING,
            start_time=datetime.now(),
        )
        _state._training_job = job
        _state._stop_flag.clear()

        # Start training thread
        _state._training_thread = threading.Thread(
            target=_run_training,
            args=(network_id, tl_id, algorithm, total_timesteps),
            daemon=True,
        )
        _state._training_thread.start()

    logger.info(f"Training job started: {network_id}/{tl_id}")

    return {
        "status": "started",
        "network_id": network_id,
        "tl_id": tl_id,
        "algorithm": str(algorithm),
        "total_timesteps": total_timesteps,
    }


def stop_training() -> dict[str, Any]:
    """Stop the current training job.

    Returns:
        dict with stop status

    Raises:
        RuntimeError: If no training job is running
    """
    with _state._lock:
        job = _state._training_job
        if job is None or job.status != TrainingStatus.RUNNING:
            raise RuntimeError("No training job is currently running")

        job.status = TrainingStatus.STOPPING
        _state._stop_flag.set()

    logger.info("Training stop requested")

    return {"status": "stopping"}


def get_training_status() -> dict[str, Any]:
    """Get the current training job status and metrics.

    Returns:
        dict with training status information
    """
    with _state._lock:
        job = _state._training_job

        if job is None:
            return {
                "status": TrainingStatus.IDLE.value,
                "job": None,
            }

        # Get current metrics from callback if available
        current_timestep = job.current_timestep
        episode_rewards = job.episode_rewards.copy()

        if _state._metrics_callback is not None:
            episode_rewards = _state._metrics_callback.episode_rewards

        if _state._trainer is not None and _state._trainer.model is not None:
            current_timestep = _state._trainer.model.num_timesteps

        # Calculate recent metrics
        recent_rewards = episode_rewards[-10:] if episode_rewards else []
        mean_reward = float(np.mean(recent_rewards)) if recent_rewards else 0.0
        std_reward = float(np.std(recent_rewards)) if recent_rewards else 0.0

        return {
            "status": job.status.value,
            "job": {
                "network_id": job.network_id,
                "tl_id": job.tl_id,
                "algorithm": str(job.algorithm),
                "total_timesteps": job.total_timesteps,
                "current_timestep": current_timestep,
                "progress": current_timestep / job.total_timesteps if job.total_timesteps > 0 else 0.0,
                "start_time": job.start_time.isoformat() if job.start_time else None,
                "end_time": job.end_time.isoformat() if job.end_time else None,
                "error_message": job.error_message,
                "model_path": job.model_path,
                "total_episodes": len(episode_rewards),
                "mean_reward": mean_reward,
                "std_reward": std_reward,
                "episode_rewards": recent_rewards,
            },
        }


def list_models() -> list[dict[str, Any]]:
    """List all available trained models.

    Returns:
        List of dicts with model information
    """
    models = []

    if not MODELS_DIR.exists():
        return models

    for model_file in MODELS_DIR.glob("*.zip"):
        # Parse filename: network_id_tl_id_algorithm_timestamp.zip
        stem = model_file.stem  # Remove .zip
        parts = stem.rsplit("_", 3)  # Split from right to handle network IDs with underscores

        if len(parts) >= 4:
            network_id = parts[0]
            tl_id = parts[1]
            algorithm = parts[2]
            timestamp = parts[3]
        else:
            # Fallback for unparseable filenames
            network_id = "unknown"
            tl_id = "unknown"
            algorithm = "unknown"
            timestamp = "unknown"

        stat = model_file.stat()
        models.append({
            "path": str(model_file),
            "filename": model_file.name,
            "network_id": network_id,
            "tl_id": tl_id,
            "algorithm": algorithm,
            "timestamp": timestamp,
            "size_bytes": stat.st_size,
            "created_at": datetime.fromtimestamp(stat.st_ctime).isoformat(),
            "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        })

    # Sort by modification time, newest first
    models.sort(key=lambda m: m["modified_at"], reverse=True)

    return models


def load_model(model_path: str) -> dict[str, Any]:
    """Load a trained model for inference.

    Args:
        model_path: Path to the model file (.zip)

    Returns:
        dict with load status

    Raises:
        FileNotFoundError: If model file doesn't exist
        ValueError: If model format is invalid
    """
    path = Path(model_path)

    if not path.exists():
        raise FileNotFoundError(f"Model file not found: {model_path}")

    # Determine algorithm from filename
    stem = path.stem
    algorithm = None

    if "_dqn_" in stem.lower():
        algorithm = Algorithm.DQN
    elif "_ppo_" in stem.lower():
        algorithm = Algorithm.PPO
    else:
        # Try to load as DQN first, then PPO
        try:
            model = DQN.load(str(path))
            algorithm = Algorithm.DQN
        except Exception:
            try:
                model = PPO.load(str(path))
                algorithm = Algorithm.PPO
            except Exception as e:
                raise ValueError(f"Could not load model. Unknown format: {e}")

    # Load the model
    if algorithm == Algorithm.DQN:
        model = DQN.load(str(path))
    else:
        model = PPO.load(str(path))

    with _state._lock:
        _state._loaded_model = model
        _state._loaded_model_path = str(path)

    logger.info(f"Loaded model from {path} (algorithm: {algorithm.value})")

    return {
        "status": "loaded",
        "path": str(path),
        "algorithm": str(algorithm),
    }


def predict(observation: list[float] | np.ndarray, deterministic: bool = True) -> dict[str, Any]:
    """Run inference with the loaded model.

    Args:
        observation: Observation array from the environment
        deterministic: Whether to use deterministic actions

    Returns:
        dict with prediction results

    Raises:
        RuntimeError: If no model is loaded
    """
    with _state._lock:
        model = _state._loaded_model
        if model is None:
            raise RuntimeError("No model loaded. Call load_model first.")

    # Convert to numpy array if needed
    if not isinstance(observation, np.ndarray):
        observation = np.array(observation, dtype=np.float32)

    # Ensure correct shape (add batch dimension if needed)
    if len(observation.shape) == 1:
        observation = observation.reshape(1, -1)

    # Get prediction (ignore internal states, only need action)
    action, _ = model.predict(observation, deterministic=deterministic)

    return {
        "action": int(action[0]) if hasattr(action, "__len__") else int(action),
        "deterministic": deterministic,
    }


def get_loaded_model_info() -> dict[str, Any] | None:
    """Get information about the currently loaded model.

    Returns:
        dict with model info or None if no model loaded
    """
    with _state._lock:
        if _state._loaded_model is None:
            return None

        model = _state._loaded_model
        return {
            "path": _state._loaded_model_path,
            "algorithm": type(model).__name__.lower(),
            "policy": type(model.policy).__name__,
            "observation_space": str(model.observation_space),
            "action_space": str(model.action_space),
        }


def unload_model() -> dict[str, Any]:
    """Unload the currently loaded model.

    Returns:
        dict with unload status
    """
    with _state._lock:
        if _state._loaded_model is None:
            return {"status": "no_model_loaded"}

        path = _state._loaded_model_path
        _state._loaded_model = None
        _state._loaded_model_path = None

    logger.info(f"Unloaded model: {path}")

    return {"status": "unloaded", "path": path}


def delete_model(model_path: str) -> dict[str, Any]:
    """Delete a trained model file.

    Args:
        model_path: Path to the model file

    Returns:
        dict with deletion status

    Raises:
        FileNotFoundError: If model file doesn't exist
        RuntimeError: If trying to delete a currently loaded model
    """
    path = Path(model_path)

    if not path.exists():
        raise FileNotFoundError(f"Model file not found: {model_path}")

    # Check if this model is currently loaded
    with _state._lock:
        if _state._loaded_model_path == str(path):
            raise RuntimeError("Cannot delete currently loaded model. Unload it first.")

    path.unlink()
    logger.info(f"Deleted model: {path}")

    return {"status": "deleted", "path": str(path)}


def is_training_running() -> bool:
    """Check if a training job is currently running.

    Returns:
        True if training is running, False otherwise
    """
    with _state._lock:
        return _state._training_job is not None and _state._training_job.status == TrainingStatus.RUNNING


def is_model_loaded() -> bool:
    """Check if a model is currently loaded.

    Returns:
        True if a model is loaded, False otherwise
    """
    with _state._lock:
        return _state._loaded_model is not None
