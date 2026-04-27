"""DQN neural network and standalone agent for traffic light control."""

import copy
import logging
import random
from collections import deque

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.nn.utils import clip_grad_norm_

logger = logging.getLogger(__name__)


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


class DQNAgent:
    """Standalone DQN agent with replay buffer, epsilon-greedy, and target network.

    Used for custom multi-agent training loop (not SB3).
    """

    def __init__(
        self,
        ob_length: int,
        num_actions: int,
        lr: float = 1e-3,
        gamma: float = 0.95,
        epsilon_start: float = 0.1,
        epsilon_min: float = 0.01,
        epsilon_decay: float = 0.995,
        grad_clip: float = 5.0,
        buffer_size: int = 5000,
        batch_size: int = 64,
        device: str = "cpu",
    ):
        self.num_actions = num_actions
        self.gamma = gamma
        self.epsilon = epsilon_start
        self.epsilon_start = epsilon_start
        self.epsilon_min = epsilon_min
        self.epsilon_decay = epsilon_decay
        self.grad_clip = grad_clip
        self.device = torch.device(device)

        self.q_network = DQNNetwork(ob_length, num_actions).to(self.device)
        self.target_network = copy.deepcopy(self.q_network).to(self.device)
        self.target_network.eval()

        self.optimizer = optim.RMSprop(
            self.q_network.parameters(), lr=lr, alpha=0.9, centered=False, eps=1e-7
        )
        self.loss_fn = nn.MSELoss()

        self.replay_buffer = deque(maxlen=buffer_size)
        self.batch_size = batch_size

    def select_action(self, obs: np.ndarray, deterministic: bool = False) -> int:
        """Epsilon-greedy action selection."""
        if not deterministic and np.random.random() < self.epsilon:
            return np.random.randint(self.num_actions)

        with torch.no_grad():
            obs_tensor = torch.FloatTensor(obs).unsqueeze(0).to(self.device)
            q_values = self.q_network(obs_tensor)
            return int(q_values.argmax(dim=1).item())

    def update(self, batch: dict[str, np.ndarray]) -> float:
        """Perform a gradient update from a batch of transitions.

        Args:
            batch: dict with keys 'obs', 'actions', 'rewards', 'next_obs', 'dones'

        Returns:
            Loss value.
        """
        obs = torch.FloatTensor(batch["obs"]).to(self.device)
        actions = torch.LongTensor(batch["actions"]).to(self.device)
        rewards = torch.FloatTensor(batch["rewards"]).to(self.device)
        next_obs = torch.FloatTensor(batch["next_obs"]).to(self.device)
        dones = torch.FloatTensor(batch["dones"]).to(self.device)

        # Current Q values
        q_values = self.q_network(obs).gather(1, actions.unsqueeze(1)).squeeze(1)

        # Target Q values
        with torch.no_grad():
            next_q_values = self.target_network(next_obs).max(dim=1).values
            target_q = rewards + self.gamma * next_q_values * (1 - dones)

        loss = self.loss_fn(q_values, target_q)

        self.optimizer.zero_grad()
        loss.backward()
        clip_grad_norm_(self.q_network.parameters(), self.grad_clip)
        self.optimizer.step()

        logger.debug("DQN update loss: %.6f", loss.item())

        return loss.item()

    def update_target_network(self):
        """Hard copy of weights to target network (LibSignal pattern)."""
        self.target_network.load_state_dict(self.q_network.state_dict())
        logger.debug("Target network updated (hard copy)")

    def decay_epsilon(self):
        """Multiplicative epsilon decay (LibSignal pattern)."""
        if self.epsilon > self.epsilon_min:
            self.epsilon *= self.epsilon_decay
        logger.debug("Epsilon decayed to %.6f", self.epsilon)

    def remember(self, obs, action, reward, next_obs, done):
        """Store transition in replay buffer."""
        self.replay_buffer.append((obs, action, reward, next_obs, done))

    def can_train(self) -> bool:
        """Check if enough samples in buffer for training."""
        return len(self.replay_buffer) >= self.batch_size

    def sample_batch(self) -> dict[str, np.ndarray]:
        """Sample a random batch from replay buffer."""
        batch = random.sample(self.replay_buffer, self.batch_size)
        obs, actions, rewards, next_obs, dones = zip(*batch)
        return {
            "obs": np.array(obs, dtype=np.float32),
            "actions": np.array(actions, dtype=np.int64),
            "rewards": np.array(rewards, dtype=np.float32),
            "next_obs": np.array(next_obs, dtype=np.float32),
            "dones": np.array(dones, dtype=np.float32),
        }
