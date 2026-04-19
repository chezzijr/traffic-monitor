"""Multi-agent environment v2 for N traffic lights sharing one SUMO instance.

Aligned with SUMO-RL's proven patterns: per-signal state tracking, explicit
yellow-state construction, min/max green enforcement, diff-waiting-time reward,
and normalized observations (density + queue).

NOT a gym.Env subclass. Returns dicts keyed by tl_id.
"""

import logging
import os
from pathlib import Path
from typing import Any

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from app.ml._sumo_compat import get_traci as _get_traci

logger = logging.getLogger(__name__)

MIN_GAP = 2.5  # SUMO default minimum gap between vehicles


class _TrafficSignal:
    """Per-signal state tracker (SUMO-RL pattern)."""

    __slots__ = (
        "tl_id",
        "green_phases",
        "yellow_dict",
        "green_phase",
        "time_since_last_phase_change",
        "is_yellow",
        "_yellow_timer",
        "_target_green_idx",
        "last_total_waiting",
        "lanes",
        "lanes_length",
        "_vehicles",
    )

    def __init__(
        self,
        tl_id: str,
        green_phases: list,
        yellow_dict: dict[tuple[int, int], str],
        lanes: list[str],
        lanes_length: dict[str, float],
    ) -> None:
        self.tl_id = tl_id
        self.green_phases = green_phases          # list of phase objects with .state
        self.yellow_dict = yellow_dict            # (i,j) -> yellow state string
        self.green_phase: int = 0                 # index into green_phases
        self.time_since_last_phase_change: float = 0.0
        self.is_yellow: bool = False
        self._yellow_timer: int = 0
        self._target_green_idx: int = 0
        self.last_total_waiting: float = 0.0
        self.lanes = lanes
        self.lanes_length = lanes_length
        self._vehicles: dict[str, float] = {}     # veh_id -> accumulated waiting


