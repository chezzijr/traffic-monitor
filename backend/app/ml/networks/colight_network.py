"""CoLight (Cooperative Light) neural network and agent for multi-agent traffic light optimization.

Ported from LibSignal's implementation using pure PyTorch (no torch-geometric).
Uses dense adjacency matrices since graphs are tiny (max 10 nodes).
"""

import copy
import logging
import random
from collections import OrderedDict, deque

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from torch.nn.utils import clip_grad_norm_
from torch.nn.utils.rnn import pad_sequence

logger = logging.getLogger(__name__)


class EmbeddingMLP(nn.Module):
    """MLP for embedding raw observations into a latent space.

    Architecture: in_size -> Linear(layer_dims[0]) -> ReLU -> ... -> Linear(layer_dims[-1]) -> ReLU
    """

    def __init__(self, in_size: int, layer_dims: list[int] | None = None):
        super().__init__()
        if layer_dims is None:
            layer_dims = [128, 128]

        constructor_dict = OrderedDict()
        for l_idx, l_size in enumerate(layer_dims):
            name = f"node_embedding_{l_idx}"
            if l_idx == 0:
                h = nn.Linear(in_size, l_size)
            else:
                h = nn.Linear(layer_dims[l_idx - 1], l_size)
            constructor_dict[name] = h
            constructor_dict[f"n_relu_{l_idx}"] = nn.ReLU()

        self.embedding_node = nn.Sequential(constructor_dict)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """Forward pass.

        Args:
            x: Input tensor of shape [N, in_size].

        Returns:
            Embedded tensor of shape [N, layer_dims[-1]].
        """
        return self.embedding_node(x)


class MultiHeadGraphAttention(nn.Module):
    """Dense graph attention replacing PyG's MessagePassing.

    Same math as LibSignal's MultiHeadAttModel, but uses dense adjacency
    matrices with masked softmax instead of sparse scatter operations.

    Args:
        d: Input feature dimension.
        dv: Dimension per attention head.
        d_out: Output dimension.
        nv: Number of attention heads.
    """

    def __init__(self, d: int, dv: int, d_out: int, nv: int):
        super().__init__()
        self.d = d
        self.dv = dv
        self.d_out = d_out
        self.nv = nv

        self.W_target = nn.Linear(d, dv * nv)
        self.W_source = nn.Linear(d, dv * nv)
        self.hidden_embedding = nn.Linear(d, dv * nv)
        self.out = nn.Linear(dv, d_out)

    def forward(self, x: torch.Tensor, adj: torch.Tensor) -> torch.Tensor:
        """Forward pass with dense graph attention.

        Args:
            x: Node features of shape [N, d].
            adj: Binary adjacency matrix of shape [N, N] (with self-loops).

        Returns:
            Output tensor of shape [N, d_out].
        """
        N = x.size(0)

        # 1. Compute target representations: [N, dv*nv] -> [N, nv, dv] -> [nv, N, dv]
        h_target = F.relu(self.W_target(x))
        h_target = h_target.view(N, self.nv, self.dv).permute(1, 0, 2)

        # 2. Compute source representations: [N, dv*nv] -> [N, nv, dv] -> [nv, N, dv]
        h_source = F.relu(self.W_source(x))
        h_source = h_source.view(N, self.nv, self.dv).permute(1, 0, 2)

        # 3. Attention scores via element-wise multiply: [nv, N, N]
        #    e[h, i, j] = sum_d(h_target[h, i, d] * h_source[h, j, d])
        e = torch.einsum("hid,hjd->hij", h_target, h_source)

        # 4. Mask out non-adjacent pairs with -inf
        adj_expanded = adj.unsqueeze(0).expand(self.nv, -1, -1)  # [nv, N, N]
        e = e.masked_fill(adj_expanded == 0, float("-inf"))

        # 5. Stable softmax along source dimension (j)
        alpha = F.softmax(e, dim=-1)  # [nv, N, N]

        # 6. Hidden neighbor features: [N, dv*nv] -> [N, nv, dv] -> [nv, N, dv]
        h_hidden = F.relu(self.hidden_embedding(x))
        h_hidden = h_hidden.view(N, self.nv, self.dv).permute(1, 0, 2)

        # 7. Aggregate: alpha @ h_hidden -> [nv, N, dv]
        out_h = torch.bmm(alpha, h_hidden)

        # 8. Mean across heads: [N, dv]
        out = out_h.mean(0)

        # 9. Output projection with ReLU: [N, d_out]
        out = F.relu(self.out(out))

        return out


