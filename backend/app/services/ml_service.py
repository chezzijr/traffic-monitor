"""ML service for model management and inference.

Training is handled by Celery tasks (see tasks/training_task.py).
This service manages model loading, inference, and listing.
Supports both legacy SB3 .zip models and new PyTorch .pt models.
"""

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import torch

from app.config import settings
from app.ml.networks.dqn_network import DQNAgent
from app.ml.networks.ppo_network import PPOAgent
from app.ml.trainer import Algorithm

logger = logging.getLogger(__name__)

MODELS_DIR = settings.simulation_models_dir


class _ModelState:
    """Thread-safe state for loaded model."""

    def __init__(self):
        self._lock = threading.Lock()
        self._loaded_model: Any = None  # DQNAgent, PPOAgent, or legacy SB3 model
        self._loaded_model_path: str | None = None
        self._model_format: str | None = None  # "pytorch" or "sb3"
        self._algorithm: str | None = None

    @property
    def model(self) -> Any:
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

    # Single-agent models: *.zip (legacy SB3) and *.pt (PyTorch) files
    for model_file in list(MODELS_DIR.glob("*.zip")) + list(MODELS_DIR.glob("*.pt")):
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

        # Try to load results
        results_path = Path(str(model_file) + ".results.json")
        results = None
        if results_path.exists():
            try:
                with open(results_path) as f:
                    results = json.load(f)
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
            "results": results,
        })

    # Multi-agent models: directories with metadata.json
    for meta_file in MODELS_DIR.glob("*/metadata.json"):
        model_dir = meta_file.parent
        try:
            with open(meta_file) as f:
                metadata = json.load(f)
        except Exception:
            continue

        # Try to load results
        results_path = model_dir / "results.json"
        results = None
        if results_path.exists():
            try:
                with open(results_path) as f:
                    results = json.load(f)
            except Exception:
                pass

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
            "results": results,
        })

    models.sort(key=lambda m: m.get("created_at", ""), reverse=True)
    return models


def load_model(model_path: str) -> dict[str, Any]:
    """Load a trained model for inference. Supports .pt (PyTorch) and .zip (legacy SB3)."""
    path = Path(model_path)
    if not path.exists():
        raise FileNotFoundError(f"Model file not found: {model_path}")

    stem = path.stem
    suffix = path.suffix.lower()

    # Determine algorithm from filename
    if "_colight_" in stem.lower():
        algorithm = Algorithm.COLIGHT
    elif "_dqn_" in stem.lower():
        algorithm = Algorithm.DQN
    elif "_ppo_" in stem.lower():
        algorithm = Algorithm.PPO
    else:
        algorithm = Algorithm.DQN  # Default

    if suffix == ".pt":
        # PyTorch model (new format)
        checkpoint = torch.load(str(path), map_location="cpu", weights_only=False)
        algo_str = checkpoint.get("algorithm", algorithm.value)
        ob_length = checkpoint["ob_length"]
        num_actions = checkpoint["num_actions"]

        if algo_str == "colight":
            from app.ml.networks.colight_network import CoLightAgent

            agent = CoLightAgent(
                ob_length=ob_length,
                num_actions=num_actions,
                num_intersections=checkpoint["num_intersections"],
                phase_lengths=checkpoint["phase_lengths"],
                edge_index=checkpoint["edge_index"],
                **checkpoint.get("network_params", {}),
            )
            agent.q_network.load_state_dict(checkpoint["model_state"])
            if "target_state" in checkpoint:
                agent.target_network.load_state_dict(checkpoint["target_state"])
            agent.q_network.eval()
            algorithm = Algorithm.COLIGHT
        elif algo_str == "dqn":
            agent = DQNAgent(ob_length=ob_length, num_actions=num_actions)
            agent.q_network.load_state_dict(checkpoint["model_state"])
            if "target_state" in checkpoint:
                agent.target_network.load_state_dict(checkpoint["target_state"])
            agent.q_network.eval()
            algorithm = Algorithm.DQN
        else:
            agent = PPOAgent(ob_length=ob_length, num_actions=num_actions)
            agent.network.load_state_dict(checkpoint["model_state"])
            agent.network.eval()
            algorithm = Algorithm.PPO

        with _state._lock:
            _state._loaded_model = agent
            _state._loaded_model_path = str(path)
            _state._model_format = "pytorch"
            _state._algorithm = algorithm.value
    else:
        # Legacy SB3 .zip model
        try:
            from stable_baselines3 import DQN, PPO
            if algorithm == Algorithm.DQN:
                model = DQN.load(str(path))
            else:
                model = PPO.load(str(path))
        except Exception as e:
            raise ValueError(f"Could not load SB3 model: {e}")

        with _state._lock:
            _state._loaded_model = model
            _state._loaded_model_path = str(path)
            _state._model_format = "sb3"
            _state._algorithm = algorithm.value

    logger.info(f"Loaded model from {path} ({algorithm.value}, format={_state._model_format})")
    return {"status": "loaded", "path": str(path), "algorithm": algorithm.value}


