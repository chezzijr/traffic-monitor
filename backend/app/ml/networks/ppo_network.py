"""PPO neural network and standalone agent for traffic light control."""

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.distributions import Categorical


class PPONetwork(nn.Module):
    """Actor-Critic network for PPO.

    Architecture:
        Input -> fc1(64) -> ReLU -> fc2(64) -> ReLU
        -> Policy head: Linear(64, num_actions) -> Softmax
        -> Value head: Linear(64, 1)
    """

    def __init__(self, ob_length: int, num_actions: int):
        super().__init__()
        self.fc1 = nn.Linear(ob_length, 64)
        self.fc2 = nn.Linear(64, 64)
        self.pi_head = nn.Linear(64, num_actions)
        self.vf_head = nn.Linear(64, 1)

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        x = torch.relu(self.fc1(x))
        x = torch.relu(self.fc2(x))
        action_probs = torch.softmax(self.pi_head(x), dim=-1)
        value = self.vf_head(x)
        return action_probs, value

    def get_distribution(self, obs: torch.Tensor) -> tuple[Categorical, torch.Tensor]:
        """Get action distribution and value estimate."""
        action_probs, value = self.forward(obs)
        dist = Categorical(action_probs)
        return dist, value


class PPOAgent:
    """Standalone PPO agent with clipped surrogate loss and GAE.

    Used for custom multi-agent training loop (not SB3).
    """

    def __init__(
        self,
        ob_length: int,
        num_actions: int,
        lr: float = 3e-4,
        gamma: float = 0.99,
        gae_lambda: float = 0.95,
        clip_range: float = 0.1,
        ent_coef: float = 0.001,
        vf_coef: float = 0.5,
        max_grad_norm: float = 0.5,
        n_epochs: int = 4,
        device: str = "cpu",
    ):
        self.gamma = gamma
        self.gae_lambda = gae_lambda
        self.clip_range = clip_range
        self.ent_coef = ent_coef
        self.vf_coef = vf_coef
        self.max_grad_norm = max_grad_norm
        self.n_epochs = n_epochs
        self.device = torch.device(device)

        self.network = PPONetwork(ob_length, num_actions).to(self.device)
        self.optimizer = optim.Adam(self.network.parameters(), lr=lr)

    def select_action(self, obs: np.ndarray) -> tuple[int, float, float]:
        """Select action and return (action, log_prob, value)."""
        with torch.no_grad():
            obs_tensor = torch.FloatTensor(obs).unsqueeze(0).to(self.device)
            dist, value = self.network.get_distribution(obs_tensor)
            action = dist.sample()
            log_prob = dist.log_prob(action)
        return int(action.item()), float(log_prob.item()), float(value.item())

    def evaluate(self, obs: torch.Tensor, actions: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """Evaluate actions: returns log_probs, values, entropy."""
        dist, values = self.network.get_distribution(obs)
        log_probs = dist.log_prob(actions)
        entropy = dist.entropy()
        return log_probs, values.squeeze(-1), entropy

    def compute_gae(
        self,
        rewards: list[float],
        values: list[float],
        dones: list[bool],
        last_value: float,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Compute GAE advantages and returns."""
        n = len(rewards)
        advantages = np.zeros(n, dtype=np.float32)
        last_gae = 0.0

        for t in reversed(range(n)):
            next_value = last_value if t == n - 1 else values[t + 1]
            next_non_terminal = 0.0 if dones[t] else 1.0
            delta = rewards[t] + self.gamma * next_value * next_non_terminal - values[t]
            last_gae = delta + self.gamma * self.gae_lambda * next_non_terminal * last_gae
            advantages[t] = last_gae

        returns = advantages + np.array(values, dtype=np.float32)
        return advantages, returns

    def update(self, rollout: dict[str, np.ndarray]) -> dict[str, float]:
        """PPO clipped surrogate update.

        Args:
            rollout: dict with 'obs', 'actions', 'old_log_probs', 'advantages', 'returns'

        Returns:
            Dict of loss components.
        """
        obs = torch.FloatTensor(rollout["obs"]).to(self.device)
        actions = torch.LongTensor(rollout["actions"]).to(self.device)
        old_log_probs = torch.FloatTensor(rollout["old_log_probs"]).to(self.device)
        advantages = torch.FloatTensor(rollout["advantages"]).to(self.device)
        returns = torch.FloatTensor(rollout["returns"]).to(self.device)

        # Normalize advantages
        advantages = (advantages - advantages.mean()) / (advantages.std() + 1e-8)

        total_policy_loss = 0.0
        total_value_loss = 0.0
        total_entropy_loss = 0.0

        for _ in range(self.n_epochs):
            log_probs, values, entropy = self.evaluate(obs, actions)

            # Clipped surrogate loss
            ratio = torch.exp(log_probs - old_log_probs)
            surr1 = ratio * advantages
            surr2 = torch.clamp(ratio, 1.0 - self.clip_range, 1.0 + self.clip_range) * advantages
            policy_loss = -torch.min(surr1, surr2).mean()

            # Value loss
            value_loss = nn.functional.mse_loss(values, returns)

            # Entropy bonus
            entropy_loss = -entropy.mean()

            # Total loss
            loss = policy_loss + self.vf_coef * value_loss + self.ent_coef * entropy_loss

            self.optimizer.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(self.network.parameters(), self.max_grad_norm)
            self.optimizer.step()

            total_policy_loss += policy_loss.item()
            total_value_loss += value_loss.item()
            total_entropy_loss += entropy_loss.item()

        return {
            "policy_loss": total_policy_loss / self.n_epochs,
            "value_loss": total_value_loss / self.n_epochs,
            "entropy_loss": total_entropy_loss / self.n_epochs,
        }
