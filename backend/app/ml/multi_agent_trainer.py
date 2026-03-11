"""Multi-agent trainer for N traffic lights sharing one SUMO instance."""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import torch
from stable_baselines3 import DQN, PPO
from stable_baselines3.common.buffers import ReplayBuffer

from app.ml.multi_agent_env import MultiAgentTrafficLightEnv, SingleAgentEnvAdapter
from app.ml.trainer import Algorithm

logger = logging.getLogger(__name__)

MAX_JUNCTIONS = 10


class MultiAgentCallback(Protocol):
    """Protocol for multi-agent training callbacks."""

    def on_step(self, step: int, total_steps: int, infos: dict[str, dict]) -> bool:
        """Called after each step. Return False to stop training."""
        ...

    def on_episode_end(self, episode: int, infos: dict[str, dict]) -> None:
        """Called at episode end."""
        ...


@dataclass
class MultiAgentMetrics:
    """Aggregated metrics from multi-agent training."""

    total_episodes: int = 0
    episode_rewards: dict[str, list[float]] = field(default_factory=dict)
    mean_reward: float = 0.0
    avg_waiting_time: float = 0.0
    avg_queue_length: float = 0.0
    throughput: int = 0


class MultiAgentTrainer:
    """Trains N independent RL agents sharing one SUMO simulation.

    Creates one SB3 model per junction via SingleAgentEnvAdapter.
    Uses custom collect-train loop (cannot use SB3's .learn()).
    Maximum 10 junctions per task.
    """

    DEFAULT_DQN_PARAMS: dict[str, Any] = {
        "learning_rate": 1e-3,
        "buffer_size": 100_000,
        "learning_starts": 1000,
        "batch_size": 64,
        "tau": 0.005,
        "gamma": 0.95,
        "train_freq": 4,
        "target_update_interval": 100,
        "exploration_fraction": 0.1,
        "exploration_initial_eps": 0.5,
        "exploration_final_eps": 0.01,
        "policy_kwargs": {"net_arch": [20, 20]},
    }

    DEFAULT_PPO_PARAMS: dict[str, Any] = {
        "learning_rate": 3e-4,
        "n_steps": 360,
        "batch_size": 360,
        "n_epochs": 4,
        "gamma": 0.99,
        "gae_lambda": 0.95,
        "clip_range": 0.1,
        "ent_coef": 0.001,
        "vf_coef": 0.5,
        "max_grad_norm": 0.5,
        "policy_kwargs": {"net_arch": {"pi": [64, 64], "vf": [64, 64]}},
    }

    def __init__(
        self,
        env: MultiAgentTrafficLightEnv,
        algorithm: Algorithm = Algorithm.DQN,
        model_params: dict[str, Any] | None = None,
        seed: int | None = None,
    ) -> None:
        if len(env.tl_ids) > MAX_JUNCTIONS:
            raise ValueError(
                f"Max {MAX_JUNCTIONS} junctions per task, got {len(env.tl_ids)}"
            )

        self.env = env
        self.algorithm = algorithm
        self._seed = seed
        self.device = "cuda" if torch.cuda.is_available() else "cpu"

        # Merge params
        if algorithm == Algorithm.DQN:
            params = self.DEFAULT_DQN_PARAMS.copy()
        else:
            params = self.DEFAULT_PPO_PARAMS.copy()
        if model_params:
            params.update(model_params)
        self._params = params

        # Create per-agent SB3 models
        self.models: dict[str, DQN | PPO] = {}
        for tl_id in env.tl_ids:
            adapter = SingleAgentEnvAdapter(env, tl_id)
            if algorithm == Algorithm.DQN:
                self.models[tl_id] = DQN(
                    "MlpPolicy",
                    adapter,
                    verbose=0,
                    seed=seed,
                    device=self.device,
                    **params,
                )
            else:
                self.models[tl_id] = PPO(
                    "MlpPolicy",
                    adapter,
                    verbose=0,
                    seed=seed,
                    device=self.device,
                    **params,
                )

        logger.info(
            f"MultiAgentTrainer: {len(env.tl_ids)} agents, "
            f"algorithm={algorithm.value}, device={self.device}"
        )

    def train(
        self,
        total_timesteps: int,
        callbacks: list[MultiAgentCallback] | None = None,
    ) -> MultiAgentMetrics:
        """Train all agents for the specified number of timesteps."""
        if self.algorithm == Algorithm.DQN:
            return self._train_dqn(total_timesteps, callbacks or [])
        return self._train_ppo(total_timesteps, callbacks or [])

    def _train_dqn(
        self,
        total_timesteps: int,
        callbacks: list[MultiAgentCallback],
    ) -> MultiAgentMetrics:
        """DQN custom collect-train loop."""
        metrics = MultiAgentMetrics()
        metrics.episode_rewards = {tl_id: [] for tl_id in self.env.tl_ids}

        # Per-agent replay buffers
        buffers: dict[str, ReplayBuffer] = {}
        for tl_id in self.env.tl_ids:
            model = self.models[tl_id]
            buffers[tl_id] = ReplayBuffer(
                buffer_size=self._params["buffer_size"],
                observation_space=model.observation_space,
                action_space=model.action_space,
                device=self.device,
            )

        observations = self.env.reset()
        episode_rewards = {tl_id: 0.0 for tl_id in self.env.tl_ids}

        learning_starts = self._params["learning_starts"]
        train_freq = self._params["train_freq"]
        target_update_interval = self._params["target_update_interval"]
        batch_size = self._params["batch_size"]
        tau = self._params["tau"]

        for step in range(1, total_timesteps + 1):
            progress_remaining = 1.0 - step / total_timesteps

            # Each agent selects action (epsilon-greedy via SB3)
            actions = {}
            for tl_id in self.env.tl_ids:
                model = self.models[tl_id]
                # Update exploration rate
                model.exploration_rate = model.exploration_initial_eps + (
                    model.exploration_final_eps - model.exploration_initial_eps
                ) * (1 - progress_remaining)
                action, _ = model.predict(observations[tl_id], deterministic=False)
                actions[tl_id] = int(action)

            # Joint step
            next_observations, rewards, terminateds, truncateds, infos = (
                self.env.step(actions)
            )

            # Store transitions
            for tl_id in self.env.tl_ids:
                done = terminateds[tl_id] or truncateds[tl_id]
                buffers[tl_id].add(
                    obs=observations[tl_id],
                    next_obs=next_observations[tl_id],
                    action=np.array([actions[tl_id]]),
                    reward=np.array([rewards[tl_id]]),
                    done=np.array([done]),
                    infos=[infos[tl_id]],
                )
                episode_rewards[tl_id] += rewards[tl_id]

            # Gradient update
            if step >= learning_starts and step % train_freq == 0:
                for tl_id in self.env.tl_ids:
                    if buffers[tl_id].size() >= batch_size:
                        model = self.models[tl_id]
                        model.replay_buffer = buffers[tl_id]
                        model.train(gradient_steps=1, batch_size=batch_size)

            # Target network update
            if step >= learning_starts and step % target_update_interval == 0:
                for tl_id in self.env.tl_ids:
                    model = self.models[tl_id]
                    # Polyak update
                    for param, target_param in zip(
                        model.q_net.parameters(),
                        model.q_net_target.parameters(),
                    ):
                        target_param.data.copy_(
                            tau * param.data + (1 - tau) * target_param.data
                        )

            # Check for episode end
            any_done = any(
                terminateds[tl_id] or truncateds[tl_id]
                for tl_id in self.env.tl_ids
            )
            if any_done:
                metrics.total_episodes += 1
                for tl_id in self.env.tl_ids:
                    metrics.episode_rewards[tl_id].append(episode_rewards[tl_id])
                    episode_rewards[tl_id] = 0.0

                for cb in callbacks:
                    cb.on_episode_end(metrics.total_episodes, infos)

                observations = self.env.reset()
            else:
                observations = next_observations

            # Callbacks
            for cb in callbacks:
                if not cb.on_step(step, total_timesteps, infos):
                    logger.info(f"Training stopped by callback at step {step}")
                    return metrics

        # Final metrics
        all_rewards = [
            r
            for rewards_list in metrics.episode_rewards.values()
            for r in rewards_list[-10:]
        ]
        metrics.mean_reward = float(np.mean(all_rewards)) if all_rewards else 0.0
        return metrics

    def _train_ppo(
        self,
        total_timesteps: int,
        callbacks: list[MultiAgentCallback],
    ) -> MultiAgentMetrics:
        """PPO custom collect-train loop."""
        metrics = MultiAgentMetrics()
        metrics.episode_rewards = {tl_id: [] for tl_id in self.env.tl_ids}

        n_steps = self._params["n_steps"]
        episode_rewards = {tl_id: 0.0 for tl_id in self.env.tl_ids}
        observations = self.env.reset()
        global_step = 0

        while global_step < total_timesteps:
            # Collect rollout
            rollout_obs: dict[str, list] = {
                tl_id: [] for tl_id in self.env.tl_ids
            }
            rollout_actions: dict[str, list] = {
                tl_id: [] for tl_id in self.env.tl_ids
            }
            rollout_rewards: dict[str, list] = {
                tl_id: [] for tl_id in self.env.tl_ids
            }
            rollout_dones: dict[str, list] = {
                tl_id: [] for tl_id in self.env.tl_ids
            }
            rollout_values: dict[str, list] = {
                tl_id: [] for tl_id in self.env.tl_ids
            }
            rollout_log_probs: dict[str, list] = {
                tl_id: [] for tl_id in self.env.tl_ids
            }

            for _rollout_step in range(n_steps):
                actions = {}
                for tl_id in self.env.tl_ids:
                    model = self.models[tl_id]
                    obs_tensor = (
                        torch.as_tensor(observations[tl_id])
                        .float()
                        .unsqueeze(0)
                        .to(self.device)
                    )

                    with torch.no_grad():
                        dist = model.policy.get_distribution(obs_tensor)
                        action = dist.sample()
                        log_prob = dist.log_prob(action)
                        value = model.policy.predict_values(obs_tensor)

                    actions[tl_id] = int(action.item())
                    rollout_obs[tl_id].append(observations[tl_id].copy())
                    rollout_actions[tl_id].append(actions[tl_id])
                    rollout_values[tl_id].append(float(value.item()))
                    rollout_log_probs[tl_id].append(float(log_prob.item()))

                next_observations, rewards, terminateds, truncateds, infos = (
                    self.env.step(actions)
                )
                global_step += 1

                for tl_id in self.env.tl_ids:
                    done = terminateds[tl_id] or truncateds[tl_id]
                    rollout_rewards[tl_id].append(rewards[tl_id])
                    rollout_dones[tl_id].append(done)
                    episode_rewards[tl_id] += rewards[tl_id]

                any_done = any(
                    terminateds[tl_id] or truncateds[tl_id]
                    for tl_id in self.env.tl_ids
                )
                if any_done:
                    metrics.total_episodes += 1
                    for tl_id in self.env.tl_ids:
                        metrics.episode_rewards[tl_id].append(
                            episode_rewards[tl_id]
                        )
                        episode_rewards[tl_id] = 0.0

                    for cb in callbacks:
                        cb.on_episode_end(metrics.total_episodes, infos)

                    next_observations = self.env.reset()

                observations = next_observations

                # Step callbacks
                for cb in callbacks:
                    if not cb.on_step(global_step, total_timesteps, infos):
                        return metrics

            # Compute last values for bootstrapping and run PPO update per agent
            for tl_id in self.env.tl_ids:
                model = self.models[tl_id]
                obs_tensor = (
                    torch.as_tensor(observations[tl_id])
                    .float()
                    .unsqueeze(0)
                    .to(self.device)
                )
                with torch.no_grad():
                    last_value = float(
                        model.policy.predict_values(obs_tensor).item()
                    )

                # Compute GAE returns and advantages
                n = len(rollout_rewards[tl_id])
                advantages = np.zeros(n, dtype=np.float32)
                last_gae = 0.0
                gamma = self._params["gamma"]
                gae_lambda = self._params["gae_lambda"]

                for t in reversed(range(n)):
                    next_val = (
                        last_value
                        if t == n - 1
                        else rollout_values[tl_id][t + 1]
                    )
                    next_non_terminal = (
                        0.0 if rollout_dones[tl_id][t] else 1.0
                    )
                    delta = (
                        rollout_rewards[tl_id][t]
                        + gamma * next_val * next_non_terminal
                        - rollout_values[tl_id][t]
                    )
                    last_gae = (
                        delta
                        + gamma * gae_lambda * next_non_terminal * last_gae
                    )
                    advantages[t] = last_gae

                returns = advantages + np.array(
                    rollout_values[tl_id], dtype=np.float32
                )

                # PPO update for this agent
                obs_t = torch.FloatTensor(np.array(rollout_obs[tl_id])).to(
                    self.device
                )
                actions_t = torch.LongTensor(rollout_actions[tl_id]).to(
                    self.device
                )
                old_log_probs = torch.FloatTensor(
                    rollout_log_probs[tl_id]
                ).to(self.device)
                advantages_t = torch.FloatTensor(advantages).to(self.device)
                returns_t = torch.FloatTensor(returns).to(self.device)

                # Normalize advantages
                advantages_t = (advantages_t - advantages_t.mean()) / (
                    advantages_t.std() + 1e-8
                )

                clip_range = self._params["clip_range"]
                ent_coef = self._params["ent_coef"]
                vf_coef = self._params["vf_coef"]
                max_grad_norm = self._params["max_grad_norm"]

                for _ in range(self._params["n_epochs"]):
                    dist = model.policy.get_distribution(obs_t)
                    log_probs = dist.log_prob(actions_t)
                    values = model.policy.predict_values(obs_t).squeeze(-1)
                    entropy = dist.entropy()

                    ratio = torch.exp(log_probs - old_log_probs)
                    surr1 = ratio * advantages_t
                    surr2 = (
                        torch.clamp(ratio, 1 - clip_range, 1 + clip_range)
                        * advantages_t
                    )
                    policy_loss = -torch.min(surr1, surr2).mean()
                    value_loss = torch.nn.functional.mse_loss(
                        values, returns_t
                    )
                    entropy_loss = -entropy.mean()

                    loss = (
                        policy_loss
                        + vf_coef * value_loss
                        + ent_coef * entropy_loss
                    )

                    model.policy.optimizer.zero_grad()
                    loss.backward()
                    torch.nn.utils.clip_grad_norm_(
                        model.policy.parameters(), max_grad_norm
                    )
                    model.policy.optimizer.step()

            # Update progress
            for tl_id in self.env.tl_ids:
                model = self.models[tl_id]
                model._n_updates += self._params["n_epochs"]

        all_rewards = [
            r
            for rewards_list in metrics.episode_rewards.values()
            for r in rewards_list[-10:]
        ]
        metrics.mean_reward = float(np.mean(all_rewards)) if all_rewards else 0.0
        return metrics

    def save(self, base_dir: str | Path) -> Path:
        """Save all agent models to a directory."""
        base_dir = Path(base_dir)
        base_dir.mkdir(parents=True, exist_ok=True)

        for tl_id, model in self.models.items():
            model_path = base_dir / f"{tl_id}.zip"
            model.save(str(model_path))

        # Save metadata
        metadata = {
            "network_id": self.env.network_id,
            "tl_ids": self.env.tl_ids,
            "algorithm": self.algorithm.value,
            "scenario": self.env.scenario,
            "created_at": datetime.now().isoformat(),
        }
        with open(base_dir / "metadata.json", "w") as f:
            json.dump(metadata, f, indent=2)

        logger.info(f"Multi-agent models saved to {base_dir}")
        return base_dir

    def run_baseline(self, num_episodes: int = 3) -> dict[str, float]:
        """Run baseline episodes with SUMO's default timing."""
        logger.info(f"Running {num_episodes} baseline episodes (multi-agent)")
        total_waiting = 0.0
        total_queue = 0.0
        total_throughput = 0

        for ep in range(num_episodes):
            observations = self.env.reset()
            done = False
            ep_waiting = 0.0
            ep_queue = 0.0
            ep_throughput = 0
            steps = 0

            while not done:
                # Use current phase (no action change) for baseline
                conn = self.env._get_conn()
                actions = {
                    tl_id: conn.trafficlight.getPhase(tl_id)
                    for tl_id in self.env.tl_ids
                }
                observations, rewards, terminateds, truncateds, infos = (
                    self.env.step(actions)
                )
                done = any(
                    terminateds[t] or truncateds[t] for t in self.env.tl_ids
                )

                for tl_id in self.env.tl_ids:
                    ep_waiting += infos[tl_id].get("avg_waiting_time", 0.0)
                    ep_queue += infos[tl_id].get("avg_queue_length", 0.0)
                    ep_throughput += infos[tl_id].get("throughput", 0)
                steps += 1

            n_agents = len(self.env.tl_ids)
            if steps > 0 and n_agents > 0:
                total_waiting += ep_waiting / (steps * n_agents)
                total_queue += ep_queue / (steps * n_agents)
            total_throughput += ep_throughput

        baseline = {
            "avg_waiting_time": total_waiting / max(num_episodes, 1),
            "avg_queue_length": total_queue / max(num_episodes, 1),
            "throughput": total_throughput // max(num_episodes, 1),
        }
        logger.info(f"Multi-agent baseline: {baseline}")
        return baseline
