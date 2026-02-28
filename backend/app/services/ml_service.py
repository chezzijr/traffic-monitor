"""ML service for model management and inference.

Training is handled by Celery tasks (see tasks/training_task.py).
This service manages model loading, inference, and listing.
"""

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from stable_baselines3 import DQN, PPO
from stable_baselines3.common.base_class import BaseAlgorithm

from app.ml.trainer import Algorithm

logger = logging.getLogger(__name__)

MODELS_DIR = Path(__file__).parent.parent.parent.parent / "simulation" / "models"


class _ModelState:
    """Thread-safe state for loaded model."""

    def __init__(self):
        self._lock = threading.Lock()
        self._loaded_model: BaseAlgorithm | None = None
        self._loaded_model_path: str | None = None

    @property
    def model(self) -> BaseAlgorithm | None:
        with self._lock:
            return self._loaded_model

    @property
    def model_path(self) -> str | None:
        with self._lock:
            return self._loaded_model_path


_state = _ModelState()


def list_models() -> list[dict[str, Any]]:
    """List all available trained models (single + multi-agent)."""
    models = []

    if not MODELS_DIR.exists():
        return models

    # Single-agent models: *.zip files
    for model_file in MODELS_DIR.glob("*.zip"):
        stem = model_file.stem
        parts = stem.rsplit("_", 3)

        if len(parts) >= 4:
            network_id, tl_id, algorithm, timestamp = parts[0], parts[1], parts[2], parts[3]
        else:
            network_id, tl_id, algorithm, timestamp = "unknown", "unknown", "unknown", "unknown"

        # Try to load metadata
        meta_path = Path(str(model_file) + ".metadata.json")
        metadata = {}
        if meta_path.exists():
            try:
                with open(meta_path) as f:
                    metadata = json.load(f)
            except Exception:
                pass

        stat = model_file.stat()
        models.append({
            "model_id": model_file.stem,
            "model_path": str(model_file),
            "path": str(model_file),
            "filename": model_file.name,
            "network_id": metadata.get("network_id", network_id),
            "tl_id": metadata.get("tl_id", tl_id),
            "algorithm": metadata.get("algorithm", algorithm),
            "timestamp": timestamp,
            "size_bytes": stat.st_size,
            "created_at": metadata.get("created_at", datetime.fromtimestamp(stat.st_ctime).isoformat()),
            "type": "single",
        })

    # Multi-agent models: directories with metadata.json
    for meta_file in MODELS_DIR.glob("*/metadata.json"):
        model_dir = meta_file.parent
        try:
            with open(meta_file) as f:
                metadata = json.load(f)
        except Exception:
            continue

        # Count agent .zip files
        agent_zips = list(model_dir.glob("*.zip"))

        models.append({
            "model_id": model_dir.name,
            "model_path": str(model_dir),
            "path": str(model_dir),
            "filename": model_dir.name,
            "network_id": metadata.get("network_id", "unknown"),
            "tl_ids": metadata.get("tl_ids", []),
            "algorithm": metadata.get("algorithm", "unknown"),
            "timestamp": model_dir.name.rsplit("_", 1)[-1] if "_" in model_dir.name else "unknown",
            "num_agents": len(agent_zips),
            "created_at": metadata.get("created_at", "unknown"),
            "type": "multi",
        })

    models.sort(key=lambda m: m.get("created_at", ""), reverse=True)
    return models


def load_model(model_path: str) -> dict[str, Any]:
    """Load a trained model for inference."""
    path = Path(model_path)
    if not path.exists():
        raise FileNotFoundError(f"Model file not found: {model_path}")

    stem = path.stem
    if "_dqn_" in stem.lower():
        algorithm = Algorithm.DQN
    elif "_ppo_" in stem.lower():
        algorithm = Algorithm.PPO
    else:
        try:
            model = DQN.load(str(path))
            algorithm = Algorithm.DQN
        except Exception:
            try:
                model = PPO.load(str(path))
                algorithm = Algorithm.PPO
            except Exception as e:
                raise ValueError(f"Could not load model: {e}")

    if algorithm == Algorithm.DQN:
        model = DQN.load(str(path))
    else:
        model = PPO.load(str(path))

    with _state._lock:
        _state._loaded_model = model
        _state._loaded_model_path = str(path)

    logger.info(f"Loaded model from {path} ({algorithm.value})")
    return {"status": "loaded", "path": str(path), "algorithm": algorithm.value}


def predict(observation: list[float] | np.ndarray, deterministic: bool = True) -> dict[str, Any]:
    """Run inference with the loaded model."""
    with _state._lock:
        model = _state._loaded_model
        if model is None:
            raise RuntimeError("No model loaded")

    if not isinstance(observation, np.ndarray):
        observation = np.array(observation, dtype=np.float32)
    if len(observation.shape) == 1:
        observation = observation.reshape(1, -1)

    action, _ = model.predict(observation, deterministic=deterministic)
    return {"action": int(action[0]) if hasattr(action, "__len__") else int(action)}


def get_loaded_model_info() -> dict[str, Any] | None:
    """Get info about the currently loaded model."""
    with _state._lock:
        if _state._loaded_model is None:
            return None
        model = _state._loaded_model
        return {
            "path": _state._loaded_model_path,
            "algorithm": type(model).__name__.lower(),
            "observation_space": str(model.observation_space),
            "action_space": str(model.action_space),
        }


def unload_model() -> dict[str, Any]:
    """Unload the currently loaded model."""
    with _state._lock:
        if _state._loaded_model is None:
            return {"status": "no_model_loaded"}
        path = _state._loaded_model_path
        _state._loaded_model = None
        _state._loaded_model_path = None
    return {"status": "unloaded", "path": path}


def delete_model(model_path: str) -> dict[str, Any]:
    """Delete a trained model file."""
    path = Path(model_path)
    if not path.exists():
        raise FileNotFoundError(f"Model not found: {model_path}")

    with _state._lock:
        if _state._loaded_model_path == str(path):
            raise RuntimeError("Cannot delete currently loaded model")

    if path.is_dir():
        import shutil
        shutil.rmtree(path)
    else:
        path.unlink()
        # Also delete metadata file if exists
        meta_path = Path(str(path) + ".metadata.json")
        if meta_path.exists():
            meta_path.unlink()

    return {"status": "deleted", "path": str(path)}


def is_model_loaded() -> bool:
    """Check if a model is currently loaded."""
    with _state._lock:
        return _state._loaded_model is not None
