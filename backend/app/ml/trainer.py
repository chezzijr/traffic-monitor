"""Training pipeline for the traffic light RL environment.

This module provides a trainer class for training reinforcement learning agents
to optimize traffic light control using Stable-Baselines3.
"""

import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import numpy as np
from stable_baselines3 import DQN, PPO
from stable_baselines3.common.base_class import BaseAlgorithm
from stable_baselines3.common.callbacks import BaseCallback, CallbackList

from app.ml.environment import TrafficLightEnv

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


class MetricsLoggingCallback(BaseCallback):
    """Callback for logging training metrics.

    Logs training progress including rewards, episode lengths, and other
    metrics at configurable intervals.
    """

    def __init__(
        self,
        log_interval: int = 1000,
        verbose: int = 1,
    ) -> None:
        """Initialize the metrics logging callback.

        Args:
            log_interval: Log metrics every N timesteps
            verbose: Verbosity level (0=silent, 1=info, 2=debug)
        """
        super().__init__(verbose)
        self.log_interval = log_interval
        self._episode_rewards: list[float] = []
        self._episode_lengths: list[int] = []
        self._current_episode_reward = 0.0
        self._current_episode_length = 0

    def _on_step(self) -> bool:
        """Called after each step.

        Returns:
            True to continue training, False to stop
        """
        # Track episode rewards and lengths
        reward = self.locals.get("rewards", [0])[0]
        self._current_episode_reward += reward
        self._current_episode_length += 1

        # Check for episode end
        dones = self.locals.get("dones", [False])
        if dones[0]:
            self._episode_rewards.append(self._current_episode_reward)
            self._episode_lengths.append(self._current_episode_length)
            self._current_episode_reward = 0.0
            self._current_episode_length = 0

        # Log at intervals
        if self.n_calls % self.log_interval == 0 and self._episode_rewards:
            recent_rewards = self._episode_rewards[-10:]
            recent_lengths = self._episode_lengths[-10:]

            mean_reward = np.mean(recent_rewards)
            mean_length = np.mean(recent_lengths)

            if self.verbose >= 1:
                logger.info(
                    f"Timestep {self.num_timesteps}: "
                    f"Mean reward (last 10 eps): {mean_reward:.2f}, "
                    f"Mean length: {mean_length:.0f}, "
                    f"Total episodes: {len(self._episode_rewards)}"
                )

        return True

    def _on_training_end(self) -> None:
        """Called when training ends."""
        if self._episode_rewards and self.verbose >= 1:
            logger.info(
                f"Training complete. Total episodes: {len(self._episode_rewards)}, "
                f"Final mean reward: {np.mean(self._episode_rewards[-10:]):.2f}"
            )

    @property
    def episode_rewards(self) -> list[float]:
        """Get recorded episode rewards."""
        return self._episode_rewards.copy()

    @property
    def episode_lengths(self) -> list[int]:
        """Get recorded episode lengths."""
        return self._episode_lengths.copy()


