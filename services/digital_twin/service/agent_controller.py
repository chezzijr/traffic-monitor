"""RL agent controller for traffic light control during sync.

Loads a trained model (.pt or .zip) and provides inference to
control the SUMO traffic light at each decision step.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import torch

logger = logging.getLogger(__name__)


class AgentController:
    """Wraps a trained RL model for traffic light inference."""

    def __init__(self) -> None:
        self._model = None
        self._model_path: str | None = None
        self._model_type: str | None = None  # "pt" or "sb3"
        self._num_actions: int = 0
        self._ob_length: int = 0

    def load_model(self, model_path: str) -> None:
        """Load a trained model. Auto-detects .pt vs .zip format."""
        path = Path(model_path)
        if not path.exists():
            raise FileNotFoundError(f"Model not found: {model_path}")

        if path.suffix == ".pt":
            self._load_pt(path)
        elif path.suffix == ".zip":
            self._load_sb3(path)
        else:
            raise ValueError(f"Unknown model format: {path.suffix}")

        self._model_path = str(path)
        logger.info("Loaded model from %s (type=%s)", path, self._model_type)

    def _load_pt(self, path: Path) -> None:
        """Load a custom PyTorch DQN/PPO state dict."""
        from service._networks import DQNNetwork

        checkpoint = torch.load(path, map_location="cpu", weights_only=False)

        # Handle nested checkpoints (e.g. from Stable Baselines or custom loops)
        state_dict = checkpoint
        # Add 'model_state' to the search keys as seen in user's log
        for key in ["model_state", "state_dict", "policy_state_dict", "model_state_dict"]:
            if key in checkpoint:
                state_dict = checkpoint[key]
                break

        # Check for embedded metadata to avoid inference
        ob_length = checkpoint.get("ob_length")
        num_actions = checkpoint.get("num_actions")

        if ob_length is None or num_actions is None:
            # Fallback to inference if metadata is missing
            weight_keys = [
                k for k in state_dict.keys()
                if ("weight" in k or "fc" in k)
                and hasattr(state_dict[k], "shape")
                and len(state_dict[k].shape) > 0
            ]
            if not weight_keys:
                weight_keys = [k for k in state_dict.keys() if hasattr(state_dict[k], "shape") and len(state_dict[k].shape) > 0]

            if not weight_keys:
                logger.error("State dict keys: %s", list(state_dict.keys())[:20])
                raise ValueError("Could not find any weights in state_dict.")

            first_key = weight_keys[0]
            last_key = weight_keys[-1]
            shape = state_dict[first_key].shape
            ob_length = shape[1] if len(shape) > 1 else shape[0]
            num_actions = state_dict[last_key].shape[0]

        logger.info("Ready to build network: input=%d, output=%d", ob_length, num_actions)
        model = DQNNetwork(ob_length, num_actions)
        try:
            model.load_state_dict(state_dict)
        except Exception as e:
            logger.error("Failed to load state_dict. Keys: %s", list(state_dict.keys())[:10])
            raise e

        model.eval()
        self._model = model

        self._model_type = "pt"
        self._ob_length = ob_length
        self._num_actions = num_actions

    def _load_sb3(self, path: Path) -> None:
        """Load a Stable-Baselines3 model (.zip)."""
        try:
            from stable_baselines3 import DQN, PPO

            # Try DQN first, then PPO
            try:
                model = DQN.load(str(path))
            except Exception:
                model = PPO.load(str(path))

            self._model = model
            self._model_type = "sb3"
            self._num_actions = model.action_space.n
            self._ob_length = model.observation_space.shape[0]
        except ImportError:
            raise RuntimeError(
                "stable-baselines3 is required to load .zip models"
            )

    def build_observation(self, sumo_manager) -> np.ndarray:
        """Build the observation vector from current SUMO state.

        Format: [lane_vehicle_counts..., phase_one_hot...]
        Must match the training environment's observation space.
        """
        conn = sumo_manager._conn()
        tl_id = sumo_manager.get_tl_id()

        # Get controlled lanes and count vehicles per lane
        controlled_lanes = conn.trafficlight.getControlledLanes(tl_id)
        # Remove duplicates while preserving order
        seen = set()
        unique_lanes = []
        for lane in controlled_lanes:
            if lane not in seen:
                seen.add(lane)
                unique_lanes.append(lane)

        lane_counts = []
        for lane in unique_lanes:
            try:
                count = conn.lane.getLastStepVehicleNumber(lane)
            except Exception:
                count = 0
            lane_counts.append(float(count))

        # Get current phase as one-hot
        current_phase = conn.trafficlight.getPhase(tl_id)
        num_phases = sumo_manager.get_num_phases()

        # Only encode green phases (skip yellow/red-only phases)
        # For simplicity, encode all phases
        phase_one_hot = [0.0] * num_phases
        if 0 <= current_phase < num_phases:
            phase_one_hot[current_phase] = 1.0

        obs = np.array(lane_counts + phase_one_hot, dtype=np.float32)

        # Ensure observation matches what the model expects
        if self._ob_length > 0 and obs.shape[0] != self._ob_length:
            logger.warning("Observation dimension mismatch: got %d, model expects %d. Padding/Truncating.", obs.shape[0], self._ob_length)
            if obs.shape[0] > self._ob_length:
                obs = obs[:self._ob_length]
            else:
                padding = np.zeros(self._ob_length - obs.shape[0], dtype=np.float32)
                obs = np.concatenate([obs, padding])

        return obs


    def select_action(self, observation: np.ndarray) -> int:
        """Run inference to get the next phase index."""
        if self._model is None:
            raise RuntimeError("No model loaded")

        if self._model_type == "pt":
            with torch.no_grad():
                obs_tensor = torch.FloatTensor(observation).unsqueeze(0)
                q_values = self._model(obs_tensor)
                return int(q_values.argmax(dim=1).item())
        elif self._model_type == "sb3":
            action, _ = self._model.predict(
                observation.reshape(1, -1), deterministic=True,
            )
            return int(action[0]) if hasattr(action, "__len__") else int(action)

        raise RuntimeError(f"Unknown model type: {self._model_type}")

    def step(self, sumo_manager) -> None:
        """Build observation, get action, and apply to SUMO."""
        if self._model is None:
            return

        obs = self.build_observation(sumo_manager)
        action = self.select_action(obs)

        # Safety: Ensure action is within valid range of current phases
        num_phases = sumo_manager.get_num_phases()
        if action >= num_phases:
            logger.warning("Agent selected out-of-bounds action %d (max %d). Clamping.", action, num_phases - 1)
            action = num_phases - 1

        sumo_manager.set_traffic_light_phase(action)

        return action

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    @property
    def model_info(self) -> dict | None:
        if not self.is_loaded:
            return None
        return {
            "path": self._model_path,
            "type": self._model_type,
            "ob_length": self._ob_length,
            "num_actions": self._num_actions,
        }
