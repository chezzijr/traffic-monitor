"""Minimal RL model loader/inference for digital twin deploy loop.

Supports:
  - DQN (single-agent)
  - PPO (single-agent)
  - CoLight (multi-agent, graph-based)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.nn.utils.rnn import pad_sequence
from collections import OrderedDict

logger = logging.getLogger(__name__)


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


# ── CoLight network components (inference-only) ─────────────────────


class EmbeddingMLP(nn.Module):
    """MLP for embedding raw observations into a latent space."""

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
        return self.embedding_node(x)


class MultiHeadGraphAttention(nn.Module):
    """Dense graph attention for CoLight."""

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
        N = x.size(0)
        h_target = F.relu(self.W_target(x)).view(N, self.nv, self.dv).permute(1, 0, 2)
        h_source = F.relu(self.W_source(x)).view(N, self.nv, self.dv).permute(1, 0, 2)
        e = torch.einsum("hid,hjd->hij", h_target, h_source)
        adj_expanded = adj.unsqueeze(0).expand(self.nv, -1, -1)
        e = e.masked_fill(adj_expanded == 0, -1e9)
        alpha = F.softmax(e, dim=-1)
        h_hidden = F.relu(self.hidden_embedding(x)).view(N, self.nv, self.dv).permute(1, 0, 2)
        out_h = torch.bmm(alpha, h_hidden)
        out = out_h.mean(0)
        out = F.relu(self.out(out))
        return out


class ColightNet(nn.Module):
    """Full CoLight network for multi-agent traffic light control."""

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
        if phase_mask.size(1) < num_actions:
            padding = torch.zeros(
                phase_mask.size(0), num_actions - phase_mask.size(1), dtype=torch.bool
            )
            phase_mask = torch.cat([phase_mask, padding], dim=1)
        self.register_buffer("phase_mask", phase_mask.float())

    def forward(self, x: torch.Tensor, adj: torch.Tensor) -> torch.Tensor:
        h = self.embedding(x)
        for layer in self.attention_layers:
            h = layer(h, adj)
        h = self.output(h)
        h = h * self.phase_mask
        return h


# ── Unified model wrapper ───────────────────────────────────────────


class RLModel:
    """Load and run inference for DQN/PPO/CoLight .pt checkpoints."""

    def __init__(self) -> None:
        self.model: nn.Module | None = None
        self.algorithm: str | None = None
        self.ob_length: int = 0
        self.num_actions: int = 0
        self.device = torch.device("cpu")
        self.model_path: str | None = None

        # Multi-agent fields (CoLight)
        self.is_multi_agent: bool = False
        self.num_intersections: int = 1
        self.phase_lengths: list[int] = []
        self.adj_matrix: torch.Tensor | None = None
        self.tl_ids: list[str] = []

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

        if algorithm == "colight":
            # Multi-agent CoLight model
            num_intersections = int(checkpoint["num_intersections"])
            phase_lengths = checkpoint["phase_lengths"]
            edge_index = checkpoint.get("edge_index")
            network_params = checkpoint.get("network_params", {})

            # Build adjacency matrix
            adj = torch.zeros(num_intersections, num_intersections, dtype=torch.float32)
            if edge_index is not None and edge_index.size > 0:
                src = edge_index[0]
                dst = edge_index[1]
                for s, d in zip(src, dst):
                    adj[int(s), int(d)] = 1.0
            for i in range(num_intersections):
                adj[i, i] = 1.0

            model = ColightNet(
                ob_length=ob_length,
                num_actions=num_actions,
                phase_lengths=phase_lengths,
                **network_params,
            )
            model.load_state_dict(checkpoint["model_state"])
            model.eval()

            self.is_multi_agent = True
            self.num_intersections = num_intersections
            self.phase_lengths = phase_lengths
            self.adj_matrix = adj
            self.tl_ids = checkpoint.get("tl_ids", [])

            logger.info(
                "Loaded CoLight multi-agent model: %d intersections, ob=%d, actions=%d",
                num_intersections, ob_length, num_actions,
            )

        elif algorithm == "dqn":
            model = DQNNetwork(ob_length, num_actions)
            model.load_state_dict(checkpoint["model_state"])
            model.eval()
            self.is_multi_agent = False
            self.tl_ids = []
            if checkpoint.get("tl_id"):
                self.tl_ids = [checkpoint["tl_id"]]

        elif algorithm == "ppo":
            model = PPONetwork(ob_length, num_actions)
            model.load_state_dict(checkpoint["model_state"])
            model.eval()
            self.is_multi_agent = False
            self.tl_ids = []
            if checkpoint.get("tl_id"):
                self.tl_ids = [checkpoint["tl_id"]]

        else:
            raise ValueError(f"Unsupported algorithm for deploy: {algorithm}")

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
            "is_multi_agent": self.is_multi_agent,
            "num_intersections": self.num_intersections,
            "tl_ids": self.tl_ids,
        }

    def predict(self, observation: list[float] | np.ndarray) -> int:
        """Single-agent prediction. Returns action index."""
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

    def predict_multi(self, observations: np.ndarray) -> np.ndarray:
        """Multi-agent prediction (CoLight). Returns array of actions per intersection.

        Args:
            observations: shape [num_intersections, ob_length]

        Returns:
            actions: shape [num_intersections]
        """
        if self.model is None:
            raise RuntimeError("No model loaded")
        if not self.is_multi_agent:
            raise RuntimeError("predict_multi called on single-agent model")

        if not isinstance(observations, np.ndarray):
            observations = np.array(observations, dtype=np.float32)

        # Ensure correct shape
        if observations.ndim == 1:
            observations = observations.reshape(self.num_intersections, -1)

        obs_tensor = torch.FloatTensor(observations)

        with torch.no_grad():
            q_values = self.model(obs_tensor, self.adj_matrix)  # [N, num_actions]
            actions = np.zeros(self.num_intersections, dtype=np.int64)
            for i in range(self.num_intersections):
                valid_q = q_values[i, : self.phase_lengths[i]]
                actions[i] = int(valid_q.argmax().item())

        return actions
