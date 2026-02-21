"""Multi-agent environment for traffic light optimization using SUMO.

This module provides a multi-agent environment that manages N traffic light
agents within a single SUMO simulation instance, plus a lightweight gym.Env
adapter for Stable-Baselines3 model construction.
"""

import logging
from typing import Any

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from app.ml import rewards
from app.services import sumo_service

logger = logging.getLogger(__name__)


class MultiAgentTrafficLightEnv:
    """Multi-agent environment managing N traffic lights in one SUMO simulation.

    NOT a gym.Env subclass. Each traffic light is treated as an independent
    agent with its own observation space, action space, and reward signal.
    All agents share a single SUMO simulation instance and act simultaneously.

    Observation format per agent (LibSignal/DaRL standard):
        obs = [
            *lane_vehicle_counts,  # Vehicle count per incoming lane [num_lanes]
            *phase_one_hot,        # Current phase one-hot encoding [num_phases]
        ]

    Attributes:
        network_path: Path to the SUMO network file
        network_id: ID of the network for SUMO service
        tl_ids: List of traffic light IDs to control
        max_steps: Maximum steps per episode before truncation
        steps_per_action: Number of simulation steps between actions
        gui: Whether to launch SUMO with GUI
        scenario: Traffic scenario for route generation
        algorithm: RL algorithm type for reward computation
    """

    def __init__(
        self,
        network_path: str,
        network_id: str,
        tl_ids: list[str],
        max_steps: int = 3600,
        steps_per_action: int = 5,
        gui: bool = False,
        scenario: str = "moderate",
        algorithm: str = "dqn",
    ) -> None:
        """Initialize the multi-agent traffic light environment.

        Args:
            network_path: Path to the SUMO .net.xml file
            network_id: ID of the network for SUMO service
            tl_ids: List of traffic light IDs to control
            max_steps: Maximum simulation steps per episode (default: 3600 = 1 hour)
            steps_per_action: Number of simulation steps between agent actions (default: 5)
            gui: Whether to launch SUMO with GUI (default: False)
            scenario: Traffic scenario for route generation when routes are generated.
                Options: "light", "moderate", "heavy", "rush_hour" (default: "moderate")
            algorithm: RL algorithm type for reward computation.
                Options: "dqn", "colight", "ppo" (default: "dqn")
        """
        self.network_path = network_path
        self.network_id = network_id
        self.tl_ids = tl_ids
        self.max_steps = max_steps
        self.steps_per_action = steps_per_action
        self.gui = gui
        self.scenario = scenario
        self.algorithm = algorithm.lower()

        # State tracking
        self._current_step = 0
        self._is_initialized = False

        # Per-agent state (populated on first reset when SUMO is running)
        self._controlled_lanes: dict[str, list[str]] = {}
        self._num_phases: dict[str, int] = {}
        self._observation_spaces: dict[str, spaces.Box] = {}
        self._action_spaces: dict[str, spaces.Discrete] = {}

    @property
    def agent_ids(self) -> list[str]:
        """Return the list of agent (traffic light) IDs."""
        return self.tl_ids

    def _initialize_spaces(self) -> None:
        """Initialize per-agent action and observation spaces from SUMO.

        Must be called after SUMO simulation is started so TraCI is available.
        Follows the same pattern as TrafficLightEnv._initialize_spaces() but
        does it for every traffic light agent.
        """
        for tl_id in self.tl_ids:
            tl_info = sumo_service.get_traffic_light(tl_id)
            if tl_info is None:
                raise RuntimeError(f"Traffic light '{tl_id}' not found in network")

            controlled_lanes = tl_info["controlled_lanes"]
            self._controlled_lanes[tl_id] = controlled_lanes

            num_phases = self._get_num_phases(tl_id)
            self._num_phases[tl_id] = num_phases

            # Action space: select one of the available phases
            self._action_spaces[tl_id] = spaces.Discrete(num_phases)

            # Observation space (LibSignal format):
            # lane_vehicle_counts [num_lanes] + phase_one_hot [num_phases]
            num_lanes = len(controlled_lanes)
            obs_dim = num_lanes + num_phases
            self._observation_spaces[tl_id] = spaces.Box(
                low=0.0,
                high=np.inf,
                shape=(obs_dim,),
                dtype=np.float32,
            )

            logger.info(
                f"Agent '{tl_id}' initialized: {num_lanes} lanes, {num_phases} phases, "
                f"observation dim={obs_dim}"
            )

        self._is_initialized = True
        logger.info(
            f"MultiAgentTrafficLightEnv initialized: {len(self.tl_ids)} agents, "
            f"algorithm={self.algorithm} (LibSignal format)"
        )

    def _get_num_phases(self, tl_id: str) -> int:
        """Get the number of phases for a traffic light.

        Args:
            tl_id: Traffic light ID

        Returns:
            Number of phases in the traffic light program
        """
        if not sumo_service.SUMO_AVAILABLE or sumo_service.traci is None:
            return 4  # Default fallback

        try:
            logic = sumo_service.traci.trafficlight.getAllProgramLogics(tl_id)
            if logic and len(logic) > 0:
                return len(logic[0].phases)
        except Exception as e:
            logger.warning(f"Could not get phase count for {tl_id}: {e}")

        return 4  # Default fallback

    def reset(self, seed: int | None = None) -> dict[str, np.ndarray]:
        """Reset the environment: stop sim, generate routes, start SUMO, init spaces.

        Args:
            seed: Random seed for reproducibility

        Returns:
            Dict mapping each agent (tl_id) to its initial observation
        """
        # Stop any existing simulation
        if sumo_service.is_simulation_running():
            sumo_service.stop_simulation()

        # Generate routes (same pattern as TrafficLightEnv.reset())
        from pathlib import Path

        from app.models.schemas import TrafficScenario
        from app.services import route_service

        scenario_map = {
            "light": TrafficScenario.LIGHT,
            "moderate": TrafficScenario.MODERATE,
            "heavy": TrafficScenario.HEAVY,
            "rush_hour": TrafficScenario.RUSH_HOUR,
        }
        scenario_enum = scenario_map.get(self.scenario, TrafficScenario.MODERATE)

        output_dir = str(Path(self.network_path).parent)
        route_result = route_service.generate_routes(
            network_path=self.network_path,
            output_dir=output_dir,
            scenario=scenario_enum,
            seed=seed,
        )
        routes_path = route_result["routes_path"]

        # Start fresh simulation with routes
        sumo_service.start_simulation(
            network_path=self.network_path,
            network_id=self.network_id,
            routes_path=routes_path,
            gui=self.gui,
        )

        # Initialize per-agent spaces if not done yet
        if not self._is_initialized:
            self._initialize_spaces()

        # Reset state
        self._current_step = 0

        # Collect initial observations for all agents
        observations: dict[str, np.ndarray] = {}
        for tl_id in self.tl_ids:
            observations[tl_id] = self._get_observation(tl_id)

        return observations

    def step(
        self, actions: dict[str, int]
    ) -> tuple[
        dict[str, np.ndarray],   # observations
        dict[str, float],        # rewards
        dict[str, bool],         # terminateds
        dict[str, bool],         # truncateds
        dict[str, dict],         # infos
    ]:
        """Execute actions for all agents and advance the simulation.

        Sets ALL agent phases first, THEN advances SUMO by steps_per_action
        steps, so all agents act simultaneously.

        Args:
            actions: Dict mapping each agent (tl_id) to its chosen phase index

        Returns:
            Tuple of (observations, rewards, terminateds, truncateds, infos),
            each a dict keyed by tl_id
        """
        # Set ALL agent phases before advancing the simulation
        for tl_id, action in actions.items():
            if not self._action_spaces[tl_id].contains(action):
                raise ValueError(
                    f"Invalid action {action} for agent '{tl_id}'. "
                    f"Must be in [0, {self._num_phases[tl_id]})"
                )
            sumo_service.set_traffic_light_phase(tl_id, action)

        # Advance simulation by steps_per_action steps
        step_metrics: list[dict] = []
        arrived_count = 0
        for _ in range(self.steps_per_action):
            metrics = sumo_service.step()
            step_metrics.append(metrics)
            self._current_step += 1
            if sumo_service.traci is not None:
                arrived_count += sumo_service.traci.simulation.getArrivedNumber()

        # Collect per-agent results
        observations: dict[str, np.ndarray] = {}
        agent_rewards: dict[str, float] = {}
        terminateds: dict[str, bool] = {}
        truncateds: dict[str, bool] = {}
        infos: dict[str, dict] = {}

        truncated = self._current_step >= self.max_steps

        for tl_id in self.tl_ids:
            observations[tl_id] = self._get_observation(tl_id)
            agent_rewards[tl_id] = self._compute_reward(tl_id)
            terminateds[tl_id] = False  # Episode doesn't naturally terminate
            truncateds[tl_id] = truncated
            # Compute per-agent traffic metrics
            lane_waiting_counts = self._get_lane_waiting_counts(tl_id)
            lane_waiting_times = self._get_lane_waiting_times(tl_id)
            avg_waiting_time = float(np.mean(lane_waiting_times)) if len(lane_waiting_times) > 0 else 0.0
            avg_queue_length = float(np.mean(lane_waiting_counts)) if len(lane_waiting_counts) > 0 else 0.0

            infos[tl_id] = {
                "step": self._current_step,
                "action": actions.get(tl_id),
                "total_vehicles": step_metrics[-1]["total_vehicles"] if step_metrics else 0,
                "average_speed": step_metrics[-1].get("average_speed", 0.0) if step_metrics else 0.0,
                "throughput": arrived_count,
                "avg_waiting_time": avg_waiting_time,
                "avg_queue_length": avg_queue_length,
            }

        return observations, agent_rewards, terminateds, truncateds, infos

    def _get_observation(self, tl_id: str) -> np.ndarray:
        """Collect current observation for a single agent from SUMO.

        Observation format (LibSignal/DaRL standard):
            obs = [
                *lane_vehicle_counts,  # Vehicle count per incoming lane
                *phase_one_hot,        # Current phase one-hot encoding
            ]

        Args:
            tl_id: Traffic light ID

        Returns:
            Numpy array of observations with shape (num_lanes + num_phases,)
        """
        controlled_lanes = self._controlled_lanes[tl_id]
        num_phases = self._num_phases[tl_id]

        if not sumo_service.SUMO_AVAILABLE or sumo_service.traci is None:
            obs_dim = len(controlled_lanes) + num_phases
            return np.zeros(obs_dim, dtype=np.float32)

        traci = sumo_service.traci

        # Collect vehicle counts per lane (LibSignal format)
        lane_vehicle_counts: list[float] = []
        for lane_id in controlled_lanes:
            try:
                vehicle_count = traci.lane.getLastStepVehicleNumber(lane_id)
                lane_vehicle_counts.append(float(vehicle_count))
            except Exception as e:
                logger.warning(f"Error getting vehicle count for lane {lane_id}: {e}")
                lane_vehicle_counts.append(0.0)

        # Get current phase as one-hot encoding
        current_phase = 0
        try:
            current_phase = traci.trafficlight.getPhase(tl_id)
        except Exception as e:
            logger.warning(f"Error getting current phase for {tl_id}: {e}")

        phase_one_hot = np.zeros(num_phases, dtype=np.float32)
        if 0 <= current_phase < num_phases:
            phase_one_hot[current_phase] = 1.0

        # Combine all observations (LibSignal format: lane counts + phase)
        observation = np.concatenate([
            np.array(lane_vehicle_counts, dtype=np.float32),
            phase_one_hot,
        ])

        return observation

    def _get_lane_waiting_counts(self, tl_id: str) -> np.ndarray:
        """Get the number of halting (waiting) vehicles per controlled lane for an agent.

        Args:
            tl_id: Traffic light ID

        Returns:
            Numpy array of halting vehicle counts per lane
        """
        controlled_lanes = self._controlled_lanes[tl_id]

        if not sumo_service.SUMO_AVAILABLE or sumo_service.traci is None:
            return np.zeros(len(controlled_lanes), dtype=np.float32)

        traci = sumo_service.traci
        waiting_counts: list[float] = []

        for lane_id in controlled_lanes:
            try:
                halting_count = traci.lane.getLastStepHaltingNumber(lane_id)
                waiting_counts.append(float(halting_count))
            except Exception as e:
                logger.warning(f"Error getting halting count for lane {lane_id}: {e}")
                waiting_counts.append(0.0)

        return np.array(waiting_counts, dtype=np.float32)

    def _get_lane_waiting_times(self, tl_id: str) -> np.ndarray:
        """Get the total waiting time per controlled lane for an agent.

        Args:
            tl_id: Traffic light ID

        Returns:
            Numpy array of total waiting times per lane (in seconds)
        """
        controlled_lanes = self._controlled_lanes[tl_id]

        if not sumo_service.SUMO_AVAILABLE or sumo_service.traci is None:
            return np.zeros(len(controlled_lanes), dtype=np.float32)

        traci = sumo_service.traci
        waiting_times: list[float] = []

        for lane_id in controlled_lanes:
            try:
                vehicle_ids = traci.lane.getLastStepVehicleIDs(lane_id)
                lane_wait_time = sum(
                    traci.vehicle.getWaitingTime(vid) for vid in vehicle_ids
                )
                waiting_times.append(float(lane_wait_time))
            except Exception as e:
                logger.warning(f"Error getting waiting times for lane {lane_id}: {e}")
                waiting_times.append(0.0)

        return np.array(waiting_times, dtype=np.float32)

    def _compute_reward(self, tl_id: str) -> float:
        """Compute reward for a single agent using algorithm-specific formula.

        Delegates to rewards.compute_reward() for known algorithms (dqn,
        colight, ppo). Returns 0.0 for unrecognized algorithms.

        Args:
            tl_id: Traffic light ID

        Returns:
            Reward value for this agent
        """
        lane_waiting_counts = self._get_lane_waiting_counts(tl_id)
        lane_waiting_times = self._get_lane_waiting_times(tl_id)
        return rewards.compute_reward(
            self.algorithm, lane_waiting_counts, lane_waiting_times
        )

    def close(self) -> None:
        """Clean up the environment and stop SUMO simulation."""
        if sumo_service.is_simulation_running():
            sumo_service.stop_simulation()
        self._is_initialized = False
        logger.info("MultiAgentTrafficLightEnv closed")