class TrafficLightTrainer:
    """Trainer for traffic light optimization RL agents.

    Supports training with DQN or PPO algorithms via Stable-Baselines3.

    Attributes:
        env: The TrafficLightEnv environment
        algorithm: The RL algorithm to use
        model: The trained model (created during init or load)
    """

    # Default hyperparameters for each algorithm
    DEFAULT_DQN_PARAMS: dict[str, Any] = {
        "learning_rate": 1e-4,
        "buffer_size": 100_000,
        "learning_starts": 1000,
        "batch_size": 64,
        "tau": 0.005,
        "gamma": 0.99,
        "train_freq": 4,
        "target_update_interval": 1000,
        "exploration_fraction": 0.1,
        "exploration_final_eps": 0.05,
    }

    DEFAULT_PPO_PARAMS: dict[str, Any] = {
        "learning_rate": 3e-4,
        "n_steps": 2048,
        "batch_size": 64,
        "n_epochs": 10,
        "gamma": 0.99,
        "gae_lambda": 0.95,
        "clip_range": 0.2,
        "ent_coef": 0.01,
    }

    def __init__(
        self,
        env: TrafficLightEnv,
        algorithm: Algorithm = Algorithm.DQN,
        model_params: dict[str, Any] | None = None,
        seed: int | None = None,
    ) -> None:
        """Initialize the trainer.

        Args:
            env: The TrafficLightEnv to train on
            algorithm: RL algorithm to use (DQN or PPO)
            model_params: Custom hyperparameters (merged with defaults)
            seed: Random seed for reproducibility
        """
        self.env = env
        self.algorithm = algorithm
        self._seed = seed

        # Merge custom params with defaults
        params = self._get_default_params(algorithm)
        if model_params:
            params.update(model_params)

        # Create the model
        self.model = self._create_model(params)
        logger.info(f"Initialized {algorithm.value.upper()} trainer")

    def _get_default_params(self, algorithm: Algorithm) -> dict[str, Any]:
        """Get default hyperparameters for the algorithm.

        Args:
            algorithm: The RL algorithm

        Returns:
            Dictionary of default hyperparameters
        """
        if algorithm == Algorithm.DQN:
            return self.DEFAULT_DQN_PARAMS.copy()
        # algorithm == Algorithm.PPO
        return self.DEFAULT_PPO_PARAMS.copy()

    def _create_model(self, params: dict[str, Any]) -> BaseAlgorithm:
        """Create a new model with the given parameters.

        Args:
            params: Hyperparameters for the model

        Returns:
            The created model
        """
        common_kwargs = {
            "env": self.env,
            "verbose": 0,
            "seed": self._seed,
        }

        if self.algorithm == Algorithm.DQN:
            return DQN(policy="MlpPolicy", **common_kwargs, **params)
        # self.algorithm == Algorithm.PPO
        return PPO(policy="MlpPolicy", **common_kwargs, **params)

    def train(
        self,
        total_timesteps: int,
        callbacks: list[BaseCallback] | None = None,
        log_interval: int = 1000,
        progress_bar: bool = False,
    ) -> MetricsLoggingCallback:
        """Train the model.

        Args:
            total_timesteps: Total number of timesteps to train for
            callbacks: Additional callbacks to use during training
            log_interval: Interval for logging metrics
            progress_bar: Whether to show a progress bar

        Returns:
            The metrics logging callback with training history
        """
        logger.info(f"Starting training for {total_timesteps} timesteps")

        # Create metrics callback
        metrics_callback = MetricsLoggingCallback(log_interval=log_interval)

        # Combine with user callbacks
        all_callbacks = [metrics_callback]
        if callbacks:
            all_callbacks.extend(callbacks)
        callback_list = CallbackList(all_callbacks)

        # Train
        self.model.learn(
            total_timesteps=total_timesteps,
            callback=callback_list,
            progress_bar=progress_bar,
        )

        logger.info("Training complete")
        return metrics_callback

    def save(self, path: str | Path) -> Path:
        """Save the trained model.

        Args:
            path: Path to save the model (without extension)

        Returns:
            The full path where the model was saved
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        self.model.save(str(path))
        logger.info(f"Model saved to {path}")
        return path

    def load(self, path: str | Path) -> None:
        """Load a trained model.

        Args:
            path: Path to the saved model (with or without extension)
        """
        path = Path(path)

        if self.algorithm == Algorithm.DQN:
            self.model = DQN.load(str(path), env=self.env)
        elif self.algorithm == Algorithm.PPO:
            self.model = PPO.load(str(path), env=self.env)
        else:
            raise ValueError(f"Unsupported algorithm: {self.algorithm}")

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
                action, _ = self.model.predict(obs, deterministic=deterministic)
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

    @classmethod
    def from_pretrained(
        cls,
        path: str | Path,
        env: TrafficLightEnv,
        algorithm: Algorithm,
    ) -> "TrafficLightTrainer":
        """Create a trainer with a pretrained model.

        Args:
            path: Path to the saved model
            env: The environment to use
            algorithm: The algorithm used to train the model

        Returns:
            A TrafficLightTrainer instance with the loaded model
        """
        trainer = cls(env=env, algorithm=algorithm)
        trainer.load(path)
        return trainer
