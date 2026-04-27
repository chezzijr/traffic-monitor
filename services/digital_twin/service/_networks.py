"""Lightweight DQN network definition for model loading in the digital twin.

Mirrors the architecture from backend/app/ml/networks/dqn_network.py
so that .pt state dicts can be loaded without importing the backend.
"""

import torch
import torch.nn as nn


class DQNNetwork(nn.Module):
    """3-layer MLP for DQN Q-value estimation.

    Architecture: input -> fc1(20) -> ReLU -> fc2(20) -> ReLU -> fc3(num_actions)
    """

    def __init__(self, ob_length: int, num_actions: int):
        super().__init__()
        self.fc1 = nn.Linear(ob_length, 20)
        self.fc2 = nn.Linear(20, 20)
        self.fc3 = nn.Linear(20, num_actions)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = torch.relu(self.fc1(x))
        x = torch.relu(self.fc2(x))
        return self.fc3(x)
