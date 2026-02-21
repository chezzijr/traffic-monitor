"""Multi-agent trainer for traffic light optimization with shared SUMO simulation.

This module provides a custom training loop for N independent SB3 models that
share a single SUMO simulation. Cannot use SB3's .learn() because it owns the
env step loop -- all agents must share one sim, so we need a manual
collect-train loop.

Supports both DQN (off-policy, replay buffer) and PPO (on-policy, rollout buffer)
with proper epsilon schedule management for DQN and GAE advantage computation
for PPO.
"""

import copy
import json
import logging
from pathlib import Path
from typing import Any

import numpy as np
import torch as th
from stable_baselines3 import DQN, PPO
from stable_baselines3.common.base_class import BaseAlgorithm
from stable_baselines3.common import utils as sb3_utils
from stable_baselines3.common.utils import obs_as_tensor, polyak_update

from app.ml.multi_agent_env import MultiAgentTrafficLightEnv, SingleAgentEnvAdapter
from app.ml.trainer import Algorithm

logger = logging.getLogger(__name__)


# Re-use default hyperparams from the single-agent trainer to stay DRY.
# Imported here to avoid circular imports while keeping a single source of truth.
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


class MultiAgentCallback:
    """Callback protocol for the multi-agent training loop.

    Implement any subset of methods. Default implementations are no-ops
    (on_step returns True to continue training).
    """

    def on_step(
        self,
        step: int,
        total_timesteps: int,
        obs_dict: dict[str, np.ndarray],
        rewards_dict: dict[str, float],
        infos_dict: dict[str, dict],
    ) -> bool:
        """Called after every environment step.

        Args:
            step: Current global timestep (0-indexed).
            total_timesteps: Total timesteps the loop will run.
            obs_dict: Per-agent observations after the step.
            rewards_dict: Per-agent rewards from the step.
            infos_dict: Per-agent info dicts from the step.

        Returns:
            True to continue training, False to stop early.
        """
        return True

    def on_episode_end(
        self,
        episode_count: int,
        episode_rewards: dict[str, float],
    ) -> None:
        """Called when an episode ends (environment truncated/terminated).

        Args:
            episode_count: Number of episodes completed so far.
            episode_rewards: Cumulative reward per agent for the finished episode.
        """

    def on_training_end(self) -> None:
        """Called once when the training loop finishes."""