def predict(observation: list[float] | np.ndarray, deterministic: bool = True) -> dict[str, Any]:
    """Run inference with the loaded model. Supports PyTorch and SB3 models."""
    with _state._lock:
        model = _state._loaded_model
        model_format = _state._model_format
        algorithm = _state._algorithm
        if model is None:
            raise RuntimeError("No model loaded")

    if not isinstance(observation, np.ndarray):
        observation = np.array(observation, dtype=np.float32)

    if model_format == "pytorch":
        from app.ml.networks.colight_network import CoLightAgent as _CoLightAgent

        if isinstance(model, _CoLightAgent):
            # CoLight expects [N, ob_length] observation
            if len(observation.shape) == 1:
                n = model.num_intersections
                observation = observation.reshape(n, -1)
            actions = model.select_action(observation, deterministic=deterministic)
            return {"actions": actions.tolist()}
        elif isinstance(model, DQNAgent):
            if len(observation.shape) > 1:
                observation = observation.flatten()
            action = model.select_action(observation, deterministic=deterministic)
        elif isinstance(model, PPOAgent):
            if len(observation.shape) > 1:
                observation = observation.flatten()
            if deterministic:
                with torch.no_grad():
                    obs_t = torch.FloatTensor(observation).unsqueeze(0).to(model.device)
                    action_probs, _ = model.network(obs_t)
                    action = int(action_probs.argmax(dim=1).item())
            else:
                action, _, _ = model.select_action(observation)
        else:
            raise RuntimeError(f"Unknown PyTorch model type: {type(model)}")
        return {"action": int(action)}
    else:
        # Legacy SB3 model
        if len(observation.shape) == 1:
            observation = observation.reshape(1, -1)
        action, _ = model.predict(observation, deterministic=deterministic)
        return {"action": int(action[0]) if hasattr(action, "__len__") else int(action)}


def get_loaded_model_info() -> dict[str, Any] | None:
    """Get info about the currently loaded model."""
    with _state._lock:
        if _state._loaded_model is None:
            return None
        return {
            "path": _state._loaded_model_path,
            "algorithm": _state._algorithm or "unknown",
            "format": _state._model_format or "unknown",
        }


def unload_model() -> dict[str, Any]:
    """Unload the currently loaded model."""
    with _state._lock:
        if _state._loaded_model is None:
            return {"status": "no_model_loaded"}
        path = _state._loaded_model_path
        _state._loaded_model = None
        _state._loaded_model_path = None
        _state._model_format = None
        _state._algorithm = None
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
        # Delete associated metadata and results files
        for suffix in [".metadata.json", ".results.json"]:
            p = Path(str(path) + suffix)
            if p.exists():
                p.unlink()

    return {"status": "deleted", "path": str(path)}


def is_model_loaded() -> bool:
    """Check if a model is currently loaded."""
    with _state._lock:
        return _state._loaded_model is not None
