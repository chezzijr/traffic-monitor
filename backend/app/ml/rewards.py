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
    """PPO reward based on waiting times, clipped.

    reward = clip(-mean(lane_waiting_times) / 224.0, -4.0, 4.0)
    """
    waiting_times = []
    for lane_id in controlled_lanes:
        vehicle_ids = traci.lane.getLastStepVehicleIDs(lane_id)
        lane_wait = sum(traci.vehicle.getWaitingTime(vid) for vid in vehicle_ids)
        waiting_times.append(lane_wait)
    if not waiting_times:
        return 0.0
    return float(np.clip(-np.mean(waiting_times) / 224.0, -4.0, 4.0))


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