class MultiAgentTrainer:
    """Trainer for N independent SB3 models sharing one SUMO simulation.

    Creates one SB3 model per traffic light agent using SingleAgentEnvAdapter
    for space information, then drives a manual collect-train loop through
    the shared MultiAgentTrafficLightEnv.

    Attributes:
        env: The multi-agent environment.
        algorithm: RL algorithm (DQN or PPO).
        agents: Mapping from traffic-light ID to SB3 model.
    """

    def __init__(
        self,
        env: MultiAgentTrafficLightEnv,
        algorithm: Algorithm,
        model_params: dict[str, Any] | None = None,
        seed: int | None = None,
    ) -> None:
        """Initialize the multi-agent trainer.

        Resets the environment to populate observation/action spaces, then
        creates one SB3 model per agent using SingleAgentEnvAdapter.

        Args:
            env: Multi-agent traffic light environment.
            algorithm: Which RL algorithm to use.
            model_params: Optional overrides merged into default hyperparams.
            seed: Random seed for reproducibility.
        """
        self.env = env
        self.algorithm = algorithm
        self._seed = seed

        # Reset env to initialise per-agent spaces (must happen before model creation).
        self.env.reset(seed=seed)

        # Build merged hyperparams (deep-copy defaults so mutations are isolated).
        params = self._get_default_params(algorithm)
        if model_params:
            params.update(model_params)

        # Create one model per agent.
        self.agents: dict[str, BaseAlgorithm] = {}
        for tl_id in env.agent_ids:
            adapter = SingleAgentEnvAdapter(env, tl_id)
            self.agents[tl_id] = self._create_model(adapter, algorithm, params)

        logger.info(
            f"MultiAgentTrainer initialised: {len(self.agents)} agents, "
            f"algorithm={algorithm.value}"
        )

    # ------------------------------------------------------------------
    # Model creation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_default_params(algorithm: Algorithm) -> dict[str, Any]:
        """Return deep-copied default hyperparams for *algorithm*."""
        if algorithm == Algorithm.DQN:
            return copy.deepcopy(DEFAULT_DQN_PARAMS)
        return copy.deepcopy(DEFAULT_PPO_PARAMS)

    def _create_model(
        self,
        adapter: SingleAgentEnvAdapter,
        algorithm: Algorithm,
        params: dict[str, Any],
    ) -> BaseAlgorithm:
        """Instantiate a fresh SB3 model for a single agent.

        Args:
            adapter: Gym-compatible wrapper exposing the agent's spaces.
            algorithm: DQN or PPO.
            params: Merged hyperparams (deep-copied already).

        Returns:
            A newly constructed SB3 model.
        """
        common = {"env": adapter, "verbose": 0, "seed": self._seed}
        # Deep-copy params to avoid sharing mutable dicts between agents.
        agent_params = copy.deepcopy(params)

        if algorithm == Algorithm.DQN:
            model = DQN(policy="MlpPolicy", **common, **agent_params)
        else:
            model = PPO(policy="MlpPolicy", **common, **agent_params)

        # SB3 normally sets _logger inside _setup_learn() (called by .learn()).
        # Since we drive the loop manually, configure it here so model.train()
        # can log without AttributeError.
        model._logger = sb3_utils.configure_logger(verbose=0)
        return model

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def train(
        self,
        total_timesteps: int,
        callbacks: list[MultiAgentCallback] | None = None,
    ) -> dict[str, Any]:
        """Run the manual collect-train loop.

        Dispatches to algorithm-specific inner loops for DQN and PPO.

        Args:
            total_timesteps: Number of environment steps to run.
            callbacks: Optional list of MultiAgentCallback instances.

        Returns:
            Dict with training summary (total_steps, episodes, per-agent
            cumulative rewards history).
        """
        cbs = callbacks or []
        logger.info(
            f"Starting multi-agent training for {total_timesteps} timesteps "
            f"({self.algorithm.value.upper()}, {len(self.agents)} agents)"
        )

        if self.algorithm == Algorithm.DQN:
            result = self._train_dqn(total_timesteps, cbs)
        else:
            result = self._train_ppo(total_timesteps, cbs)

        for cb in cbs:
            cb.on_training_end()

        logger.info(
            f"Multi-agent training finished: {result['total_steps']} steps, "
            f"{result['episodes']} episodes"
        )
        return result

    # ------------------------------------------------------------------
    # DQN inner loop
    # ------------------------------------------------------------------

    def _train_dqn(
        self,
        total_timesteps: int,
        callbacks: list[MultiAgentCallback],
    ) -> dict[str, Any]:
        """DQN collect-train loop with replay buffer and epsilon schedule.

        For each step:
        1. Each agent picks an action (epsilon-greedy via model.predict).
        2. Joint step through the shared environment.
        3. Store transition in each agent's replay buffer.
        4. Periodically call model.train() for gradient updates.
        5. Periodically update target networks (polyak).
        6. Update epsilon via _current_progress_remaining.
        """
        obs_dict = self.env.reset(seed=self._seed)

        episode_count = 0
        episode_rewards: dict[str, float] = {tl: 0.0 for tl in self.agents}
        all_episode_rewards: dict[str, list[float]] = {tl: [] for tl in self.agents}
        total_steps = 0

        for step in range(total_timesteps):
            # --- collect actions ---
            actions: dict[str, int] = {}
            for tl_id, model in self.agents.items():
                action, _ = model.predict(obs_dict[tl_id], deterministic=False)
                actions[tl_id] = int(action)

            # --- env step ---
            new_obs, rewards, terminateds, truncateds, infos = self.env.step(actions)
            total_steps += 1

            # --- store transitions & train ---
            for tl_id, model in self.agents.items():
                assert isinstance(model, DQN)
                done = terminateds[tl_id] or truncateds[tl_id]

                # Add to replay buffer (shapes: obs [obs_dim], action [1], etc.)
                model.replay_buffer.add(
                    obs_dict[tl_id],
                    new_obs[tl_id],
                    np.array([actions[tl_id]]),
                    np.array([rewards[tl_id]]),
                    np.array([done]),
                    [infos[tl_id]],
                )

                # Gradient updates after learning_starts, at train_freq interval.
                if (
                    step >= model.learning_starts
                    and step % model.train_freq.frequency == 0
                ):
                    model.train(
                        gradient_steps=model.gradient_steps,
                        batch_size=model.batch_size,
                    )

                # Target network polyak update.
                if (
                    step >= model.learning_starts
                    and step % model.target_update_interval == 0
                ):
                    polyak_update(
                        model.q_net.parameters(),
                        model.q_net_target.parameters(),
                        model.tau,
                    )

                # Accumulate episode reward.
                episode_rewards[tl_id] += rewards[tl_id]

            # --- epsilon schedule ---
            for tl_id, model in self.agents.items():
                assert isinstance(model, DQN)
                model._current_progress_remaining = 1.0 - (step + 1) / total_timesteps
                model.exploration_rate = model.exploration_schedule(
                    model._current_progress_remaining
                )

            # --- callbacks ---
            cont = True
            for cb in callbacks:
                if not cb.on_step(step, total_timesteps, new_obs, rewards, infos):
                    cont = False
            if not cont:
                break

            # --- episode boundary ---
            if any(truncateds.values()) or any(terminateds.values()):
                episode_count += 1
                for cb in callbacks:
                    cb.on_episode_end(episode_count, episode_rewards)
                for tl_id in self.agents:
                    all_episode_rewards[tl_id].append(episode_rewards[tl_id])
                    episode_rewards[tl_id] = 0.0
                obs_dict = self.env.reset()
            else:
                obs_dict = new_obs

        return {
            "total_steps": total_steps,
            "episodes": episode_count,
            "episode_rewards": all_episode_rewards,
        }

    # ------------------------------------------------------------------
    # PPO inner loop
    # ------------------------------------------------------------------

    def _train_ppo(
        self,
        total_timesteps: int,
        callbacks: list[MultiAgentCallback],
    ) -> dict[str, Any]:
        """PPO collect-train loop with rollout buffer and GAE.

        Outer loop runs until total_timesteps consumed. Each iteration:
        1. Collect n_steps transitions into each agent's rollout buffer.
        2. Compute returns & advantages (GAE).
        3. Call model.train() for n_epochs of minibatch updates.
        """
        obs_dict = self.env.reset(seed=self._seed)

        # All PPO agents share the same n_steps (from merged hyperparams).
        first_model = next(iter(self.agents.values()))
        assert isinstance(first_model, PPO)
        n_steps = first_model.n_steps

        episode_count = 0
        episode_rewards: dict[str, float] = {tl: 0.0 for tl in self.agents}
        all_episode_rewards: dict[str, list[float]] = {tl: [] for tl in self.agents}
        total_steps = 0
        stop_requested = False

        # Track episode_start flags across rollout phases.  True at the
        # beginning or right after an env reset.
        episode_starts: dict[str, bool] = {tl: True for tl in self.agents}

        while total_steps < total_timesteps and not stop_requested:
            # Reset rollout buffers for all agents.
            for model in self.agents.values():
                assert isinstance(model, PPO)
                model.rollout_buffer.reset()

            # ---- collect n_steps transitions ----
            steps_collected = 0
            terminateds: dict[str, bool] = {tl: False for tl in self.agents}
            truncateds: dict[str, bool] = {tl: False for tl in self.agents}
            for rollout_step in range(n_steps):
                if total_steps >= total_timesteps:
                    break

                actions: dict[str, int] = {}
                values: dict[str, th.Tensor] = {}
                log_probs: dict[str, th.Tensor] = {}

                # Get action, value, log_prob from each agent's policy.
                for tl_id, model in self.agents.items():
                    assert isinstance(model, PPO)
                    obs_tensor = obs_as_tensor(
                        obs_dict[tl_id].reshape(1, -1), model.device
                    )
                    with th.no_grad():
                        dist = model.policy.get_distribution(obs_tensor)
                        action_tensor = dist.get_actions(deterministic=False)
                        log_prob = dist.log_prob(action_tensor)
                        value = model.policy.predict_values(obs_tensor)

                    action_np = action_tensor.cpu().numpy().flatten()
                    actions[tl_id] = int(action_np[0])
                    values[tl_id] = value.flatten()
                    log_probs[tl_id] = log_prob

                # Joint env step.
                new_obs, rewards, terminateds, truncateds, infos = self.env.step(actions)
                total_steps += 1
                steps_collected += 1

                # Store in each agent's rollout buffer.
                for tl_id, model in self.agents.items():
                    assert isinstance(model, PPO)
                    model.rollout_buffer.add(
                        obs_dict[tl_id].reshape(1, -1),
                        np.array([[actions[tl_id]]]),
                        np.array([rewards[tl_id]]),
                        np.array([episode_starts[tl_id]], dtype=np.float32),
                        values[tl_id],
                        log_probs[tl_id],
                    )
                    episode_rewards[tl_id] += rewards[tl_id]

                # Callbacks.
                for cb in callbacks:
                    if not cb.on_step(total_steps - 1, total_timesteps, new_obs, rewards, infos):
                        stop_requested = True
                if stop_requested:
                    break

                # Episode boundary.
                if any(truncateds.values()) or any(terminateds.values()):
                    episode_count += 1
                    for cb in callbacks:
                        cb.on_episode_end(episode_count, episode_rewards)
                    for tl_id in self.agents:
                        all_episode_rewards[tl_id].append(episode_rewards[tl_id])
                        episode_rewards[tl_id] = 0.0
                    obs_dict = self.env.reset()
                    episode_starts = {tl: True for tl in self.agents}
                else:
                    obs_dict = new_obs
                    episode_starts = {tl: False for tl in self.agents}

            # ---- compute returns & advantage, then train ----
            if steps_collected > 0:
                # Check if last step was an episode boundary.
                last_done = any(terminateds.values()) or any(truncateds.values())

                for tl_id, model in self.agents.items():
                    assert isinstance(model, PPO)

                    # Bootstrap value for the last observation.
                    with th.no_grad():
                        obs_tensor = obs_as_tensor(
                            obs_dict[tl_id].reshape(1, -1), model.device
                        )
                        last_value = model.policy.predict_values(obs_tensor)

                    model.rollout_buffer.compute_returns_and_advantage(
                        last_values=last_value.flatten(),
                        dones=np.array([last_done], dtype=np.float32),
                    )
                    model.train()

                # Update progress for learning rate / clip range schedules.
                for model in self.agents.values():
                    assert isinstance(model, PPO)
                    model._current_progress_remaining = max(
                        0.0, 1.0 - total_steps / total_timesteps
                    )

        return {
            "total_steps": total_steps,
            "episodes": episode_count,
            "episode_rewards": all_episode_rewards,
        }

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, base_dir: str | Path) -> Path:
        """Save all agent models and metadata to *base_dir*.

        Layout::

            base_dir/
                metadata.json
                <tl_id_1>.zip
                <tl_id_2>.zip
                ...

        Args:
            base_dir: Directory to write into (created if needed).

        Returns:
            The base_dir Path.
        """
        base_dir = Path(base_dir)
        base_dir.mkdir(parents=True, exist_ok=True)

        # Save each agent model.
        for tl_id, model in self.agents.items():
            model_path = base_dir / tl_id
            model.save(str(model_path))
            logger.debug(f"Saved agent '{tl_id}' to {model_path}.zip")

        # Save metadata.
        metadata = {
            "network_id": self.env.network_id,
            "tl_ids": list(self.agents.keys()),
            "algorithm": self.algorithm.value,
            "scenario": self.env.scenario,
        }
        metadata_path = base_dir / "metadata.json"
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)

        logger.info(
            f"Multi-agent models saved to {base_dir} "
            f"({len(self.agents)} agents)"
        )
        return base_dir

    def load(self, base_dir: str | Path) -> None:
        """Load agent models from *base_dir*.

        Reads metadata.json, then loads each per-agent .zip file.

        Args:
            base_dir: Directory previously written by save().

        Raises:
            FileNotFoundError: If base_dir or metadata.json is missing.
            ValueError: If algorithm in metadata doesn't match self.algorithm.
        """
        base_dir = Path(base_dir)
        metadata_path = base_dir / "metadata.json"
        if not metadata_path.exists():
            raise FileNotFoundError(f"metadata.json not found in {base_dir}")

        with open(metadata_path) as f:
            metadata = json.load(f)

        saved_algo = metadata["algorithm"]
        if saved_algo != self.algorithm.value:
            raise ValueError(
                f"Algorithm mismatch: trainer is {self.algorithm.value}, "
                f"saved models are {saved_algo}"
            )

        tl_ids: list[str] = metadata["tl_ids"]
        for tl_id in tl_ids:
            model_path = base_dir / f"{tl_id}.zip"
            if not model_path.exists():
                raise FileNotFoundError(f"Model file not found: {model_path}")

            adapter = SingleAgentEnvAdapter(self.env, tl_id)
            if self.algorithm == Algorithm.DQN:
                self.agents[tl_id] = DQN.load(str(model_path), env=adapter)
            else:
                self.agents[tl_id] = PPO.load(str(model_path), env=adapter)

            logger.debug(f"Loaded agent '{tl_id}' from {model_path}")

        logger.info(
            f"Multi-agent models loaded from {base_dir} "
            f"({len(self.agents)} agents)"
        )

    @classmethod
    def from_pretrained(
        cls,
        base_dir: str | Path,
        env: MultiAgentTrafficLightEnv,
        algorithm: Algorithm,
    ) -> "MultiAgentTrainer":
        """Create a trainer and immediately load pre-trained agent models.

        Args:
            base_dir: Directory with saved models + metadata.json.
            env: Multi-agent environment (must have same tl_ids).
            algorithm: Algorithm the models were trained with.

        Returns:
            A MultiAgentTrainer with loaded models.
        """
        trainer = cls(env=env, algorithm=algorithm)
        trainer.load(base_dir)
        return trainer