class MultiAgentTrafficLightEnvV2:
    """Multi-agent environment v2: N traffic lights sharing one SUMO instance.

    NOT a gym.Env subclass. Returns dicts keyed by tl_id.

    Key differences from v1:
    - Per-signal state tracking with explicit yellow state construction
    - min_green / max_green enforcement
    - Diff-waiting-time reward (SUMO-RL)
    - Normalized observations: phase one-hot, min_green flag, lane density, lane queue
    - setRedYellowGreenState() instead of setPhase()
    """

    def __init__(
        self,
        network_path: str,
        network_id: str,
        tl_ids: list[str],
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
        self.network_path = network_path
        self.network_id = network_id
        self.tl_ids = tl_ids
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
        self._sumo_running: bool = False
        self._conn_label = f"multi_v2_{network_id}_{id(self)}"
        self._is_initialized: bool = False

        # Per-signal trackers (populated on first reset)
        self._signals: dict[str, _TrafficSignal] = {}
        self.observation_spaces: dict[str, spaces.Box] = {}
        self.action_spaces: dict[str, spaces.Discrete] = {}

    # ------------------------------------------------------------------
    # SUMO lifecycle (reused from v1)
    # ------------------------------------------------------------------

    def _start_sumo(self, seed: int | None = None) -> None:
        traci = _get_traci()
        self._stop_sumo()

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
            "--ignore-route-errors", "true",
        ]
        if seed is not None:
            sumo_cmd.extend(["--seed", str(seed)])

        traci.start(sumo_cmd, label=self._conn_label)
        self._sumo_running = True

    def _stop_sumo(self) -> None:
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
        traci = _get_traci()
        return traci.getConnection(self._conn_label)

    # ------------------------------------------------------------------
    # Initialization: build per-signal data structures
    # ------------------------------------------------------------------

    def _initialize(self) -> None:
        conn = self._get_conn()

        for tl_id in self.tl_ids:
            # Deduplicated controlled lanes
            raw_lanes = list(conn.trafficlight.getControlledLanes(tl_id))
            seen: set[str] = set()
            unique_lanes: list[str] = []
            for lane in raw_lanes:
                if lane not in seen:
                    seen.add(lane)
                    unique_lanes.append(lane)

            # Lane lengths for normalization
            lanes_length: dict[str, float] = {}
            for lane in unique_lanes:
                try:
                    lanes_length[lane] = conn.lane.getLength(lane)
                except Exception:
                    lanes_length[lane] = 100.0  # fallback

            # Extract green phases from program logics
            logics = conn.trafficlight.getAllProgramLogics(tl_id)
            all_phases = logics[0].phases if logics else []
            green_phases = [
                p for p in all_phases
                if "G" in p.state or "g" in p.state
            ]
            if not green_phases:
                # Fallback: treat all phases as green
                green_phases = list(all_phases) if all_phases else []

            # Build pairwise yellow states for ALL green->green transitions
            yellow_dict: dict[tuple[int, int], str] = {}
            for i, phase_i in enumerate(green_phases):
                for j, phase_j in enumerate(green_phases):
                    if i == j:
                        continue
                    yellow_state = ""
                    for s_i, s_j in zip(phase_i.state, phase_j.state):
                        if s_i in ("G", "g") and s_j in ("r", "s"):
                            yellow_state += "y"
                        else:
                            yellow_state += s_i
                    yellow_dict[(i, j)] = yellow_state

            signal = _TrafficSignal(
                tl_id=tl_id,
                green_phases=green_phases,
                yellow_dict=yellow_dict,
                lanes=unique_lanes,
                lanes_length=lanes_length,
            )
            self._signals[tl_id] = signal

            # Spaces
            num_green = len(green_phases)
            num_lanes = len(unique_lanes)
            # obs: phase_one_hot (num_green) + min_green_flag (1) + density (num_lanes) + queue (num_lanes)
            obs_dim = num_green + 1 + 2 * num_lanes
            self.observation_spaces[tl_id] = spaces.Box(
                low=0.0, high=1.0, shape=(obs_dim,), dtype=np.float32,
            )
            self.action_spaces[tl_id] = spaces.Discrete(num_green)

        self._is_initialized = True

        # Diagnostic logging
        for tl_id in self.tl_ids:
            sig = self._signals[tl_id]
            logger.info(
                f"[DIAG] TL {tl_id}: {len(sig.green_phases)} green phases, "
                f"{len(sig.lanes)} lanes, "
                f"{len(sig.yellow_dict)} yellow transitions"
            )
        logger.info(f"Multi-agent env v2 initialized: {len(self.tl_ids)} agents")

    # ------------------------------------------------------------------
    # Phase management helpers
    # ------------------------------------------------------------------

    def _set_next_phase(self, tl_id: str, action: int) -> None:
        """Apply an action (green phase index) to a signal.

        Enforces min_green: if time since last change < min_green, action is
        ignored (keeps current green). Otherwise, if action differs from
        current green, start yellow transition.
        """
        conn = self._get_conn()
        sig = self._signals[tl_id]

        new_green_idx = int(action)

        if sig.is_yellow:
            # Currently in yellow -- ignore new action, yellow will resolve itself
            return

        # min_green enforcement: ignore change if too soon
        if sig.time_since_last_phase_change < self.min_green:
            return

        # max_green enforcement is handled in _advance_time

        if new_green_idx == sig.green_phase:
            # Same phase, no change needed
            return

        # Start yellow transition
        yellow_key = (sig.green_phase, new_green_idx)
        yellow_state = sig.yellow_dict.get(yellow_key)
        if yellow_state is not None:
            conn.trafficlight.setRedYellowGreenState(tl_id, yellow_state)
        sig.is_yellow = True
        sig._yellow_timer = self.yellow_time
        sig._target_green_idx = new_green_idx
        sig.time_since_last_phase_change = 0.0

    def _force_next_phase(self, tl_id: str) -> None:
        """Force a phase change when max_green is exceeded.

        Cycles to the next green phase index.
        """
        conn = self._get_conn()
        sig = self._signals[tl_id]

        if sig.is_yellow or len(sig.green_phases) <= 1:
            return

        next_green_idx = (sig.green_phase + 1) % len(sig.green_phases)
        yellow_key = (sig.green_phase, next_green_idx)
        yellow_state = sig.yellow_dict.get(yellow_key)
        if yellow_state is not None:
            conn.trafficlight.setRedYellowGreenState(tl_id, yellow_state)
        sig.is_yellow = True
        sig._yellow_timer = self.yellow_time
        sig._target_green_idx = next_green_idx
        sig.time_since_last_phase_change = 0.0

    def _advance_one_second(self) -> None:
        """Advance SUMO by one second and update per-signal timers."""
        conn = self._get_conn()
        conn.simulationStep()
        self._sim_step += 1

        for tl_id in self.tl_ids:
            sig = self._signals[tl_id]
            sig.time_since_last_phase_change += 1.0

            if sig.is_yellow:
                sig._yellow_timer -= 1
                if sig._yellow_timer <= 0:
                    # Yellow expired: set the target green phase
                    sig.is_yellow = False
                    sig.green_phase = sig._target_green_idx
                    green_state = sig.green_phases[sig.green_phase].state
                    conn.trafficlight.setRedYellowGreenState(tl_id, green_state)
                    sig.time_since_last_phase_change = 0.0
            else:
                # max_green enforcement
                if sig.time_since_last_phase_change >= self.max_green:
                    self._force_next_phase(tl_id)

    # ------------------------------------------------------------------
    # Observations
    # ------------------------------------------------------------------

    def _get_observation(self, tl_id: str) -> np.ndarray:
        """Per-signal observation: [phase_one_hot, min_green_flag, lane_density, lane_queue].

        All values in [0, 1].
        """
        conn = self._get_conn()
        sig = self._signals[tl_id]

        num_green = len(sig.green_phases)
        num_lanes = len(sig.lanes)

        # Phase one-hot
        phase_one_hot = np.zeros(num_green, dtype=np.float32)
        phase_one_hot[sig.green_phase] = 1.0

        # Min-green flag: 1 if min_green elapsed (agent CAN switch), 0 if locked
        min_green_flag = np.array(
            [1.0 if sig.time_since_last_phase_change >= self.min_green else 0.0],
            dtype=np.float32,
        )

        # Lane density: num_vehicles / (lane_length / MIN_GAP)
        density = np.zeros(num_lanes, dtype=np.float32)
        for i, lane in enumerate(sig.lanes):
            try:
                num_veh = conn.lane.getLastStepVehicleNumber(lane)
                max_capacity = sig.lanes_length[lane] / (MIN_GAP + 5.0)
                density[i] = min(num_veh / max(max_capacity, 1.0), 1.0)
            except Exception:
                density[i] = 0.0

        # Lane queue: halting_vehicles / (lane_length / MIN_GAP)
        queue = np.zeros(num_lanes, dtype=np.float32)
        for i, lane in enumerate(sig.lanes):
            try:
                halting = conn.lane.getLastStepHaltingNumber(lane)
                max_capacity = sig.lanes_length[lane] / (MIN_GAP + 5.0)
                queue[i] = min(halting / max(max_capacity, 1.0), 1.0)
            except Exception:
                queue[i] = 0.0

        return np.concatenate([phase_one_hot, min_green_flag, density, queue])

    # ------------------------------------------------------------------
    # Reward
    # ------------------------------------------------------------------

    def _compute_reward(self, tl_id: str) -> float:
        """Diff-waiting-time reward (SUMO-RL pattern).

        reward = last_total_waiting - current_total_waiting
        """
        conn = self._get_conn()
        sig = self._signals[tl_id]

        # Update per-vehicle waiting times
        current_vehicles: set[str] = set()
        for lane in sig.lanes:
            try:
                veh_ids = conn.lane.getLastStepVehicleIDs(lane)
            except Exception:
                veh_ids = []
            for vid in veh_ids:
                current_vehicles.add(vid)
                try:
                    wait = conn.vehicle.getAccumulatedWaitingTime(vid)
                except Exception:
                    wait = 0.0
                sig._vehicles[vid] = wait

        # Remove vehicles that have left
        departed = set(sig._vehicles.keys()) - current_vehicles
        for vid in departed:
            del sig._vehicles[vid]

        # Sum accumulated waiting across all tracked vehicles
        current_waiting = sum(sig._vehicles.values()) / 100.0

        reward = sig.last_total_waiting - current_waiting
        sig.last_total_waiting = current_waiting

        return reward

    # ------------------------------------------------------------------
    # Reset / Step
    # ------------------------------------------------------------------

    def reset(self, seed: int | None = None) -> dict[str, np.ndarray]:
        self._start_sumo(seed=seed)

        if not self._is_initialized:
            self._initialize()

        self._sim_step = 0

        # Reset per-signal state
        conn = self._get_conn()
        for tl_id in self.tl_ids:
            sig = self._signals[tl_id]
            sig.green_phase = 0
            sig.time_since_last_phase_change = 0.0
            sig.is_yellow = False
            sig._yellow_timer = 0
            sig._target_green_idx = 0
            sig.last_total_waiting = 0.0
            sig._vehicles.clear()

            # Set initial green phase via state string
            green_state = sig.green_phases[0].state
            conn.trafficlight.setRedYellowGreenState(tl_id, green_state)

        observations: dict[str, np.ndarray] = {}
        for tl_id in self.tl_ids:
            observations[tl_id] = self._get_observation(tl_id)

        return observations

    def step(
        self, actions: dict[str, int]
    ) -> tuple[
        dict[str, np.ndarray],
        dict[str, float],
        dict[str, bool],
        dict[str, bool],
        dict[str, dict[str, Any]],
    ]:
        """Execute one environment step.

        1. Apply actions via set_next_phase() for each signal
        2. Advance SUMO by delta_time seconds (1 second at a time)
           During each second: track yellow countdown, time_since_last_phase_change
           When yellow timer expires, set the target green phase
        3. Compute observations, rewards, infos for each signal
        """
        # 1. Apply actions
        for tl_id, action in actions.items():
            self._set_next_phase(tl_id, action)

        # 2. Advance SUMO by delta_time seconds, one second at a time
        for _ in range(self.delta_time):
            self._advance_one_second()

        # 3. Compute observations, rewards, terminateds, truncateds, infos
        observations: dict[str, np.ndarray] = {}
        rewards: dict[str, float] = {}
        terminateds: dict[str, bool] = {}
        truncateds: dict[str, bool] = {}
        infos: dict[str, dict[str, Any]] = {}

        truncated = self._sim_step >= self.num_seconds

        # Diagnostic logging every 500 sim steps
        if self._sim_step % 500 == 0:
            conn = self._get_conn()
            total_vehicles = conn.vehicle.getIDCount()
            per_tl_info: dict[str, str] = {}
            for tl_id in self.tl_ids:
                sig = self._signals[tl_id]
                tl_veh_count = sum(
                    conn.lane.getLastStepVehicleNumber(lane)
                    for lane in sig.lanes
                )
                tl_halt_count = sum(
                    conn.lane.getLastStepHaltingNumber(lane)
                    for lane in sig.lanes
                )
                per_tl_info[tl_id] = f"{tl_veh_count}({tl_halt_count}halting)"
            logger.info(
                f"[DIAG] sim_step={self._sim_step}, "
                f"total_vehicles={total_vehicles}, "
                f"per_tl={per_tl_info}"
            )

        for tl_id in self.tl_ids:
            observations[tl_id] = self._get_observation(tl_id)
            rewards[tl_id] = self._compute_reward(tl_id)
            terminateds[tl_id] = False
            truncateds[tl_id] = truncated

            sig = self._signals[tl_id]
            conn = self._get_conn()

            # Info: per-agent metrics
            lane_vehicle_ids: list[str] = []
            for lane in sig.lanes:
                try:
                    lane_vehicle_ids.extend(conn.lane.getLastStepVehicleIDs(lane))
                except Exception:
                    pass
            waiting_time = sum(
                conn.vehicle.getWaitingTime(vid) for vid in lane_vehicle_ids
            )
            num_vehicles = len(lane_vehicle_ids)
            queue_length = sum(
                conn.lane.getLastStepHaltingNumber(lane)
                for lane in sig.lanes
            )

            infos[tl_id] = {
                "step": self._sim_step,
                "action": actions.get(tl_id, 0),
                "avg_waiting_time": waiting_time / max(num_vehicles, 1),
                "avg_queue_length": queue_length / max(len(sig.lanes), 1),
                "throughput": conn.simulation.getArrivedNumber(),
                "reward": rewards[tl_id],
            }

        return observations, rewards, terminateds, truncateds, infos

    def close(self) -> None:
        self._stop_sumo()
        self._is_initialized = False


class SingleAgentEnvAdapter(gym.Env):
    """Stub gym.Env for SB3 model construction only.

    Copies observation/action spaces from MultiAgentTrafficLightEnvV2 for a
    specific tl_id. step() and reset() raise NotImplementedError.
    """

    def __init__(self, multi_env: MultiAgentTrafficLightEnvV2, tl_id: str):
        super().__init__()
        self.observation_space = multi_env.observation_spaces[tl_id]
        self.action_space = multi_env.action_spaces[tl_id]
        self.tl_id = tl_id

    def reset(self, **kwargs):
        raise NotImplementedError("SingleAgentEnvAdapter is for model construction only")

    def step(self, action):
        raise NotImplementedError("SingleAgentEnvAdapter is for model construction only")
