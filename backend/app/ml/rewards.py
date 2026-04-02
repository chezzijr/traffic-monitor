"""Reward functions for RL traffic light optimization."""

import numpy as np


def compute_dqn_reward(controlled_lanes: list[str], traci) -> float:
    """DQN reward based on halting vehicle counts.

    reward = -mean(lane_halting_counts) * 12.0
    """
    halting_counts = [
        traci.lane.getLastStepHaltingNumber(lane_id)
        for lane_id in controlled_lanes
    ]
    if not halting_counts:
        return 0.0
    return -float(np.mean(halting_counts)) * 12.0


def compute_ppo_reward(controlled_lanes: list[str], traci) -> float:
    """PPO reward: same as DQN = -mean(lane_halting_counts) * 12.0

    LibSignal uses the same reward formula for all algorithms.
    """
    return compute_dqn_reward(controlled_lanes, traci)


def compute_reward(algorithm: str, controlled_lanes: list[str], traci) -> float:
    """Dispatch to the correct reward function based on algorithm."""
    algo = algorithm.lower()
    if algo == "dqn":
        return compute_dqn_reward(controlled_lanes, traci)
    elif algo == "ppo":
        return compute_ppo_reward(controlled_lanes, traci)
    else:
        # Fallback: not used in practice
        return 0.0