class ColightNet(nn.Module):
    """Full CoLight network combining embedding, graph attention layers, and output.

    Args:
        ob_length: Observation dimension per intersection.
        num_actions: Maximum number of actions (padded).
        phase_lengths: List of number of valid phases per intersection.
        n_layers: Number of graph attention layers.
        node_emb_dim: Layer dimensions for the embedding MLP.
        input_dim: Input dimensions for each attention layer.
        output_dim: Output dimensions for each attention layer.
        num_heads: Number of attention heads per layer.
        dims_per_head: Dimension per head per layer.
    """

    def __init__(
        self,
        ob_length: int,
        num_actions: int,
        phase_lengths: list[int],
        n_layers: int = 1,
        node_emb_dim: list[int] | None = None,
        input_dim: list[int] | None = None,
        output_dim: list[int] | None = None,
        num_heads: list[int] | None = None,
        dims_per_head: list[int] | None = None,
    ):
        super().__init__()
        if node_emb_dim is None:
            node_emb_dim = [128, 128]
        if input_dim is None:
            input_dim = [128, 128]
        if output_dim is None:
            output_dim = [128, 128]
        if num_heads is None:
            num_heads = [5, 5]
        if dims_per_head is None:
            dims_per_head = [16, 16]

        self.embedding = EmbeddingMLP(ob_length, node_emb_dim)

        self.attention_layers = nn.ModuleList()
        for i in range(n_layers):
            self.attention_layers.append(
                MultiHeadGraphAttention(
                    d=input_dim[i],
                    dv=dims_per_head[i],
                    d_out=output_dim[i],
                    nv=num_heads[i],
                )
            )

        final_dim = output_dim[-1] if n_layers > 0 else node_emb_dim[-1]
        self.output = nn.Linear(final_dim, num_actions)

        # Build phase mask: [num_intersections, num_actions] boolean buffer
        unpadded_masks = [torch.ones(length, dtype=torch.bool) for length in phase_lengths]
        phase_mask = pad_sequence(unpadded_masks, batch_first=True, padding_value=0)
        # Pad to num_actions if needed (phase_mask width may be < num_actions)
        if phase_mask.size(1) < num_actions:
            padding = torch.zeros(
                phase_mask.size(0), num_actions - phase_mask.size(1), dtype=torch.bool
            )
            phase_mask = torch.cat([phase_mask, padding], dim=1)
        self.register_buffer("phase_mask", phase_mask.float())

    def forward(self, x: torch.Tensor, adj: torch.Tensor) -> torch.Tensor:
        """Forward pass.

        Args:
            x: Observations of shape [N, ob_length].
            adj: Dense adjacency matrix of shape [N, N] with self-loops.

        Returns:
            Q-values of shape [N, num_actions] with invalid actions masked to zero.
        """
        h = self.embedding(x)

        for layer in self.attention_layers:
            h = layer(h, adj)

        h = self.output(h)

        # Apply phase mask: zero out invalid action Q-values
        h = h * self.phase_mask

        return h


