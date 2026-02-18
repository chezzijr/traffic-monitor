"""Gymnasium environment for traffic light optimization using SUMO.

This module provides a Gymnasium-compatible environment for training
reinforcement learning agents to optimize traffic light control.
"""

import logging
from typing import Any

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from app.services import sumo_service

logger = logging.getLogger(__name__)


class TrafficLightEnv(gym.Env):
    """Gymnasium environment for single traffic light optimization.

    The environment wraps SUMO simulation and provides:
    - Observation: vehicle counts per incoming lane + current phase (one-hot)
      Following LibSignal/DaRL observation format for compatibility.
    - Action: select next traffic light phase
    - Reward: negative change in total waiting time

    Observation format (LibSignal standard):
        obs = [
            *lane_vehicle_counts,  # Vehicle count per incoming lane [num_lanes]
            *phase_one_hot,        # Current phase one-hot encoding [num_phases]
        ]
        Typical shape: [8-12] lanes + [4-8] phases = [12-20] total

    Attributes:
        network_path: Path to the SUMO network file
        tl_id: Traffic light ID to control
        max_steps: Maximum steps per episode before truncation
        steps_per_action: Number of simulation steps between actions
        routes_path: Path to pre-generated routes file (optional)
        scenario: Traffic scenario for route generation (light/moderate/heavy/rush_hour)
    """

    metadata = {"render_modes": ["human"]}

    def __init__(
        self,
        network_path: str,
        network_id: str,
        tl_id: str,
        max_steps: int = 3600,
        steps_per_action: int = 5,
        gui: bool = False,
        routes_path: str | None = None,
        scenario: str = "moderate",
        algorithm: str = "dqn",
    ) -> None:
        """Initialize the traffic light environment.

        Args:
            network_path: Path to the SUMO .net.xml file
            network_id: ID of the network for SUMO service
            tl_id: ID of the traffic light to control
            max_steps: Maximum simulation steps per episode (default: 3600 = 1 hour)
            steps_per_action: Number of simulation steps between agent actions (default: 5)
            gui: Whether to launch SUMO with GUI (default: False)
            routes_path: Path to pre-generated .rou.xml file (optional).
                If not provided, routes are generated automatically on reset.
            scenario: Traffic scenario for route generation when routes_path is None.
                Options: "light", "moderate", "heavy", "rush_hour" (default: "moderate")
            algorithm: RL algorithm type for reward computation.
                Options: "dqn", "colight", "ppo" (default: "dqn")
                - "dqn"/"colight": Uses lane waiting counts with reward = -mean(counts) * 12
                - "ppo": Uses lane waiting times with reward = clip(-mean(times) / 224, -4, 4)
        """
        super().__init__()

        self.network_path = network_path
        self.network_id = network_id
        self.tl_id = tl_id
        self.max_steps = max_steps
        self.steps_per_action = steps_per_action
        self.gui = gui
        self.routes_path = routes_path
        self.scenario = scenario
        self.algorithm = algorithm.lower()

        # State tracking
        self._current_step = 0
        self._prev_total_wait_time = 0.0
        self._controlled_lanes: list[str] = []
        self._num_phases = 0
        self._is_initialized = False

        # Spaces will be properly defined after first reset when we know the network
        # Placeholder spaces - will be updated in reset()
        self.action_space = spaces.Discrete(4)  # Will be updated based on actual phases
        self.observation_space = spaces.Box(
            low=0.0,
            high=np.inf,
            shape=(1,),  # Placeholder, updated in reset
            dtype=np.float32,
        )

    def _initialize_spaces(self) -> None:
        """Initialize action and observation spaces based on traffic light config.

        Observation space follows LibSignal/DaRL format:
        - Vehicle counts per incoming lane [num_lanes]
        - Current phase one-hot encoding [num_phases]
        Total observation dimension: num_lanes + num_phases
        """
        # Get traffic light info
        tl_info = sumo_service.get_traffic_light(self.tl_id)
        if tl_info is None:
            raise RuntimeError(f"Traffic light '{self.tl_id}' not found in network")

        self._controlled_lanes = tl_info["controlled_lanes"]

        # Get number of phases from the traffic light program
        self._num_phases = self._get_num_phases()

        # Action space: select one of the available phases
        self.action_space = spaces.Discrete(self._num_phases)

        # Observation space (LibSignal format):
        # - lane_vehicle_counts: vehicle count per incoming lane [num_lanes]
        # - phase_one_hot: current phase one-hot encoding [num_phases]
        num_lanes = len(self._controlled_lanes)
        obs_dim = num_lanes + self._num_phases
        self.observation_space = spaces.Box(
            low=0.0,
            high=np.inf,
            shape=(obs_dim,),
            dtype=np.float32,
        )

        self._is_initialized = True
        logger.info(
            f"Environment initialized: {num_lanes} lanes, {self._num_phases} phases, "
            f"observation dim={obs_dim}, algorithm={self.algorithm} (LibSignal format)"
        )

    def _get_num_phases(self) -> int:
        """Get the number of phases for the traffic light.

        Returns:
            Number of phases in the traffic light program
        """
        # Access TraCI to get phase count
        if not sumo_service.SUMO_AVAILABLE or sumo_service.traci is None:
            return 4  # Default fallback

        try:
            logic = sumo_service.traci.trafficlight.getAllProgramLogics(self.tl_id)
            if logic and len(logic) > 0:
                # Get the first (current) program's phases
                return len(logic[0].phases)
        except Exception as e:
            logger.warning(f"Could not get phase count for {self.tl_id}: {e}")

        return 4  # Default fallback

    def reset(
        self,
        *,
        seed: int | None = None,
        options: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> tuple[np.ndarray, dict[str, Any]]:
        """Reset the environment to initial state.

        Stops any existing simulation and starts a fresh one.
        If no routes_path was provided at init, generates routes using route_service
        with the configured traffic scenario.

        Args:
            seed: Random seed for reproducibility
            options: Additional options (unused, required by Gymnasium API)

        Returns:
            Tuple of (initial_observation, info_dict)
        """
        super().reset(seed=seed)

        # Stop any existing simulation
        if sumo_service.is_simulation_running():
            sumo_service.stop_simulation()

        # Generate routes if not provided
        from pathlib import Path

        from app.models.schemas import TrafficScenario
        from app.services import route_service

        if self.routes_path is None:
            # Map scenario string to enum
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
                seed=seed,  # Use the seed from reset() for reproducibility
            )
            routes_path = route_result["routes_path"]
        else:
            routes_path = self.routes_path

        # Start fresh simulation with routes
        # Note: vtypes are already embedded in the routes file by duarouter
        sumo_service.start_simulation(
            network_path=self.network_path,
            network_id=self.network_id,
            routes_path=routes_path,
            gui=self.gui,
        )

        # Initialize spaces if not done yet
        if not self._is_initialized:
            self._initialize_spaces()

        # Reset state
        self._current_step = 0
        self._prev_total_wait_time = self._compute_total_wait_time()

        observation = self._get_observation()
        info = {
            "step": self._current_step,
            "tl_id": self.tl_id,
            "num_lanes": len(self._controlled_lanes),
            "num_phases": self._num_phases,
            "algorithm": self.algorithm,
        }

        return observation, info

    def step(
        self, action: int
    ) -> tuple[np.ndarray, float, bool, bool, dict[str, Any]]:
        """Execute an action and advance the simulation.

        Args:
            action: Phase index to set for the traffic light

        Returns:
            Tuple of (observation, reward, terminated, truncated, info)
        """
        # Validate action
        if not self.action_space.contains(action):
            raise ValueError(f"Invalid action {action}. Must be in [0, {self._num_phases})")

        # Set the traffic light phase
        sumo_service.set_traffic_light_phase(self.tl_id, action)

        # Advance simulation by steps_per_action steps
        step_metrics = []
        arrived_count = 0
        for _ in range(self.steps_per_action):
            metrics = sumo_service.step()
            step_metrics.append(metrics)
            self._current_step += 1
            # Track vehicles that completed their trips in this sub-step
            if sumo_service.traci is not None:
                arrived_count += sumo_service.traci.simulation.getArrivedNumber()

        # Compute reward using algorithm-specific formula (LibSignal/DaRL)
        current_total_wait = self._compute_total_wait_time()
        reward = self._compute_reward(current_total_wait)
        self._prev_total_wait_time = current_total_wait

        # Compute traffic metrics
        num_vehicles = len(sumo_service.traci.vehicle.getIDList()) if sumo_service.traci is not None else 0
        avg_waiting_time = current_total_wait / max(1, num_vehicles)
        lane_waiting_counts = self._get_lane_waiting_counts()
        avg_queue_length = float(np.mean(lane_waiting_counts)) if len(lane_waiting_counts) > 0 else 0.0

        # Get new observation
        observation = self._get_observation()

        # Check termination conditions
        terminated = False  # Episode doesn't naturally terminate
        truncated = self._current_step >= self.max_steps

        # Gather info
        info = {
            "step": self._current_step,
            "total_wait_time": current_total_wait,
            "action": action,
            "total_vehicles": step_metrics[-1]["total_vehicles"] if step_metrics else 0,
            "average_speed": step_metrics[-1].get("average_speed", 0.0) if step_metrics else 0.0,
            "avg_waiting_time": avg_waiting_time,
            "avg_queue_length": avg_queue_length,
            "throughput": arrived_count,
        }

        return observation, reward, terminated, truncated, info

    def _get_observation(self) -> np.ndarray:
        """Collect current observation from SUMO using LibSignal format.

        Observation format (LibSignal/DaRL standard):
            obs = [
                *lane_vehicle_counts,  # Vehicle count per incoming lane [num_lanes]
                *phase_one_hot,        # Current phase one-hot encoding [num_phases]
            ]

        Returns:
            Numpy array of observations with shape (num_lanes + num_phases,)
        """
        if not sumo_service.SUMO_AVAILABLE or sumo_service.traci is None:
            # Return zeros if SUMO not available
            obs_dim = len(self._controlled_lanes) + self._num_phases
            return np.zeros(obs_dim, dtype=np.float32)

        traci = sumo_service.traci

        # Collect vehicle counts per lane (LibSignal format)
        lane_vehicle_counts = []

        for lane_id in self._controlled_lanes:
            try:
                # Vehicle count: total number of vehicles on the lane
                vehicle_count = traci.lane.getLastStepVehicleNumber(lane_id)
                lane_vehicle_counts.append(float(vehicle_count))
            except Exception as e:
                logger.warning(f"Error getting vehicle count for lane {lane_id}: {e}")
                lane_vehicle_counts.append(0.0)

        # Get current phase as one-hot encoding
        current_phase = 0
        try:
            current_phase = traci.trafficlight.getPhase(self.tl_id)
        except Exception as e:
            logger.warning(f"Error getting current phase for {self.tl_id}: {e}")

        phase_one_hot = np.zeros(self._num_phases, dtype=np.float32)
        if 0 <= current_phase < self._num_phases:
            phase_one_hot[current_phase] = 1.0

        # Combine all observations (LibSignal format: lane counts + phase)
        observation = np.concatenate([
            np.array(lane_vehicle_counts, dtype=np.float32),
            phase_one_hot,
        ])

        return observation

    def _compute_total_wait_time(self) -> float:
        """Compute total waiting time of all vehicles in the simulation.

        Returns:
            Total accumulated waiting time across all vehicles
        """
        if not sumo_service.SUMO_AVAILABLE or sumo_service.traci is None:
            return 0.0

        try:
            traci = sumo_service.traci
            vehicle_ids = traci.vehicle.getIDList()
            total_wait = sum(traci.vehicle.getWaitingTime(vid) for vid in vehicle_ids)
            return float(total_wait)
        except Exception as e:
            logger.warning(f"Error computing total wait time: {e}")
            return 0.0

    def _get_lane_waiting_counts(self) -> np.ndarray:
        """Get the number of halting (waiting) vehicles per controlled lane.

        Uses SUMO's getLastStepHaltingNumber which counts vehicles with
        speed < 0.1 m/s on each lane.

        Returns:
            Numpy array of halting vehicle counts per lane
        """
        if not sumo_service.SUMO_AVAILABLE or sumo_service.traci is None:
            return np.zeros(len(self._controlled_lanes), dtype=np.float32)

        traci = sumo_service.traci
        waiting_counts = []

        for lane_id in self._controlled_lanes:
            try:
                # Halting number: vehicles with speed < 0.1 m/s
                halting_count = traci.lane.getLastStepHaltingNumber(lane_id)
                waiting_counts.append(float(halting_count))
            except Exception as e:
                logger.warning(f"Error getting halting count for lane {lane_id}: {e}")
                waiting_counts.append(0.0)

        return np.array(waiting_counts, dtype=np.float32)

    def _get_lane_waiting_times(self) -> np.ndarray:
        """Get the total waiting time per controlled lane.

        Sums the waiting time of all vehicles on each controlled lane.

        Returns:
            Numpy array of total waiting times per lane (in seconds)
        """
        if not sumo_service.SUMO_AVAILABLE or sumo_service.traci is None:
            return np.zeros(len(self._controlled_lanes), dtype=np.float32)

        traci = sumo_service.traci
        waiting_times = []

        for lane_id in self._controlled_lanes:
            try:
                # Get all vehicles on this lane and sum their waiting times
                vehicle_ids = traci.lane.getLastStepVehicleIDs(lane_id)
                lane_wait_time = sum(
                    traci.vehicle.getWaitingTime(vid) for vid in vehicle_ids
                )
                waiting_times.append(float(lane_wait_time))
            except Exception as e:
                logger.warning(f"Error getting waiting times for lane {lane_id}: {e}")
                waiting_times.append(0.0)

        return np.array(waiting_times, dtype=np.float32)

    def _compute_reward(self, current_total_wait: float) -> float:
        """Compute reward based on algorithm type using LibSignal/DaRL formulas.

        Reward functions:
        - DQN/CoLight: reward = -mean(lane_waiting_counts) * 12
            Penalizes average NUMBER of waiting vehicles on incoming lanes
        - PPO: reward = clip(-mean(lane_waiting_times) / 224, -4, 4)
            Penalizes average waiting TIME (normalized and clipped)

        Args:
            current_total_wait: Current total waiting time (used for info, not reward)

        Returns:
            Reward value based on the configured algorithm
        """
        if self.algorithm in ("dqn", "colight"):
            # DQN/CoLight reward: penalize average number of waiting vehicles
            lane_waiting_counts = self._get_lane_waiting_counts()
            if len(lane_waiting_counts) > 0:
                reward = -np.mean(lane_waiting_counts) * 12.0
            else:
                reward = 0.0

        elif self.algorithm == "ppo":
            # PPO reward: penalize average waiting time (normalized and clipped)
            lane_waiting_times = self._get_lane_waiting_times()
            if len(lane_waiting_times) > 0:
                reward = np.clip(-np.mean(lane_waiting_times) / 224.0, -4.0, 4.0)
            else:
                reward = 0.0

        else:
            # Fallback: use original wait time change method
            wait_time_change = current_total_wait - self._prev_total_wait_time
            reward = -wait_time_change / 10.0

        return float(reward)

    def render(self) -> None:
        """Render the environment.

        If GUI mode is enabled, SUMO-GUI handles rendering.
        Otherwise, this is a no-op.
        """
        # SUMO-GUI handles rendering when gui=True
        pass

    def close(self) -> None:
        """Clean up the environment and stop SUMO simulation."""
        if sumo_service.is_simulation_running():
            sumo_service.stop_simulation()
        self._is_initialized = False
        logger.info("TrafficLightEnv closed")


