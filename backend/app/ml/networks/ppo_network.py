"""Custom PPO network architecture with Actor-Critic design.

This module provides a PPO (Proximal Policy Optimization) network with shared
backbone and separate policy/value heads, designed for traffic light optimization.
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.distributions import Categorical


class PPONetwork(nn.Module):
    """Actor-Critic network for PPO with shared backbone.

    Architecture:
        - Shared backbone: 2-layer MLP (input -> 64 -> 64)
        - Policy head: 64 -> num_actions (outputs action probabilities)
        - Value head: 64 -> 1 (outputs state value)

    The network outputs both action probabilities and state values,
    enabling actor-critic style training with PPO.

    Attributes:
        fc1: First shared fully connected layer
        fc2: Second shared fully connected layer
        policy: Policy head outputting action logits
        value: Value head outputting state value
    """

    def __init__(self, ob_length: int, num_actions: int, hidden_dim: int = 64) -> None:
        """Initialize the PPO network.

        Args:
            ob_length: Dimension of the observation/state space
            num_actions: Number of possible actions (output dimension)
            hidden_dim: Size of hidden layers (default: 64)
        """
        super().__init__()

        self.ob_length = ob_length
        self.num_actions = num_actions
        self.hidden_dim = hidden_dim

        # Shared 2-layer backbone
        self.fc1 = nn.Linear(ob_length, hidden_dim)
        self.fc2 = nn.Linear(hidden_dim, hidden_dim)

        # Policy head (actor)
        self.policy = nn.Linear(hidden_dim, num_actions)

        # Value head (critic)
        self.value = nn.Linear(hidden_dim, 1)

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        """Forward pass through the network.

        Args:
            x: Input tensor of shape (batch_size, ob_length) or (ob_length,)

        Returns:
            Tuple of (policy, value):
                - policy: Action probabilities of shape (batch_size, num_actions)
                - value: State value of shape (batch_size, 1)
        """
        # Shared backbone
        x = F.relu(self.fc1(x))
        x = F.relu(self.fc2(x))

        # Policy head with softmax for probabilities
        policy = F.softmax(self.policy(x), dim=-1)

        # Value head (no activation)
        value = self.value(x)

        return policy, value

    def get_action_and_value(
        self, state: torch.Tensor, action: torch.Tensor | None = None
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        """Get action, log probability, entropy, and value for a state.

        This method is useful during training for computing the PPO loss.

        Args:
            state: State tensor of shape (batch_size, ob_length) or (ob_length,)
            action: Optional action tensor. If None, sample from policy.

        Returns:
            Tuple of (action, log_prob, entropy, value):
                - action: Selected action(s)
                - log_prob: Log probability of the action
                - entropy: Policy entropy for exploration bonus
                - value: State value estimate
        """
        policy, value = self.forward(state)
        dist = Categorical(policy)

        if action is None:
            action = dist.sample()

        log_prob = dist.log_prob(action)
        entropy = dist.entropy()

        return action, log_prob, entropy, value


class PPOAgent:
    """PPO agent with training utilities and GAE computation.

    This agent implements the PPO algorithm components:
    - Actor-Critic network for policy and value estimation
    - Generalized Advantage Estimation (GAE)
    - PPO clipped surrogate loss
    - Value function loss
    - Entropy bonus for exploration

    PPO Hyperparameters (per specification):
        - Clip epsilon: 0.1
        - Update interval: 360 steps
        - Minibatch size: 360
        - Training epochs: 4
        - Entropy coefficient: 0.001

    Attributes:
        network: PPO Actor-Critic network
        optimizer: Adam optimizer
        gamma: Discount factor for future rewards
        gae_lambda: Lambda for GAE computation
        clip_epsilon: PPO clipping parameter
        entropy_coef: Entropy bonus coefficient
        value_coef: Value loss coefficient
        update_interval: Steps between updates
        minibatch_size: Size of training minibatches
        epochs: Number of epochs per update
    """

    def __init__(
        self,
        ob_length: int,
        num_actions: int,
        hidden_dim: int = 64,
        learning_rate: float = 0.0003,
        gamma: float = 0.99,
        gae_lambda: float = 0.95,
        clip_epsilon: float = 0.1,
        entropy_coef: float = 0.001,
        value_coef: float = 0.5,
        update_interval: int = 360,
        minibatch_size: int = 360,
        epochs: int = 4,
        device: str | None = None,
    ) -> None:
        """Initialize the PPO agent.

        Args:
            ob_length: Dimension of the observation/state space
            num_actions: Number of possible actions
            hidden_dim: Size of hidden layers (default: 64)
            learning_rate: Learning rate for Adam optimizer
            gamma: Discount factor for future rewards
            gae_lambda: Lambda for GAE computation
            clip_epsilon: PPO clipping parameter
            entropy_coef: Coefficient for entropy bonus
            value_coef: Coefficient for value loss
            update_interval: Steps between policy updates
            minibatch_size: Size of minibatches for training
            epochs: Number of training epochs per update
            device: Device to use ('cuda', 'cpu', or None for auto)
        """
        self.ob_length = ob_length
        self.num_actions = num_actions
        self.gamma = gamma
        self.gae_lambda = gae_lambda
        self.clip_epsilon = clip_epsilon
        self.entropy_coef = entropy_coef
        self.value_coef = value_coef
        self.update_interval = update_interval
        self.minibatch_size = minibatch_size
        self.epochs = epochs

        # Set device
        if device is None:
            self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        else:
            self.device = torch.device(device)

        # Actor-Critic network
        self.network = PPONetwork(ob_length, num_actions, hidden_dim).to(self.device)

        # Adam optimizer
        self.optimizer = torch.optim.Adam(
            self.network.parameters(),
            lr=learning_rate,
        )

        # Rollout buffers
        self._reset_buffers()

        # Step counter
        self._step_count = 0

    def _reset_buffers(self) -> None:
        """Reset rollout buffers."""
        self.states: list[torch.Tensor] = []
        self.actions: list[torch.Tensor] = []
        self.log_probs: list[torch.Tensor] = []
        self.rewards: list[float] = []
        self.values: list[torch.Tensor] = []
        self.dones: list[bool] = []

    def select_action(self, state: torch.Tensor, training: bool = True) -> int:
        """Select an action using the current policy.

        Args:
            state: Current state tensor
            training: If True, store transition in buffer

        Returns:
            Selected action index
        """
        state = state.to(self.device)
        if state.dim() == 1:
            state = state.unsqueeze(0)

        with torch.no_grad():
            action, log_prob, _, value = self.network.get_action_and_value(state)

        if training:
            self.states.append(state)
            self.actions.append(action)
            self.log_probs.append(log_prob)
            self.values.append(value)

        return int(action.item())

    def store_transition(self, reward: float, done: bool) -> None:
        """Store reward and done flag for the last action.

        Args:
            reward: Reward received after taking the action
            done: Whether the episode ended
        """
        self.rewards.append(reward)
        self.dones.append(done)
        self._step_count += 1

    def should_update(self) -> bool:
        """Check if it's time to update the policy.

        Returns:
            True if update_interval steps have been collected
        """
        return len(self.rewards) >= self.update_interval

    def compute_gae(
        self,
        rewards: torch.Tensor,
        values: torch.Tensor,
        dones: torch.Tensor,
        next_value: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """Compute Generalized Advantage Estimation.

        Args:
            rewards: Tensor of rewards (T,)
            values: Tensor of value estimates (T,)
            dones: Tensor of done flags (T,)
            next_value: Value estimate for the state after last transition

        Returns:
            Tuple of (advantages, returns):
                - advantages: GAE advantage estimates
                - returns: Discounted returns for value targets
        """
        T = len(rewards)
        advantages = torch.zeros(T, device=self.device)
        last_gae = 0.0

        for t in reversed(range(T)):
            if t == T - 1:
                next_non_terminal = 1.0 - dones[t].float()
                next_val = next_value
            else:
                next_non_terminal = 1.0 - dones[t].float()
                next_val = values[t + 1]

            delta = rewards[t] + self.gamma * next_val * next_non_terminal - values[t]
            advantages[t] = last_gae = (
                delta + self.gamma * self.gae_lambda * next_non_terminal * last_gae
            )

        returns = advantages + values
        return advantages, returns

    def update(self) -> dict[str, float]:
        """Perform PPO policy update.

        Returns:
            Dictionary with loss metrics:
                - policy_loss: Policy gradient loss
                - value_loss: Value function loss
                - entropy_loss: Entropy bonus (negative)
                - total_loss: Combined loss
        """
        if len(self.rewards) == 0:
            return {}

        # Convert buffers to tensors
        states = torch.cat(self.states, dim=0)
        actions = torch.cat(self.actions, dim=0)
        old_log_probs = torch.cat(self.log_probs, dim=0)
        old_values = torch.cat(self.values, dim=0).squeeze(-1)
        rewards = torch.tensor(self.rewards, dtype=torch.float32, device=self.device)
        dones = torch.tensor(self.dones, dtype=torch.bool, device=self.device)

        # Compute next value for GAE
        with torch.no_grad():
            if len(self.states) > 0:
                last_state = self.states[-1]
                _, next_value = self.network(last_state)
                next_value = next_value.squeeze()
            else:
                next_value = torch.tensor(0.0, device=self.device)

        # Compute GAE
        advantages, returns = self.compute_gae(rewards, old_values, dones, next_value)

        # Normalize advantages
        advantages = (advantages - advantages.mean()) / (advantages.std() + 1e-8)

        # Training metrics
        total_policy_loss = 0.0
        total_value_loss = 0.0
        total_entropy_loss = 0.0
        num_updates = 0

        # PPO epochs
        batch_size = len(rewards)
        indices = torch.randperm(batch_size, device=self.device)

        for _ in range(self.epochs):
            # Process in minibatches
            for start in range(0, batch_size, self.minibatch_size):
                end = min(start + self.minibatch_size, batch_size)
                mb_indices = indices[start:end]

                mb_states = states[mb_indices]
                mb_actions = actions[mb_indices]
                mb_old_log_probs = old_log_probs[mb_indices]
                mb_advantages = advantages[mb_indices]
                mb_returns = returns[mb_indices]

                # Get current policy outputs
                _, new_log_probs, entropy, new_values = self.network.get_action_and_value(
                    mb_states, mb_actions
                )
                new_values = new_values.squeeze(-1)

                # Policy loss with clipping
                ratio = torch.exp(new_log_probs - mb_old_log_probs)
                surr1 = ratio * mb_advantages
                surr2 = torch.clamp(ratio, 1 - self.clip_epsilon, 1 + self.clip_epsilon) * mb_advantages
                policy_loss = -torch.min(surr1, surr2).mean()

                # Value loss
                value_loss = F.mse_loss(new_values, mb_returns)

                # Entropy bonus (negative for minimization)
                entropy_loss = -entropy.mean()

                # Total loss
                loss = (
                    policy_loss
                    + self.value_coef * value_loss
                    + self.entropy_coef * entropy_loss
                )

                # Optimize
                self.optimizer.zero_grad()
                loss.backward()
                # Gradient clipping for stability
                torch.nn.utils.clip_grad_norm_(self.network.parameters(), max_norm=0.5)
                self.optimizer.step()

                # Accumulate metrics
                total_policy_loss += policy_loss.item()
                total_value_loss += value_loss.item()
                total_entropy_loss += entropy_loss.item()
                num_updates += 1

        # Reset buffers
        self._reset_buffers()

        # Return average metrics
        return {
            "policy_loss": total_policy_loss / num_updates,
            "value_loss": total_value_loss / num_updates,
            "entropy_loss": total_entropy_loss / num_updates,
            "total_loss": (total_policy_loss + total_value_loss + total_entropy_loss) / num_updates,
        }

    def save(self, path: str) -> None:
        """Save the agent's state to a file.

        Args:
            path: File path to save the state
        """
        torch.save(
            {
                "network_state_dict": self.network.state_dict(),
                "optimizer_state_dict": self.optimizer.state_dict(),
                "step_count": self._step_count,
                "ob_length": self.ob_length,
                "num_actions": self.num_actions,
                "gamma": self.gamma,
                "gae_lambda": self.gae_lambda,
                "clip_epsilon": self.clip_epsilon,
                "entropy_coef": self.entropy_coef,
                "value_coef": self.value_coef,
            },
            path,
        )

    def load(self, path: str) -> None:
        """Load the agent's state from a file.

        Args:
            path: File path to load the state from
        """
        checkpoint = torch.load(path, map_location=self.device)
        self.network.load_state_dict(checkpoint["network_state_dict"])
        self.optimizer.load_state_dict(checkpoint["optimizer_state_dict"])
        self._step_count = checkpoint["step_count"]
