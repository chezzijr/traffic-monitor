"""Custom DQN network architecture following LibSignal/DaRL specifications.

This module provides a 3-layer MLP network for Deep Q-Learning, designed
to work with traffic light optimization environments.
"""

import torch
import torch.nn as nn
import torch.nn.functional as F


class DQNNetwork(nn.Module):
    """3-layer MLP network for DQN following LibSignal specifications.

    Architecture:
        - Input layer: ob_length -> 20
        - Hidden layer: 20 -> 20
        - Output layer: 20 -> num_actions

    The network outputs Q-values for each action, representing the expected
    cumulative reward for taking that action in the given state.

    Attributes:
        fc1: First fully connected layer
        fc2: Second fully connected layer
        fc3: Output layer producing Q-values
    """

    def __init__(self, ob_length: int, num_actions: int, hidden_dim: int = 20) -> None:
        """Initialize the DQN network.

        Args:
            ob_length: Dimension of the observation/state space
            num_actions: Number of possible actions (output dimension)
            hidden_dim: Size of hidden layers (default: 20 per LibSignal spec)
        """
        super().__init__()

        self.ob_length = ob_length
        self.num_actions = num_actions
        self.hidden_dim = hidden_dim

        # 3-layer MLP architecture
        self.fc1 = nn.Linear(ob_length, hidden_dim)
        self.fc2 = nn.Linear(hidden_dim, hidden_dim)
        self.fc3 = nn.Linear(hidden_dim, num_actions)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """Forward pass through the network.

        Args:
            x: Input tensor of shape (batch_size, ob_length) or (ob_length,)

        Returns:
            Q-values tensor of shape (batch_size, num_actions) or (num_actions,)
        """
        x = F.relu(self.fc1(x))
        x = F.relu(self.fc2(x))
        return self.fc3(x)  # Q-values (no activation on output)

    def get_action(self, state: torch.Tensor) -> int:
        """Get the greedy action for a given state.

        Args:
            state: State tensor of shape (ob_length,) or (1, ob_length)

        Returns:
            Action index with the highest Q-value
        """
        with torch.no_grad():
            q_values = self.forward(state)
            return int(q_values.argmax(dim=-1).item())