class MultiScenarioEnvWrapper(gym.Wrapper):
    """Wrapper that rotates scenarios during training for generalization.

    This wrapper changes the traffic scenario on each reset, allowing the agent
    to learn across different traffic conditions (light, moderate, heavy, rush_hour).

    Attributes:
        scenarios: List of scenario names to rotate through
        mode: Scenario selection mode ('round_robin', 'random', or 'curriculum')
    """

    def __init__(
        self,
        env: TrafficLightEnv,
        scenarios: list[str] | None = None,
        mode: str = "round_robin",
    ) -> None:
        """Initialize the multi-scenario wrapper.

        Args:
            env: The TrafficLightEnv to wrap
            scenarios: List of scenario names. Defaults to all scenarios.
            mode: Selection mode:
                - 'round_robin': Cycle through scenarios in order
                - 'random': Randomly select scenario each reset
                - 'curriculum': Progress from easy to hard as training advances
        """
        super().__init__(env)
        self.scenarios = scenarios or ["light", "moderate", "heavy", "rush_hour"]
        self.mode = mode
        self._scenario_idx = 0
        self._episode_count = 0
        self._curriculum_threshold = 50  # Episodes before advancing difficulty

    def reset(
        self,
        *,
        seed: int | None = None,
        options: dict[str, Any] | None = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        """Reset with a new scenario based on the selection mode.

        Args:
            seed: Random seed for reproducibility
            options: Additional options (passed to wrapped env)

        Returns:
            Tuple of (initial_observation, info_dict)
        """
        # Select scenario based on mode
        if self.mode == "round_robin":
            scenario = self.scenarios[self._scenario_idx % len(self.scenarios)]
            self._scenario_idx += 1
        elif self.mode == "random":
            scenario = np.random.choice(self.scenarios)
        elif self.mode == "curriculum":
            # Progress through scenarios based on episode count
            # Stay on easier scenarios longer, then advance
            progress = self._episode_count / (self._curriculum_threshold * len(self.scenarios))
            idx = min(int(progress * len(self.scenarios)), len(self.scenarios) - 1)
            scenario = self.scenarios[idx]
        else:
            scenario = self.scenarios[0]

        # Update the wrapped environment's scenario
        self.env.scenario = scenario
        self._episode_count += 1

        # Log scenario change
        logger.debug(f"Episode {self._episode_count}: Using scenario '{scenario}'")

        # Call parent reset
        obs, info = self.env.reset(seed=seed, options=options)

        # Add scenario info
        info["scenario"] = scenario
        info["episode_count"] = self._episode_count

        return obs, info

    def get_current_scenario(self) -> str:
        """Get the current scenario name.

        Returns:
            Current scenario name
        """
        return getattr(self.env, 'scenario', 'unknown')

    def set_curriculum_threshold(self, threshold: int) -> None:
        """Set the number of episodes before advancing curriculum difficulty.

        Args:
            threshold: Episodes per difficulty level
        """
        self._curriculum_threshold = threshold