class SingleAgentEnvAdapter(gym.Env):
    """Lightweight gym.Env wrapper for SB3 model construction.

    Provides .observation_space and .action_space attributes required by
    Stable-Baselines3 to construct models, but does NOT implement step/reset.
    The actual simulation is driven through MultiAgentTrafficLightEnv directly.

    Attributes:
        multi_env: Reference to the parent MultiAgentTrafficLightEnv
        tl_id: Traffic light ID this adapter represents
    """

    metadata = {"render_modes": []}

    def __init__(self, multi_env: MultiAgentTrafficLightEnv, tl_id: str) -> None:
        """Initialize the adapter with spaces from the multi-agent environment.

        Args:
            multi_env: The MultiAgentTrafficLightEnv instance
            tl_id: Traffic light ID whose spaces to expose

        Raises:
            KeyError: If tl_id is not found in multi_env's initialized spaces
        """
        super().__init__()
        self.multi_env = multi_env
        self.tl_id = tl_id
        self.observation_space = multi_env._observation_spaces[tl_id]
        self.action_space = multi_env._action_spaces[tl_id]

    def reset(
        self,
        *,
        seed: int | None = None,
        options: dict[str, Any] | None = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        """Not implemented. Use MultiAgentTrafficLightEnv.reset() directly.

        Raises:
            NotImplementedError: Always
        """
        raise NotImplementedError("Use MultiAgentTrafficLightEnv.reset() directly")

    def step(
        self, action: int
    ) -> tuple[np.ndarray, float, bool, bool, dict[str, Any]]:
        """Not implemented. Use MultiAgentTrafficLightEnv.step() directly.

        Raises:
            NotImplementedError: Always
        """
        raise NotImplementedError("Use MultiAgentTrafficLightEnv.step() directly")