class DQNAgent:
    """DQN agent with target network and training utilities.

    This agent implements the full DQN algorithm components:
    - Policy network for action selection
    - Target network for stable Q-value estimation
    - Epsilon-greedy exploration
    - RMSprop optimizer
    - MSE loss for Q-learning

    Attributes:
        policy_net: Network for selecting actions
        target_net: Network for computing target Q-values
        optimizer: RMSprop optimizer
        gamma: Discount factor for future rewards
        epsilon: Current exploration rate
        epsilon_min: Minimum exploration rate
        epsilon_decay: Rate of epsilon decay
    """

    def __init__(
        self,
        ob_length: int,
        num_actions: int,
        hidden_dim: int = 20,
        learning_rate: float = 0.001,
        gamma: float = 0.95,
        epsilon: float = 0.5,
        epsilon_min: float = 0.01,
        epsilon_decay: float = 0.9995,
        target_update_freq: int = 100,
        device: str | None = None,
    ) -> None:
        """Initialize the DQN agent.

        Args:
            ob_length: Dimension of the observation/state space
            num_actions: Number of possible actions
            hidden_dim: Size of hidden layers (default: 20)
            learning_rate: Learning rate for RMSprop optimizer
            gamma: Discount factor for future rewards
            epsilon: Initial exploration rate
            epsilon_min: Minimum exploration rate
            epsilon_decay: Decay multiplier for epsilon after each step
            target_update_freq: Steps between target network updates
            device: Device to use ('cuda', 'cpu', or None for auto)
        """
        self.ob_length = ob_length
        self.num_actions = num_actions
        self.gamma = gamma
        self.epsilon = epsilon
        self.epsilon_min = epsilon_min
        self.epsilon_decay = epsilon_decay
        self.target_update_freq = target_update_freq

        # Set device
        if device is None:
            self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        else:
            self.device = torch.device(device)

        # Policy and target networks
        self.policy_net = DQNNetwork(ob_length, num_actions, hidden_dim).to(self.device)
        self.target_net = DQNNetwork(ob_length, num_actions, hidden_dim).to(self.device)
        self.target_net.load_state_dict(self.policy_net.state_dict())
        self.target_net.eval()  # Target network is always in eval mode

        # RMSprop optimizer as per spec
        self.optimizer = torch.optim.RMSprop(
            self.policy_net.parameters(),
            lr=learning_rate,
        )

        # MSE loss for Q-learning
        self.loss_fn = nn.MSELoss()

        # Training step counter for target updates
        self._step_count = 0

    def select_action(self, state: torch.Tensor, training: bool = True) -> int:
        """Select an action using epsilon-greedy policy.

        Args:
            state: Current state tensor
            training: If True, use epsilon-greedy; if False, use greedy

        Returns:
            Selected action index
        """
        if training and torch.rand(1).item() < self.epsilon:
            # Random exploration
            return torch.randint(0, self.num_actions, (1,)).item()
        else:
            # Greedy action
            state = state.to(self.device)
            if state.dim() == 1:
                state = state.unsqueeze(0)
            return self.policy_net.get_action(state)

    def update_epsilon(self) -> None:
        """Decay epsilon according to the decay schedule."""
        self.epsilon = max(self.epsilon_min, self.epsilon * self.epsilon_decay)

    def update_target_network(self) -> None:
        """Copy policy network weights to target network."""
        self.target_net.load_state_dict(self.policy_net.state_dict())

    def train_step(
        self,
        states: torch.Tensor,
        actions: torch.Tensor,
        rewards: torch.Tensor,
        next_states: torch.Tensor,
        dones: torch.Tensor,
    ) -> float:
        """Perform a single training step.

        Args:
            states: Batch of states (batch_size, ob_length)
            actions: Batch of actions (batch_size,)
            rewards: Batch of rewards (batch_size,)
            next_states: Batch of next states (batch_size, ob_length)
            dones: Batch of done flags (batch_size,)

        Returns:
            Loss value for this training step
        """
        # Move tensors to device
        states = states.to(self.device)
        actions = actions.to(self.device).long()
        rewards = rewards.to(self.device)
        next_states = next_states.to(self.device)
        dones = dones.to(self.device)

        # Current Q-values for taken actions
        current_q = self.policy_net(states).gather(1, actions.unsqueeze(1)).squeeze(1)

        # Target Q-values using target network
        with torch.no_grad():
            next_q = self.target_net(next_states).max(dim=1)[0]
            target_q = rewards + self.gamma * next_q * (1 - dones.float())

        # MSE loss
        loss = self.loss_fn(current_q, target_q)

        # Optimize
        self.optimizer.zero_grad()
        loss.backward()
        self.optimizer.step()

        # Update step count and possibly update target network
        self._step_count += 1
        if self._step_count % self.target_update_freq == 0:
            self.update_target_network()

        return loss.item()

    def save(self, path: str) -> None:
        """Save the agent's state to a file.

        Args:
            path: File path to save the state
        """
        torch.save(
            {
                "policy_net_state_dict": self.policy_net.state_dict(),
                "target_net_state_dict": self.target_net.state_dict(),
                "optimizer_state_dict": self.optimizer.state_dict(),
                "epsilon": self.epsilon,
                "step_count": self._step_count,
                "ob_length": self.ob_length,
                "num_actions": self.num_actions,
            },
            path,
        )

    def load(self, path: str) -> None:
        """Load the agent's state from a file.

        Args:
            path: File path to load the state from
        """
        checkpoint = torch.load(path, map_location=self.device)
        self.policy_net.load_state_dict(checkpoint["policy_net_state_dict"])
        self.target_net.load_state_dict(checkpoint["target_net_state_dict"])
        self.optimizer.load_state_dict(checkpoint["optimizer_state_dict"])
        self.epsilon = checkpoint["epsilon"]
        self._step_count = checkpoint["step_count"]
