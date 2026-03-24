"""Training pipeline for the traffic light RL environment.

This module provides a trainer class for training reinforcement learning agents
to optimize traffic light control using custom LibSignal-style training loops
with standalone DQN/PPO agents (no SB3 dependency).
"""

import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import numpy as np
import torch

from app.ml.environment import TrafficLightEnv
from app.ml.networks.dqn_network import DQNAgent
from app.ml.networks.ppo_network import PPOAgent

logger = logging.getLogger(__name__)


class Algorithm(str, Enum):
    """Supported RL algorithms."""

    DQN = "dqn"
    PPO = "ppo"


@dataclass
class EvaluationMetrics:
    """Metrics from model evaluation.

    Attributes:
        mean_reward: Average reward across evaluation episodes
        std_reward: Standard deviation of rewards
        mean_episode_length: Average episode length
        total_episodes: Number of episodes evaluated
        episode_rewards: List of individual episode rewards
        episode_lengths: List of individual episode lengths
    """

    mean_reward: float
    std_reward: float
    mean_episode_length: float
    total_episodes: int
    episode_rewards: list[float]
    episode_lengths: list[int]


class TrainingCallback:
    """Base callback for custom training loop."""

    def on_episode_end(
        self,
        episode: int,
        num_episodes: int,
        episode_reward: float,
        info: dict,
    ) -> bool:
        """Called at end of each episode. Return False to cancel training."""
        return True

    def on_step(
        self,
        decision: int,
        loss: float | None,
        info: dict,
    ) -> None:
        """Called after each decision/step."""
        pass


