"""Gymnasium environment (v2) for single traffic light RL optimization using SUMO.

Aligned with SUMO-RL's proven patterns:
- Discrete(num_green_phases) action space
- Pairwise yellow transitions for all green->green pairs
- diff-waiting-time reward
- Normalized observation with density, queue, phase one-hot, and min_green flag
"""

import logging
import os
import random
from pathlib import Path
from typing import Any

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from app.ml._sumo_compat import get_traci as _get_traci

logger = logging.getLogger(__name__)

MIN_GAP = 2.5  # SUMO default minimum gap between vehicles (meters)


class TrafficLightEnvV2(gym.Env):
    """Gymnasium environment for single traffic light optimization (v2).

    Follows SUMO-RL patterns:
    - Action: Discrete(num_green_phases) - select which green phase to activate
    - Observation: [phase_one_hot, min_green_flag, lane_density, lane_queue]
    - Reward: diff-waiting-time (change in accumulated waiting time)
    - Yellow transitions: pairwise for ALL green->green pairs
    """

    metadata = {"render_modes": ["human"]}

    def __init__(
        self,
        network_path: str,
        network_id: str,
        tl_id: str,
        algorithm: str = "dqn",
        num_seconds: int = 3600,
        delta_time: int = 5,
        yellow_time: int = 2,
        min_green: int = 10,
        max_green: int = 50,
        gui: bool = False,
        routes_path: str | None = None,
        scenario: str = "moderate",
    ) -> None:
        super().__init__()

        self.network_path = network_path
        self.network_id = network_id
        self.tl_id = tl_id
        self.algorithm = algorithm
        self.num_seconds = num_seconds
        self.delta_time = delta_time
        self.yellow_time = yellow_time
        self.min_green = min_green
        self.max_green = max_green
        self.gui = gui
        self.routes_path = routes_path
        self.scenario = scenario

        self._sim_step: int = 0
        self._step_count: int = 0
        self._controlled_lanes: list[str] = []
        self._green_phases: list[str] = []  # state strings for each green phase
        self._num_green: int = 0
        self._num_lanes: int = 0
        self._lane_lengths: dict[str, float] = {}
        self._lane_capacities: dict[str, float] = {}  # max vehicles per lane

        # Phase management
        self._current_phase_index: int = 0  # index into self._green_phases
        self._is_yellow: bool = False
        self._time_since_last_phase_change: int = 0
        self._next_phase_index: int = 0  # target green phase after yellow
        self.yellow_dict: dict[tuple[int, int], str] = {}

        # Reward tracking
        self._last_total_waiting: float = 0.0
        self._vehicles: dict[str, dict[str, float]] = {}  # {lane: {vid: acc_wait}}

        self._is_initialized: bool = False
        self._sumo_running: bool = False
        self._conn_label: str = f"train_v2_{tl_id}_{id(self)}"

        # Placeholder spaces - updated after first reset
        self.action_space = spaces.Discrete(4)
        self.observation_space = spaces.Box(
            low=0.0, high=1.0, shape=(1,), dtype=np.float32,
        )

    # ------------------------------------------------------------------
    # SUMO lifecycle
    # ------------------------------------------------------------------

    def _start_sumo(self, seed: int | None = None) -> None:
        """Start a SUMO instance owned by this environment."""
        traci = _get_traci()

        # Stop existing connection if any
        self._stop_sumo()

        # Generate routes if needed
        routes_path = self.routes_path
        if routes_path is None:
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

        sumo_binary = os.path.join(
            os.environ.get("SUMO_HOME", "/usr/share/sumo"),
            "bin",
            "sumo-gui" if self.gui else "sumo",
        )
        sumo_cmd = [
            sumo_binary,
            "-n", self.network_path,
            "-r", routes_path,
            "--no-step-log", "true",
            "--waiting-time-memory", "1000",
            "--no-warnings", "true",
        ]
        if seed is not None:
            sumo_cmd.extend(["--seed", str(seed)])

        traci.start(sumo_cmd, label=self._conn_label)
        self._sumo_running = True

    def _stop_sumo(self) -> None:
        """Stop the SUMO instance."""
        if not self._sumo_running:
            return
        try:
            traci = _get_traci()
            conn = traci.getConnection(self._conn_label)
            conn.close()
        except Exception:
            pass
        self._sumo_running = False

    def _get_conn(self):
        """Get the TraCI connection for this environment."""
        traci = _get_traci()
        return traci.getConnection(self._conn_label)

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def _initialize(self) -> None:
        """Initialize spaces, green phases, yellow dict from SUMO."""
        conn = self._get_conn()

        # Get controlled lanes (deduplicated, preserving order)
        raw_lanes = list(conn.trafficlight.getControlledLanes(self.tl_id))
        seen: set[str] = set()
        unique_lanes: list[str] = []
        for lane in raw_lanes:
            if lane not in seen:
                seen.add(lane)
                unique_lanes.append(lane)
        self._controlled_lanes = unique_lanes
        self._num_lanes = len(unique_lanes)

        # Cache lane lengths and capacities
        for lane_id in self._controlled_lanes:
            length = conn.lane.getLength(lane_id)
            self._lane_lengths[lane_id] = length
            # Approximate max vehicles: lane_length / (MIN_GAP + avg_vehicle_length)
            # Use SUMO default vehicle length ~5m as approximation
            avg_vehicle_length = 5.0
            self._lane_capacities[lane_id] = length / (MIN_GAP + avg_vehicle_length)

        # Extract green phases from SUMO program logics
        logics = conn.trafficlight.getAllProgramLogics(self.tl_id)
        all_phases = logics[0].phases if logics else []

        self._green_phases = []
        for phase in all_phases:
            if "G" in phase.state or "g" in phase.state:
                self._green_phases.append(phase.state)

        if not self._green_phases:
            # Fallback: use first phase
            if all_phases:
                self._green_phases = [all_phases[0].state]
            else:
                self._green_phases = ["G" * self._num_lanes]

        self._num_green = len(self._green_phases)

        # Build pairwise yellow states for ALL green->green transitions
        self.yellow_dict = {}
        for i in range(self._num_green):
            for j in range(self._num_green):
                if i == j:
                    continue
                green_i = self._green_phases[i]
                green_j = self._green_phases[j]
                yellow_state = []
                for s in range(len(green_i)):
                    char_i = green_i[s]
                    char_j = green_j[s]
                    # If current green has G/g and target has r/s at this position, set yellow
                    if char_i in ("G", "g") and char_j in ("r", "s"):
                        yellow_state.append("y")
                    else:
                        yellow_state.append(char_i)
                self.yellow_dict[(i, j)] = "".join(yellow_state)

        # Define spaces
        # Observation: [phase_one_hot(num_green), min_green_flag(1),
        #               lane_density(num_lanes), lane_queue(num_lanes)]
        obs_dim = self._num_green + 1 + 2 * self._num_lanes
        self.action_space = spaces.Discrete(self._num_green)
        self.observation_space = spaces.Box(
            low=0.0, high=1.0, shape=(obs_dim,), dtype=np.float32,
        )

        self._is_initialized = True

        logger.info(
            f"[V2] TL {self.tl_id}: {self._num_lanes} lanes, {self._num_green} green phases, "
            f"yellow_time={self.yellow_time}s, min_green={self.min_green}s, max_green={self.max_green}s"
        )

    # ------------------------------------------------------------------
    # Phase management
    # ------------------------------------------------------------------

    def _set_next_phase(self, new_phase: int) -> None:
        """Handle phase switching with max_green enforcement and yellow transitions.

        Args:
            new_phase: Index into self._green_phases for the desired green phase.
        """
        conn = self._get_conn()

        # 1. max_green enforcement: if at max_green and agent wants to keep current, force change
        if (
            self._time_since_last_phase_change >= self.max_green
            and new_phase == self._current_phase_index
        ):
            new_phase = (self._current_phase_index + 1) % self._num_green
            logger.info(f"[V2-MAXGREEN] {self.tl_id}: forced switch after {self.max_green}s")

        # 2. If same phase or not enough time elapsed: re-assert current green, ignore change
        if (
            new_phase == self._current_phase_index
            or self._time_since_last_phase_change < self.yellow_time + self.min_green
        ):
            conn.trafficlight.setRedYellowGreenState(
                self.tl_id, self._green_phases[self._current_phase_index]
            )
            return

        # 3. Initiate yellow transition
        logger.debug(
            f"[V2-PHASE] {self.tl_id}: phase {self._current_phase_index} -> {new_phase} "
            f"(held {self._time_since_last_phase_change}s)"
        )
        yellow_state = self.yellow_dict.get(
            (self._current_phase_index, new_phase),
            self._green_phases[self._current_phase_index],
        )
        conn.trafficlight.setRedYellowGreenState(self.tl_id, yellow_state)
        self._next_phase_index = new_phase
        self._is_yellow = True
        self._time_since_last_phase_change = 0

    # ------------------------------------------------------------------
    # Observation
    # ------------------------------------------------------------------

    def _get_observation(self) -> np.ndarray:
        """Build normalized observation vector.

        Components:
        - Phase one-hot: current green phase (num_green)
        - min_green flag: 1 if time >= min_green + yellow_time, else 0 (1)
        - Lane density per lane: normalized vehicle count (num_lanes)
        - Lane queue per lane: normalized halting count (num_lanes)
        """
        conn = self._get_conn()

        # Phase one-hot
        phase_one_hot = np.zeros(self._num_green, dtype=np.float32)
        phase_one_hot[self._current_phase_index] = 1.0

        # min_green flag
        min_green_flag = np.array(
            [1.0 if self._time_since_last_phase_change >= self.min_green + self.yellow_time else 0.0],
            dtype=np.float32,
        )

        # Lane density and queue
        lane_density = np.zeros(self._num_lanes, dtype=np.float32)
        lane_queue = np.zeros(self._num_lanes, dtype=np.float32)

        for i, lane_id in enumerate(self._controlled_lanes):
            capacity = self._lane_capacities.get(lane_id, 1.0)
            if capacity <= 0:
                capacity = 1.0

            try:
                num_vehicles = conn.lane.getLastStepVehicleNumber(lane_id)
                lane_density[i] = min(1.0, num_vehicles / capacity)
            except Exception:
                lane_density[i] = 0.0

            try:
                halting = conn.lane.getLastStepHaltingNumber(lane_id)
                lane_queue[i] = min(1.0, halting / capacity)
            except Exception:
                lane_queue[i] = 0.0

        return np.concatenate([phase_one_hot, min_green_flag, lane_density, lane_queue])

    # ------------------------------------------------------------------
    # Reward (diff-waiting-time)
    # ------------------------------------------------------------------

    def _get_accumulated_waiting_time_per_lane(self) -> list[float]:
        """Get accumulated waiting time per controlled lane.

        Tracks per-vehicle waiting per lane to avoid double-counting
        when vehicles move between lanes.
        """
        conn = self._get_conn()
        waiting_per_lane: list[float] = []

        for lane_id in self._controlled_lanes:
            lane_vehicles: dict[str, float] = {}
            try:
                vehicle_ids = conn.lane.getLastStepVehicleIDs(lane_id)
                for vid in vehicle_ids:
                    acc_wait = conn.vehicle.getAccumulatedWaitingTime(vid)
                    lane_vehicles[vid] = acc_wait
            except Exception:
                pass

            # Update tracked vehicles for this lane
            self._vehicles[lane_id] = lane_vehicles
            waiting_per_lane.append(sum(lane_vehicles.values()))

        return waiting_per_lane

    def _compute_reward(self) -> float:
        """Diff-waiting-time reward: improvement in total waiting time."""
        current_waiting = sum(self._get_accumulated_waiting_time_per_lane()) / 100.0
        reward = self._last_total_waiting - current_waiting
        self._last_total_waiting = current_waiting
        return reward

    # ------------------------------------------------------------------
    # Core Gymnasium interface
    # ------------------------------------------------------------------

    def reset(
        self,
        *,
        seed: int | None = None,
        options: dict[str, Any] | None = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        super().reset(seed=seed)

        self._start_sumo(seed=seed)

        if not self._is_initialized:
            self._initialize()

        # Reset state
        self._sim_step = 0
        self._step_count = 0
        self._current_phase_index = 0
        self._is_yellow = False
        self._time_since_last_phase_change = 0
        self._next_phase_index = 0
        self._last_total_waiting = 0.0
        self._vehicles = {}

        # Set initial green phase
        conn = self._get_conn()
        conn.trafficlight.setRedYellowGreenState(
            self.tl_id, self._green_phases[0]
        )

        observation = self._get_observation()
        info = {
            "step": self._sim_step,
            "tl_id": self.tl_id,
            "num_lanes": self._num_lanes,
            "num_phases": self._num_green,
        }
        return observation, info

    def step(
        self, action: int
    ) -> tuple[np.ndarray, float, bool, bool, dict[str, Any]]:
        conn = self._get_conn()

        # Request phase change (handles yellow transition, min/max green)
        self._set_next_phase(int(action))

        # Advance simulation by delta_time seconds, one second at a time
        for _ in range(self.delta_time):
            conn.simulationStep()
            self._sim_step += 1
            self._time_since_last_phase_change += 1

            # During yellow phase, count down then switch to target green
            if self._is_yellow:
                if self._time_since_last_phase_change >= self.yellow_time:
                    # Yellow phase complete: switch to target green
                    conn.trafficlight.setRedYellowGreenState(
                        self.tl_id, self._green_phases[self._next_phase_index]
                    )
                    self._current_phase_index = self._next_phase_index
                    self._is_yellow = False

        # Compute observation, reward, and info at the END of the delta_time loop
        observation = self._get_observation()
        reward = self._compute_reward()

        self._step_count += 1

        # Periodic diagnostic logging
        if self._step_count % 100 == 0:
            total_v = conn.vehicle.getIDCount()
            logger.info(
                f"[V2-STEP] rl_step={self._step_count}, sim={self._sim_step}s, "
                f"phase={self._current_phase_index}, held={self._time_since_last_phase_change}s, "
                f"yellow={self._is_yellow}, reward={reward:.3f}, vehicles={total_v}"
            )

        terminated = False
        truncated = self._sim_step >= self.num_seconds

        # Collect info metrics
        total_vehicles = conn.vehicle.getIDCount()
        total_waiting = sum(
            conn.vehicle.getWaitingTime(vid) for vid in conn.vehicle.getIDList()
        )
        avg_waiting = total_waiting / max(total_vehicles, 1)
        queue_length = sum(
            conn.lane.getLastStepHaltingNumber(lane)
            for lane in self._controlled_lanes
        )

        info = {
            "step": self._sim_step,
            "action": action,
            "avg_waiting_time": avg_waiting,
            "avg_queue_length": queue_length / max(self._num_lanes, 1),
            "throughput": conn.simulation.getArrivedNumber(),
            "reward": reward,
        }

        return observation, reward, terminated, truncated, info

    def render(self) -> None:
        pass

    def close(self) -> None:
        self._stop_sumo()
        self._is_initialized = False
        self._sim_step = 0
        self._current_phase_index = 0
        self._is_yellow = False
        self._time_since_last_phase_change = 0
        self._last_total_waiting = 0.0
        self._vehicles = {}


class MultiScenarioEnvWrapper(gym.Wrapper):
    """Wraps TrafficLightEnvV2 to rotate traffic scenarios across episodes.

    Modes:
    - round_robin: Cycles through scenarios sequentially
    - random: Picks a random scenario each episode
    - curriculum: Progresses from light to rush_hour (50 episodes per level)
    """

    def __init__(
        self,
        env: TrafficLightEnvV2,
        mode: str = "round_robin",
        scenarios: list[str] | None = None,
        curriculum_threshold: int = 50,
    ):
        super().__init__(env)
        self.mode = mode
        self.scenarios = scenarios or ["light", "moderate", "heavy", "rush_hour"]
        self.curriculum_threshold = curriculum_threshold
        self._episode_count = 0
        self._scenario_index = 0

    def reset(self, **kwargs) -> tuple[np.ndarray, dict[str, Any]]:
        # Select next scenario
        scenario = self._select_scenario()
        self.env.unwrapped.scenario = scenario
        self.env.unwrapped.routes_path = None  # Force re-generation

        self._episode_count += 1
        obs, info = self.env.reset(**kwargs)
        info["scenario"] = scenario
        return obs, info

    def _select_scenario(self) -> str:
        if self.mode == "random":
            return random.choice(self.scenarios)
        elif self.mode == "curriculum":
            level = min(
                self._episode_count // self.curriculum_threshold,
                len(self.scenarios) - 1,
            )
            return self.scenarios[level]
        else:
            scenario = self.scenarios[self._scenario_index]
            self._scenario_index = (self._scenario_index + 1) % len(self.scenarios)
            return scenario
