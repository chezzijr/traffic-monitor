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
    - Observation: queue lengths, waiting times per lane, current phase
    - Action: select next traffic light phase
    - Reward: negative change in total waiting time

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
        """Initialize action and observation spaces based on traffic light config."""
        # Get traffic light info
        tl_info = sumo_service.get_traffic_light(self.tl_id)
        if tl_info is None:
            raise RuntimeError(f"Traffic light '{self.tl_id}' not found in network")

        self._controlled_lanes = tl_info["controlled_lanes"]

        # Get number of phases from the traffic light program
        self._num_phases = self._get_num_phases()

        # Action space: select one of the available phases
        self.action_space = spaces.Discrete(self._num_phases)

        # Observation space:
        # - queue_lengths: one per controlled lane
        # - waiting_times: one per controlled lane
        # - current_phase: one-hot encoded
        num_lanes = len(self._controlled_lanes)
        obs_dim = num_lanes * 2 + self._num_phases
        self.observation_space = spaces.Box(
            low=0.0,
            high=np.inf,
            shape=(obs_dim,),
            dtype=np.float32,
        )

        self._is_initialized = True
        logger.info(
            f"Environment initialized: {num_lanes} lanes, {self._num_phases} phases, "
            f"observation dim={obs_dim}"
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
        for _ in range(self.steps_per_action):
            metrics = sumo_service.step()
            step_metrics.append(metrics)
            self._current_step += 1

        # Compute reward (negative change in total wait time)
        current_total_wait = self._compute_total_wait_time()
        reward = self._compute_reward(current_total_wait)
        self._prev_total_wait_time = current_total_wait

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
        }

        return observation, reward, terminated, truncated, info

    def _get_observation(self) -> np.ndarray:
        """Collect current observation from SUMO.

        Observation includes:
        - Queue lengths per controlled lane
        - Waiting times per controlled lane
        - One-hot encoded current phase

        Returns:
            Numpy array of observations
        """
        if not sumo_service.SUMO_AVAILABLE or sumo_service.traci is None:
            # Return zeros if SUMO not available
            obs_dim = len(self._controlled_lanes) * 2 + self._num_phases
            return np.zeros(obs_dim, dtype=np.float32)

        traci = sumo_service.traci

        # Collect queue lengths and waiting times per lane
        queue_lengths = []
        waiting_times = []

        for lane_id in self._controlled_lanes:
            try:
                # Queue length: number of halting vehicles on the lane
                queue_length = traci.lane.getLastStepHaltingNumber(lane_id)
                queue_lengths.append(float(queue_length))

                # Waiting time: sum of waiting times of vehicles on the lane
                # Use accumulated waiting time from vehicles on this lane
                vehicle_ids = traci.lane.getLastStepVehicleIDs(lane_id)
                lane_wait_time = sum(
                    traci.vehicle.getWaitingTime(vid) for vid in vehicle_ids
                )
                waiting_times.append(float(lane_wait_time))
            except Exception as e:
                logger.warning(f"Error getting metrics for lane {lane_id}: {e}")
                queue_lengths.append(0.0)
                waiting_times.append(0.0)

        # Get current phase as one-hot encoding
        current_phase = 0
        try:
            current_phase = traci.trafficlight.getPhase(self.tl_id)
        except Exception as e:
            logger.warning(f"Error getting current phase for {self.tl_id}: {e}")

        phase_one_hot = np.zeros(self._num_phases, dtype=np.float32)
        if 0 <= current_phase < self._num_phases:
            phase_one_hot[current_phase] = 1.0

        # Combine all observations
        observation = np.concatenate([
            np.array(queue_lengths, dtype=np.float32),
            np.array(waiting_times, dtype=np.float32),
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

    def _compute_reward(self, current_total_wait: float) -> float:
        """Compute reward based on change in total waiting time.

        The reward is the negative change in total waiting time.
        Decreasing wait time gives positive reward.
        Increasing wait time gives negative reward.

        Args:
            current_total_wait: Current total waiting time

        Returns:
            Reward value (negative of wait time change)
        """
        wait_time_change = current_total_wait - self._prev_total_wait_time
        # Negative change in wait time -> positive reward
        reward = -wait_time_change

        # Normalize reward to reasonable scale
        # Typical wait time changes can be in the range of 0-100+ seconds
        reward = reward / 10.0  # Scale down for stability

        return reward

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