class TrafficLightTrainer:
    """Trainer for traffic light optimization RL agents.

    Uses custom LibSignal-style training loops with standalone DQN/PPO agents.

    Attributes:
        env: The TrafficLightEnv environment
        algorithm: The RL algorithm to use
        agent: The DQN or PPO agent
    """

    def __init__(
        self,
        env: TrafficLightEnv,
        algorithm: Algorithm = Algorithm.DQN,
        seed: int | None = None,
    ) -> None:
        """Initialize the trainer.

        Args:
            env: The TrafficLightEnv to train on
            algorithm: RL algorithm to use (DQN or PPO)
            seed: Random seed for reproducibility
        """
        self.env = env
        self.algorithm = algorithm
        self._seed = seed
        self._episode_rewards: list[float] = []

        # Trigger lazy space initialization so observation/action spaces are correct
        self.env.reset()

        self._ob_length = env.observation_space.shape[0]
        self._num_actions = env.action_space.n

        # Determine device
        device = "cuda" if torch.cuda.is_available() else "cpu"

        # Create agent based on algorithm
        if algorithm == Algorithm.DQN:
            self.agent = DQNAgent(
                ob_length=self._ob_length,
                num_actions=self._num_actions,
                lr=1e-3,
                gamma=0.95,
                epsilon_start=0.1,
                epsilon_decay=0.995,
                epsilon_min=0.01,
                buffer_size=5000,
                batch_size=64,
                grad_clip=5.0,
                device=device,
            )
        else:
            self.agent = PPOAgent(
                ob_length=self._ob_length,
                num_actions=self._num_actions,
                lr=3e-4,
                gamma=0.99,
                gae_lambda=0.95,
                clip_range=0.1,
                ent_coef=0.001,
                vf_coef=0.5,
                max_grad_norm=0.5,
                n_epochs=4,
                device=device,
            )

        logger.info(
            f"Initialized {algorithm.value.upper()} trainer "
            f"(obs={self._ob_length}, actions={self._num_actions}, device={device})"
        )

    def train(
        self,
        total_timesteps: int,
        callbacks: list[TrainingCallback] | None = None,
    ) -> None:
        """Train the agent.

        Converts total_timesteps to episodes (~360 decisions per episode)
        and runs the algorithm-specific training loop.

        Args:
            total_timesteps: Total number of timesteps to train for
            callbacks: Callbacks for progress reporting and cancellation
        """
        logger.info(f"Starting training for {total_timesteps} timesteps")

        if self.algorithm == Algorithm.DQN:
            self._train_dqn(total_timesteps, callbacks)
        else:
            self._train_ppo(total_timesteps, callbacks)

        logger.info("Training complete")

    def _train_dqn(
        self,
        total_timesteps: int,
        callbacks: list[TrainingCallback] | None,
    ) -> None:
        """DQN training loop (LibSignal pattern)."""
        assert isinstance(self.agent, DQNAgent)
        agent = self.agent
        num_episodes = max(total_timesteps // 360, 10)
        learning_start = 1000
        update_model_rate = 1
        update_target_rate = 10
        total_decisions = 0

        for episode in range(num_episodes):
            obs, info = self.env.reset()
            episode_reward = 0.0
            episode_steps = 0
            done = False

            while not done:
                action = agent.select_action(obs)
                next_obs, reward, terminated, truncated, info = self.env.step(action)
                done = terminated or truncated

                agent.remember(obs, action, reward, next_obs, float(done))
                total_decisions += 1
                episode_reward += reward
                episode_steps += 1

                loss = None
                if total_decisions > learning_start and total_decisions % update_model_rate == 0:
                    if agent.can_train():
                        loss = agent.update(agent.sample_batch())
                        agent.decay_epsilon()

                if total_decisions > learning_start and total_decisions % update_target_rate == 0:
                    agent.update_target_network()

                # Step callback
                for cb in (callbacks or []):
                    cb.on_step(total_decisions, loss, info)

                obs = next_obs

            # Episode end
            self._episode_rewards.append(episode_reward)
            logger.info(
                f"Episode {episode + 1}/{num_episodes}: reward={episode_reward:.2f}, "
                f"steps={episode_steps}, decisions={total_decisions}, "
                f"epsilon={agent.epsilon:.4f}, "
                f"buffer={len(agent.replay_buffer)}"
            )

            # Episode callbacks (cancellation check, progress publish)
            for cb in (callbacks or []):
                if not cb.on_episode_end(episode, num_episodes, episode_reward, info):
                    logger.info("Training cancelled by callback")
                    return

    def _train_ppo(
        self,
        total_timesteps: int,
        callbacks: list[TrainingCallback] | None,
    ) -> None:
        """PPO training loop with rollout collection and GAE."""
        assert isinstance(self.agent, PPOAgent)
        agent = self.agent
        num_episodes = max(total_timesteps // 360, 10)
        n_steps = 360  # Collect this many transitions before update
        total_decisions = 0

        for episode in range(num_episodes):
            obs, info = self.env.reset()
            episode_reward = 0.0
            episode_steps = 0
            done = False

            # Rollout storage
            rollout_obs: list[np.ndarray] = []
            rollout_actions: list[int] = []
            rollout_log_probs: list[float] = []
            rollout_rewards: list[float] = []
            rollout_values: list[float] = []
            rollout_dones: list[bool] = []

            while not done:
                action, log_prob, value = agent.select_action(obs)
                next_obs, reward, terminated, truncated, info = self.env.step(action)
                done = terminated or truncated

                rollout_obs.append(obs)
                rollout_actions.append(action)
                rollout_log_probs.append(log_prob)
                rollout_rewards.append(reward)
                rollout_values.append(value)
                rollout_dones.append(done)

                total_decisions += 1
                episode_reward += reward
                episode_steps += 1

                # Update when rollout is full or episode ends
                if len(rollout_obs) >= n_steps or done:
                    # Get last value for GAE
                    if done:
                        last_value = 0.0
                    else:
                        with torch.no_grad():
                            obs_t = torch.FloatTensor(next_obs).unsqueeze(0).to(agent.device)
                            _, last_val = agent.network(obs_t)
                            last_value = last_val.item()

                    advantages, returns = agent.compute_gae(
                        rollout_rewards, rollout_values, rollout_dones, last_value
                    )

                    rollout = {
                        "obs": np.array(rollout_obs, dtype=np.float32),
                        "actions": np.array(rollout_actions, dtype=np.int64),
                        "old_log_probs": np.array(rollout_log_probs, dtype=np.float32),
                        "advantages": advantages,
                        "returns": returns,
                    }
                    losses = agent.update(rollout)

                    # Clear rollout
                    rollout_obs, rollout_actions, rollout_log_probs = [], [], []
                    rollout_rewards, rollout_values, rollout_dones = [], [], []

                    policy_loss = losses.get("policy_loss")
                    for cb in (callbacks or []):
                        cb.on_step(total_decisions, policy_loss, info)

                obs = next_obs

            self._episode_rewards.append(episode_reward)
            logger.info(
                f"Episode {episode + 1}/{num_episodes}: reward={episode_reward:.2f}, "
                f"steps={episode_steps}, decisions={total_decisions}"
            )

            for cb in (callbacks or []):
                if not cb.on_episode_end(episode, num_episodes, episode_reward, info):
                    logger.info("Training cancelled by callback")
                    return

    def save(self, path: str | Path) -> Path:
        """Save the trained model.

        Saves model weights and metadata as a PyTorch checkpoint.

        Args:
            path: Path to save the model

        Returns:
            The full path where the model was saved
        """
        save_data: dict[str, Any] = {
            "algorithm": self.algorithm.value,
            "ob_length": self._ob_length,
            "num_actions": self._num_actions,
        }
        if self.algorithm == Algorithm.DQN:
            dqn_agent: DQNAgent = self.agent  # type: ignore[assignment]
            save_data["model_state"] = dqn_agent.q_network.state_dict()
            save_data["target_state"] = dqn_agent.target_network.state_dict()
        else:
            ppo_agent: PPOAgent = self.agent  # type: ignore[assignment]
            save_data["model_state"] = ppo_agent.network.state_dict()

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        torch.save(save_data, str(path))
        logger.info(f"Model saved to {path}")
        return path

    def load(self, path: str | Path) -> None:
        """Load a trained model.

        Args:
            path: Path to the saved model checkpoint
        """
        path = Path(path)
        checkpoint = torch.load(str(path), map_location=self.agent.device, weights_only=False)

        if self.algorithm == Algorithm.DQN:
            dqn_agent: DQNAgent = self.agent  # type: ignore[assignment]
            dqn_agent.q_network.load_state_dict(checkpoint["model_state"])
            if "target_state" in checkpoint:
                dqn_agent.target_network.load_state_dict(checkpoint["target_state"])
        else:
            ppo_agent: PPOAgent = self.agent  # type: ignore[assignment]
            ppo_agent.network.load_state_dict(checkpoint["model_state"])

        logger.info(f"Model loaded from {path}")

    def evaluate(
        self,
        num_episodes: int = 10,
        deterministic: bool = True,
    ) -> EvaluationMetrics:
        """Evaluate the trained model.

        Runs the model for a specified number of episodes and collects metrics.

        Args:
            num_episodes: Number of episodes to evaluate
            deterministic: Whether to use deterministic actions

        Returns:
            EvaluationMetrics with aggregated results
        """
        logger.info(f"Evaluating model for {num_episodes} episodes")

        episode_rewards: list[float] = []
        episode_lengths: list[int] = []

        for episode in range(num_episodes):
            obs, _ = self.env.reset()
            episode_reward = 0.0
            episode_length = 0
            terminated = False
            truncated = False

            while not terminated and not truncated:
                if self.algorithm == Algorithm.DQN:
                    dqn_agent: DQNAgent = self.agent  # type: ignore[assignment]
                    action = dqn_agent.select_action(obs, deterministic=deterministic)
                else:
                    ppo_agent: PPOAgent = self.agent  # type: ignore[assignment]
                    # PPO: deterministic = argmax of action probs
                    if deterministic:
                        with torch.no_grad():
                            obs_t = torch.FloatTensor(obs).unsqueeze(0).to(ppo_agent.device)
                            action_probs, _ = ppo_agent.network(obs_t)
                            action = int(action_probs.argmax(dim=1).item())
                    else:
                        action, _, _ = ppo_agent.select_action(obs)

                obs, reward, terminated, truncated, _ = self.env.step(int(action))
                episode_reward += reward
                episode_length += 1

            episode_rewards.append(episode_reward)
            episode_lengths.append(episode_length)

            logger.debug(
                f"Episode {episode + 1}: reward={episode_reward:.2f}, "
                f"length={episode_length}"
            )

        metrics = EvaluationMetrics(
            mean_reward=float(np.mean(episode_rewards)),
            std_reward=float(np.std(episode_rewards)),
            mean_episode_length=float(np.mean(episode_lengths)),
            total_episodes=num_episodes,
            episode_rewards=episode_rewards,
            episode_lengths=episode_lengths,
        )

        logger.info(
            f"Evaluation complete: mean_reward={metrics.mean_reward:.2f} "
            f"(+/- {metrics.std_reward:.2f}), "
            f"mean_length={metrics.mean_episode_length:.0f}"
        )

        return metrics

    def run_baseline(self, num_episodes: int = 3) -> dict[str, float]:
        """Run baseline episodes with SUMO's default timing.

        Returns dict with avg_waiting_time, avg_queue_length, throughput.
        """
        logger.info(f"Running {num_episodes} baseline episodes")
        total_waiting = 0.0
        total_queue = 0.0
        total_throughput = 0

        for _ in range(num_episodes):
            self.env.reset()
            env = self.env.unwrapped
            conn = env._get_conn()

            # Restore SUMO's default fixed-time program
            conn.trafficlight.setProgram(env.tl_id, "0")

            ep_waiting = 0.0
            ep_queue = 0.0
            ep_throughput = 0
            steps = 0

            num_seconds = getattr(env, "num_seconds", getattr(env, "max_steps", 3600))
            delta_time = getattr(env, "delta_time", getattr(env, "steps_per_action", 5))
            lanes = getattr(env, "_lanes", getattr(env, "_controlled_lanes", []))

            for sim_step in range(num_seconds):
                conn.simulationStep()

                if (sim_step + 1) % delta_time == 0:
                    lane_vids = []
                    for lane in lanes:
                        lane_vids.extend(conn.lane.getLastStepVehicleIDs(lane))
                    wait = sum(conn.vehicle.getWaitingTime(v) for v in lane_vids)
                    ep_waiting += wait / max(len(lane_vids), 1)

                    queue = sum(
                        conn.lane.getLastStepHaltingNumber(lane) for lane in lanes
                    )
                    ep_queue += queue / max(len(lanes), 1)
                    ep_throughput += len(lane_vids)
                    steps += 1

            if steps > 0:
                total_waiting += ep_waiting / steps
                total_queue += ep_queue / steps
            total_throughput += ep_throughput

        baseline = {
            "avg_waiting_time": total_waiting / max(num_episodes, 1),
            "avg_queue_length": total_queue / max(num_episodes, 1),
            "throughput": total_throughput // max(num_episodes, 1),
        }
        logger.info(f"Baseline metrics: {baseline}")
        return baseline

    @classmethod
    def from_pretrained(
        cls,
        path: str | Path,
        env: TrafficLightEnv,
        algorithm: Algorithm,
    ) -> "TrafficLightTrainer":
        """Create a trainer with a pretrained model.

        Args:
            path: Path to the saved model checkpoint
            env: The environment to use
            algorithm: The algorithm used to train the model

        Returns:
            A TrafficLightTrainer instance with the loaded model
        """
        trainer = cls(env=env, algorithm=algorithm)
        trainer.load(path)
        return trainer
