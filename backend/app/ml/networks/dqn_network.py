"""DQN neural network and standalone agent for traffic light control."""

import copy

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim


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
        tau: float = 0.005,
        epsilon_start: float = 0.5,
        epsilon_end: float = 0.01,
        device: str = "cpu",
    ):
        self.num_actions = num_actions
        self.gamma = gamma
        self.tau = tau
        self.epsilon = epsilon_start
        self.epsilon_start = epsilon_start
        self.epsilon_end = epsilon_end
        self.device = torch.device(device)

        self.q_network = DQNNetwork(ob_length, num_actions).to(self.device)
        self.target_network = copy.deepcopy(self.q_network).to(self.device)
        self.target_network.eval()

        self.optimizer = optim.RMSprop(self.q_network.parameters(), lr=lr)
        self.loss_fn = nn.MSELoss()

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
        self.optimizer.step()

        return loss.item()

    def update_target(self):
        """Polyak averaging update of target network."""
        for param, target_param in zip(
            self.q_network.parameters(), self.target_network.parameters()
        ):
            target_param.data.copy_(
                self.tau * param.data + (1 - self.tau) * target_param.data
            )

    def update_epsilon(self, progress_remaining: float):
        """Linear epsilon decay based on training progress."""
        self.epsilon = self.epsilon_end + (self.epsilon_start - self.epsilon_end) * progress_remaining
