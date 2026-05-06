"""Minimal RL model loader/inference for digital twin deploy loop."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn as nn


class DQNNetwork(nn.Module):
    """Simple MLP matching the training architecture."""

    def __init__(self, ob_length: int, num_actions: int) -> None:
        super().__init__()
        self.fc1 = nn.Linear(ob_length, 20)
        self.fc2 = nn.Linear(20, 20)
        self.fc3 = nn.Linear(20, num_actions)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = torch.relu(self.fc1(x))
        x = torch.relu(self.fc2(x))
        return self.fc3(x)


class PPONetwork(nn.Module):
    """Actor head of the PPO network (value head not needed for inference)."""

    def __init__(self, ob_length: int, num_actions: int) -> None:
        super().__init__()
        self.fc1 = nn.Linear(ob_length, 64)
        self.fc2 = nn.Linear(64, 64)
        self.pi_head = nn.Linear(64, num_actions)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = torch.relu(self.fc1(x))
        x = torch.relu(self.fc2(x))
        return torch.softmax(self.pi_head(x), dim=-1)


class RLModel:
    """Load and run inference for DQN/PPO .pt checkpoints."""

    def __init__(self) -> None:
        self.model: nn.Module | None = None
        self.algorithm: str | None = None
        self.ob_length: int = 0
        self.num_actions: int = 0
        self.device = torch.device("cpu")
        self.model_path: str | None = None

    def load(self, model_path: str) -> dict[str, Any]:
        path = Path(model_path)
        if not path.exists():
            raise FileNotFoundError(f"Model file not found: {model_path}")

        if path.suffix.lower() != ".pt":
            raise ValueError("Only .pt models are supported in the digital twin deploy loop")

        checkpoint = torch.load(str(path), map_location="cpu", weights_only=False)
        algorithm = str(checkpoint.get("algorithm", "dqn")).lower()
        ob_length = int(checkpoint["ob_length"])
        num_actions = int(checkpoint["num_actions"])

        if algorithm == "dqn":
            model = DQNNetwork(ob_length, num_actions)
            model.load_state_dict(checkpoint["model_state"])
        elif algorithm == "ppo":
            model = PPONetwork(ob_length, num_actions)
            model.load_state_dict(checkpoint["model_state"])
        else:
            raise ValueError(f"Unsupported algorithm for deploy: {algorithm}")

        model.eval()

        self.model = model
        self.algorithm = algorithm
        self.ob_length = ob_length
        self.num_actions = num_actions
        self.model_path = str(path)

        return {
            "status": "loaded",
            "path": str(path),
            "algorithm": algorithm,
            "ob_length": ob_length,
            "num_actions": num_actions,
        }

    def predict(self, observation: list[float] | np.ndarray) -> int:
        if self.model is None:
            raise RuntimeError("No model loaded")

        if not isinstance(observation, np.ndarray):
            obs = np.array(observation, dtype=np.float32)
        else:
            obs = observation.astype(np.float32)

        obs = obs.flatten()

        if self.ob_length and obs.size != self.ob_length:
            if obs.size < self.ob_length:
                pad = np.zeros(self.ob_length - obs.size, dtype=np.float32)
                obs = np.concatenate([obs, pad])
            else:
                obs = obs[: self.ob_length]

        obs_tensor = torch.FloatTensor(obs).unsqueeze(0)

        with torch.no_grad():
            if self.algorithm == "ppo":
                probs = self.model(obs_tensor)
                action = int(probs.argmax(dim=1).item())
            else:
                q_values = self.model(obs_tensor)
                action = int(q_values.argmax(dim=1).item())

        return action
