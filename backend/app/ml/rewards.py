"""Reward computation functions for traffic light RL algorithms.

Extracted from TrafficLightEnv to enable reuse across different
environment implementations and algorithm configurations.

Reward formulas follow LibSignal/DaRL conventions:
- DQN/CoLight: penalize average NUMBER of waiting vehicles
- PPO: penalize average waiting TIME (normalized and clipped)
"""

import numpy as np


def compute_dqn_reward(lane_waiting_counts: np.ndarray) -> float:
    """Compute reward for DQN/CoLight algorithms.

    Penalizes the average number of halting vehicles across lanes,
    scaled by a factor of 12.

    Args:
        lane_waiting_counts: Array of halting vehicle counts per lane.

    Returns:
        Reward value (non-positive).
    """
    if len(lane_waiting_counts) > 0:
        return float(-np.mean(lane_waiting_counts) * 12.0)
    return 0.0


def compute_ppo_reward(lane_waiting_times: np.ndarray) -> float:
    """Compute reward for PPO algorithm.

    Penalizes the average waiting time across lanes, normalized by 224
    and clipped to [-4, 4].

    Args:
        lane_waiting_times: Array of total waiting times per lane (seconds).

    Returns:
        Reward value clipped to [-4.0, 4.0].
    """
    if len(lane_waiting_times) > 0:
        return float(np.clip(-np.mean(lane_waiting_times) / 224.0, -4.0, 4.0))
    return 0.0


def compute_reward(
    algorithm: str,
    lane_waiting_counts: np.ndarray,
    lane_waiting_times: np.ndarray,
) -> float:
    """Dispatch reward computation to the appropriate algorithm-specific function.

    Args:
        algorithm: RL algorithm name (lowercase). One of "dqn", "colight", "ppo".
        lane_waiting_counts: Array of halting vehicle counts per lane
            (used by dqn/colight).
        lane_waiting_times: Array of total waiting times per lane in seconds
            (used by ppo).

    Returns:
        Computed reward value, or 0.0 for unrecognized algorithms.
    """
    if algorithm in ("dqn", "colight"):
        return compute_dqn_reward(lane_waiting_counts)
    elif algorithm == "ppo":
        return compute_ppo_reward(lane_waiting_times)
    return 0.0