class CoLightAgent:
    """DQN-style multi-agent CoLight with replay buffer, epsilon-greedy, and target network.

    Follows the same interface pattern as DQNAgent but operates on graph-structured
    multi-intersection observations.
    """

    def __init__(
        self,
        ob_length: int,
        num_actions: int,
        num_intersections: int,
        phase_lengths: list[int],
        edge_index: np.ndarray,
        lr: float = 1e-3,
        gamma: float = 0.95,
        epsilon_start: float = 0.8,
        epsilon_min: float = 0.01,
        epsilon_decay: float = 0.9995,
        grad_clip: float = 5.0,
        buffer_size: int = 5000,
        batch_size: int = 64,
        device: str = "cpu",
        n_layers: int = 1,
        node_emb_dim: list[int] | None = None,
        num_heads: list[int] | None = None,
        dims_per_head: list[int] | None = None,
    ):
        if node_emb_dim is None:
            node_emb_dim = [128, 128]
        if num_heads is None:
            num_heads = [5, 5]
        if dims_per_head is None:
            dims_per_head = [16, 16]

        self.ob_length = ob_length
        self.num_actions = num_actions
        self.num_intersections = num_intersections
        self.phase_lengths = phase_lengths
        self.gamma = gamma
        self.epsilon = epsilon_start
        self.epsilon_start = epsilon_start
        self.epsilon_min = epsilon_min
        self.epsilon_decay = epsilon_decay
        self.grad_clip = grad_clip
        self.batch_size = batch_size
        self.device = torch.device(device)

        # Build dense adjacency matrix from sparse edge_index [2, E] with self-loops
        adj = torch.zeros(num_intersections, num_intersections, dtype=torch.float32)
        if edge_index is not None and edge_index.size > 0:
            src = edge_index[0]
            dst = edge_index[1]
            for s, d in zip(src, dst):
                adj[s, d] = 1.0
        # Add self-loops
        for i in range(num_intersections):
            adj[i, i] = 1.0
        self.adj_matrix = adj.to(self.device)

        # Use node_emb_dim for both embedding and attention layer input/output dims
        input_dim = node_emb_dim[:n_layers]
        output_dim = node_emb_dim[:n_layers]

        self.q_network = ColightNet(
            ob_length=ob_length,
            num_actions=num_actions,
            phase_lengths=phase_lengths,
            n_layers=n_layers,
            node_emb_dim=node_emb_dim,
            input_dim=input_dim,
            output_dim=output_dim,
            num_heads=num_heads[:n_layers],
            dims_per_head=dims_per_head[:n_layers],
        ).to(self.device)

        self.target_network = copy.deepcopy(self.q_network).to(self.device)
        self.target_network.eval()

        self.optimizer = optim.RMSprop(
            self.q_network.parameters(), lr=lr, alpha=0.9, centered=False, eps=1e-7
        )
        self.loss_fn = nn.MSELoss(reduction="mean")

        self.replay_buffer: deque[tuple] = deque(maxlen=buffer_size)

        logger.info(
            "CoLightAgent initialized: %d intersections, ob_length=%d, num_actions=%d, "
            "n_layers=%d, device=%s",
            num_intersections,
            ob_length,
            num_actions,
            n_layers,
            self.device,
        )

    def select_action(self, obs: np.ndarray, deterministic: bool = False) -> np.ndarray:
        """Epsilon-greedy action selection for all intersections.

        Args:
            obs: Observations of shape [num_intersections, ob_length].
            deterministic: If True, always pick greedy action.

        Returns:
            Array of actions of shape [num_intersections], each clipped to valid phase range.
        """
        if not deterministic and random.random() < self.epsilon:
            # Random actions clipped to valid phase lengths
            actions = np.array(
                [np.random.randint(self.phase_lengths[i]) for i in range(self.num_intersections)],
                dtype=np.int64,
            )
            return actions

        with torch.no_grad():
            obs_tensor = torch.FloatTensor(obs).to(self.device)  # [N, ob_length]
            q_values = self.q_network(obs_tensor, self.adj_matrix)  # [N, num_actions]
            actions = np.zeros(self.num_intersections, dtype=np.int64)
            for i in range(self.num_intersections):
                # Only consider valid phases for this intersection
                valid_q = q_values[i, : self.phase_lengths[i]]
                actions[i] = int(valid_q.argmax().item())
            return actions

    def remember(
        self,
        obs: np.ndarray,
        actions: np.ndarray,
        rewards: np.ndarray,
        next_obs: np.ndarray,
        done: float,
    ) -> None:
        """Store a transition in the replay buffer.

        Args:
            obs: Observations [num_intersections, ob_length].
            actions: Actions [num_intersections].
            rewards: Rewards [num_intersections].
            next_obs: Next observations [num_intersections, ob_length].
            done: Terminal flag (0.0 or 1.0).
        """
        self.replay_buffer.append((obs, actions, rewards, next_obs, done))

    def can_train(self) -> bool:
        """Check if enough samples in buffer for training."""
        return len(self.replay_buffer) >= self.batch_size

    def sample_batch(self) -> list:
        """Sample a random batch from the replay buffer."""
        return random.sample(self.replay_buffer, self.batch_size)

    def update(self, samples: list) -> float:
        """Perform a gradient update from a batch of transitions.

        Each sample is a tuple (obs, actions, rewards, next_obs, done) where:
            obs, next_obs: [N, ob_length], actions, rewards: [N], done: float.

        Since N is tiny (max 10), we loop over the batch and stack results.

        Args:
            samples: List of transition tuples.

        Returns:
            Loss value (float).
        """
        all_current_q = []
        all_target_q = []

        for obs, actions, rewards, next_obs, done in samples:
            obs_t = torch.FloatTensor(obs).to(self.device)  # [N, ob_length]
            next_obs_t = torch.FloatTensor(next_obs).to(self.device)  # [N, ob_length]
            actions_t = torch.LongTensor(actions).to(self.device)  # [N]
            rewards_t = torch.FloatTensor(rewards).to(self.device)  # [N]

            # Current Q-values for taken actions
            current_q = self.q_network(obs_t, self.adj_matrix)  # [N, num_actions]
            current_q_selected = current_q.gather(
                1, actions_t.unsqueeze(1)
            ).squeeze(1)  # [N]

            # Target Q-values
            with torch.no_grad():
                target_q = self.target_network(next_obs_t, self.adj_matrix)  # [N, num_actions]
                # Mask invalid actions before taking max
                max_next_q = torch.zeros(self.num_intersections, device=self.device)
                for i in range(self.num_intersections):
                    valid_q = target_q[i, : self.phase_lengths[i]]
                    max_next_q[i] = valid_q.max()
                target_value = rewards_t + self.gamma * max_next_q * (1.0 - done)

            all_current_q.append(current_q_selected)
            all_target_q.append(target_value)

        # Stack all into flat tensors and compute loss
        all_current_q_flat = torch.cat(all_current_q)  # [B * N]
        all_target_q_flat = torch.cat(all_target_q).detach()  # [B * N]

        loss = self.loss_fn(all_current_q_flat, all_target_q_flat)

        self.optimizer.zero_grad()
        loss.backward()
        clip_grad_norm_(self.q_network.parameters(), self.grad_clip)
        self.optimizer.step()

        loss_val = loss.item()
        logger.debug("CoLight update loss: %.6f", loss_val)
        return loss_val

    def update_target_network(self) -> None:
        """Hard copy of weights to target network."""
        self.target_network.load_state_dict(self.q_network.state_dict())
        logger.debug("Target network updated (hard copy)")

    def decay_epsilon(self) -> None:
        """Multiplicative epsilon decay."""
        if self.epsilon > self.epsilon_min:
            self.epsilon *= self.epsilon_decay
        logger.debug("Epsilon decayed to %.6f", self.epsilon)
