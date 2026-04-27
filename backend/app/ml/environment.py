"""Gymnasium environment for traffic light optimization using SUMO."""

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


class TrafficLightEnv(gym.Env):
    """Gymnasium environment for single traffic light optimization.

    Action space restricted to green phases only. Yellow transitions are
    automatically inserted when switching between green phases.

    Observation: [lane_vehicle_counts..., green_phase_one_hot...]
    Action: Discrete(num_green_phases) - select next green phase
    Reward: Algorithm-specific, averaged over action interval sub-steps
    """

    metadata = {"render_modes": ["human"]}

    def __init__(
        self,
        network_path: str,
        network_id: str,
        tl_id: str,
        algorithm: str = "dqn",
        max_steps: int = 3600,
        steps_per_action: int = 10,
        yellow_time: int = 2,
        min_green: int = 10,
        gui: bool = False,
        routes_path: str | None = None,
        scenario: str = "moderate",
    ) -> None:
        super().__init__()

        self.network_path = network_path
        self.network_id = network_id
        self.tl_id = tl_id
        self.algorithm = algorithm
        self.max_steps = max_steps
        self.steps_per_action = steps_per_action
        self.gui = gui
        self.routes_path = routes_path
        self.scenario = scenario

        self._current_step = 0
        self._controlled_lanes: list[str] = []
        self._num_phases = 0
        self._green_phases: list[int] = []  # Indices into _full_phases (0..N-1)
        self._yellow_time: int = yellow_time
        self._yellow_duration: int = yellow_time
        self._yellow_dict: dict[str, int] = {}  # "i_j" -> phase index in _full_phases
        self._full_phases: list = []  # Green phases + generated yellow phases
        self._current_green_idx: int = 0  # Index into _green_phases (0-based)
        self.max_green: int = 50
        self.min_green: int = min_green
        self._time_since_last_phase_change: int = 0
        self._cumulative_throughput: int = 0
        self._cumulative_waiting: float = 0.0
        self._cumulative_queue: float = 0.0
        self._num_info_steps: int = 0
        self._cached_routes_path: str | None = None
        self._is_initialized = False
        self._sumo_running = False
        self._conn_label = f"train_{tl_id}_{id(self)}"

        # Placeholder spaces - updated after first reset
        self.action_space = spaces.Discrete(4)
        self.observation_space = spaces.Box(
            low=0.0, high=np.inf, shape=(1,), dtype=np.float32,
        )

    def _start_sumo(self, seed: int | None = None) -> None:
        """Start a SUMO instance owned by this environment."""
        traci = _get_traci()

        # Stop existing connection if any
        self._stop_sumo()

        # Generate routes once and cache, or reuse explicit routes_path
        routes_path = self.routes_path
        if routes_path is None:
            if self._cached_routes_path is None:
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
                route_result = route_service.generate_junction_routes(
                    network_path=self.network_path,
                    tl_id=self.tl_id,
                    output_dir=output_dir,
                    scenario=scenario_enum,
                    duration=self.max_steps,
                    seed=seed,
                )
                self._cached_routes_path = route_result["routes_path"]
            routes_path = self._cached_routes_path

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
            # Skip vehicles whose trip couldn't be routed instead of aborting
            # the entire run. randomTrips/duarouter occasionally emit
            # unroutable trips on dense networks; without this flag a single
            # unroutable motorbike crashes the whole training episode.
            "--ignore-route-errors", "true",
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

    def _create_yellows(self, green_phase_objects: list) -> list:
        """Create yellow transition phases between all pairs of green phases.

        Ported from LibSignal's Intersection.create_yellows() pattern.
        For each pair of green phases (i, j) where i != j, build a yellow
        string: for each signal position, if phase_i has G/g and phase_j has
        r/s, output 'r'; else keep phase_i's character.

        Returns the full phase list: green phases + generated yellow phases.
        """
        traci = _get_traci()
        full_phases = list(green_phase_objects)
        self._yellow_dict = {}

        num_greens = len(green_phase_objects)
        if num_greens <= 1:
            logger.debug(f"TL {self.tl_id}: only {num_greens} green phase(s), no yellows needed")
            return full_phases

        for i in range(num_greens):
            for j in range(num_greens):
                if i == j:
                    continue
                state_i = green_phase_objects[i].state
                state_j = green_phase_objects[j].state
                yellow_str = ""
                need_yellow = False
                for pos in range(len(state_i)):
                    if state_i[pos] in ('G', 'g') and state_j[pos] in ('r', 's'):
                        yellow_str += 'r'  # LibSignal uses 'r' for transitioning signals
                        need_yellow = True
                    else:
                        yellow_str += state_i[pos]

                if need_yellow:
                    new_idx = len(full_phases)
                    yellow_phase = traci.trafficlight.Phase(
                        self._yellow_duration, yellow_str
                    )
                    full_phases.append(yellow_phase)
                    self._yellow_dict[f"{i}_{j}"] = new_idx

        logger.debug(
            f"TL {self.tl_id}: created {len(self._yellow_dict)} yellow transitions, "
            f"yellow_dict={self._yellow_dict}"
        )
        return full_phases

    def _initialize_spaces(self) -> None:
        """Initialize action and observation spaces from SUMO."""
        traci = _get_traci()
        conn = self._get_conn()

        # Get controlled lanes (deduplicated)
        raw_lanes = list(conn.trafficlight.getControlledLanes(self.tl_id))
        seen = set()
        unique_lanes = []
        for lane in raw_lanes:
            if lane not in seen:
                seen.add(lane)
                unique_lanes.append(lane)
        self._controlled_lanes = unique_lanes

        # Get phases and identify green-only phases
        logics = conn.trafficlight.getAllProgramLogics(self.tl_id)
        phases = logics[0].phases if logics else []
        self._num_phases = len(phases) if phases else 4

        green_phase_objects = [
            p for p in phases
            if 'G' in p.state or 'g' in p.state
        ]
        if not green_phase_objects:
            # Fallback: use all phases if no green phases found
            green_phase_objects = list(phases) if phases else []

        # Yellow duration from constructor parameter (default 2s, matching V2)
        self._yellow_duration = self._yellow_time

        # Build full phase list: greens (0..N-1) + generated yellows (N..M)
        self._full_phases = self._create_yellows(green_phase_objects)

        # _green_phases stores indices into _full_phases (0..N-1)
        self._green_phases = list(range(len(green_phase_objects)))

        # Install as new SUMO program
        rl_logic = traci.trafficlight.Logic(
            f"{self.tl_id}_rl", 0, 0, self._full_phases
        )
        conn.trafficlight.setProgramLogic(self.tl_id, rl_logic)
        conn.trafficlight.setProgram(self.tl_id, f"{self.tl_id}_rl")

        # Action space = green phases only
        num_green = len(self._green_phases)
        num_lanes = len(self._controlled_lanes)
        obs_dim = num_lanes + num_green

        self.action_space = spaces.Discrete(num_green)
        self.observation_space = spaces.Box(
            low=0.0, high=np.inf, shape=(obs_dim,), dtype=np.float32,
        )

        self._is_initialized = True
        logger.info(
            f"Env initialized: {num_lanes} lanes, {self._num_phases} original phases, "
            f"{num_green} green phases (indices {self._green_phases}), "
            f"{len(self._yellow_dict)} yellow transitions, "
            f"yellow_dur={self._yellow_duration}s, obs_dim={obs_dim}, "
            f"full_phases={len(self._full_phases)} total"
        )
        logger.debug(f"TL {self.tl_id} yellow_dict: {self._yellow_dict}")
        for i, p in enumerate(self._full_phases):
            logger.debug(f"  full_phase[{i}]: state={p.state}, dur={p.duration}")

    def reset(
        self,
        *,
        seed: int | None = None,
        options: dict[str, Any] | None = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        super().reset(seed=seed)

        self._start_sumo(seed=seed)

        if not self._is_initialized:
            self._initialize_spaces()

        self._current_step = 0
        self._time_since_last_phase_change = 0
        self._cumulative_throughput = 0
        self._cumulative_waiting = 0.0
        self._cumulative_queue = 0.0
        self._num_info_steps = 0

        # Re-install RL program (SUMO was restarted, so the program is gone)
        conn = self._get_conn()
        if self._full_phases:
            traci = _get_traci()
            rl_logic = traci.trafficlight.Logic(
                f"{self.tl_id}_rl", 0, 0, self._full_phases
            )
            conn.trafficlight.setProgramLogic(self.tl_id, rl_logic)
            conn.trafficlight.setProgram(self.tl_id, f"{self.tl_id}_rl")
        conn.trafficlight.setPhase(self.tl_id, 0)  # First green phase = index 0 in _full_phases
        self._current_green_idx = 0

        observation = self._get_observation()
        info = {
            "step": self._current_step,
            "tl_id": self.tl_id,
            "num_lanes": len(self._controlled_lanes),
            "num_phases": len(self._green_phases),
        }
        return observation, info

    def step(self, action: int) -> tuple[np.ndarray, float, bool, bool, dict[str, Any]]:
        conn = self._get_conn()

        # desired_green_idx is the index into _green_phases (0-based)
        desired_green_idx = int(action)

        # max_green enforcement: force next phase if held too long
        if (
            self._time_since_last_phase_change >= self.max_green
            and desired_green_idx == self._current_green_idx
        ):
            desired_green_idx = (self._current_green_idx + 1) % len(self._green_phases)

        # min_green enforcement: ignore switch if green too short
        if (
            desired_green_idx != self._current_green_idx
            and self._time_since_last_phase_change < self.min_green
        ):
            desired_green_idx = self._current_green_idx

        if desired_green_idx != self._current_green_idx:
            # Yellow transition using LibSignal pattern
            y_key = f"{self._current_green_idx}_{desired_green_idx}"
            if y_key in self._yellow_dict:
                conn.trafficlight.setPhase(self.tl_id, self._yellow_dict[y_key])
                logger.debug(
                    f"TL {self.tl_id}: yellow transition {y_key} -> "
                    f"phase {self._yellow_dict[y_key]}"
                )
            for _ in range(self._yellow_duration):
                conn.simulationStep()
                self._current_step += 1
                self._cumulative_throughput += conn.simulation.getArrivedNumber()
            self._time_since_last_phase_change = 0

        # Set desired green phase (green phases occupy indices 0..N-1 in _full_phases)
        sumo_phase_idx = self._green_phases[desired_green_idx]
        conn.trafficlight.setPhase(self.tl_id, sumo_phase_idx)
        logger.debug(
            f"TL {self.tl_id}: green phase idx={desired_green_idx} -> "
            f"SUMO phase={sumo_phase_idx}"
        )
        self._current_green_idx = desired_green_idx

        # Advance simulation, collecting halting counts for reward averaging
        sub_step_halting: list[list[int]] = []
        for _ in range(self.steps_per_action):
            conn.simulationStep()
            self._current_step += 1
            self._time_since_last_phase_change += 1
            self._cumulative_throughput += conn.simulation.getArrivedNumber()
            halting = [
                conn.lane.getLastStepHaltingNumber(lane)
                for lane in self._controlled_lanes
            ]
            sub_step_halting.append(halting)

        # Compute reward averaged over all sub-steps (LibSignal pattern)
        # Same reward for all algorithms: -mean(halting) * 12.0
        if sub_step_halting and sub_step_halting[0]:
            avg_halting = [
                float(np.mean([step[i] for step in sub_step_halting]))
                for i in range(len(sub_step_halting[0]))
            ]
            reward = -float(np.mean(avg_halting)) * 12.0
        else:
            reward = 0.0

        observation = self._get_observation()

        terminated = False
        truncated = self._current_step >= self.max_steps

        # Collect junction-specific metrics (controlled lanes only)
        junction_vids = []
        for lane in self._controlled_lanes:
            junction_vids.extend(conn.lane.getLastStepVehicleIDs(lane))
        junction_waiting = sum(conn.vehicle.getWaitingTime(v) for v in junction_vids)
        avg_waiting = junction_waiting / max(len(junction_vids), 1)
        queue_length = sum(
            conn.lane.getLastStepHaltingNumber(lane) for lane in self._controlled_lanes
        )

        # Accumulate for episode-level averages
        self._cumulative_waiting += avg_waiting
        self._cumulative_queue += queue_length / max(len(self._controlled_lanes), 1)
        self._num_info_steps += 1

        info = {
            "step": self._current_step,
            "action": action,
            "junction_vehicles": len(junction_vids),
            "avg_waiting_time": self._cumulative_waiting / max(self._num_info_steps, 1),
            "avg_queue_length": self._cumulative_queue / max(self._num_info_steps, 1),
            "throughput": self._cumulative_throughput,
        }

        # Periodic debug logging every 100 sim steps
        if self._current_step % 100 == 0:
            logger.debug(
                f"[DIAG] TL {self.tl_id}: sim_step={self._current_step}, "
                f"junction_veh={len(junction_vids)}, halting={queue_length}, "
                f"green_idx={self._current_green_idx}, reward={reward:.2f}"
            )

        return observation, reward, terminated, truncated, info

    def _get_observation(self) -> np.ndarray:
        """Observation: [lane_vehicle_counts, green_phase_one_hot]."""
        conn = self._get_conn()

        vehicle_counts = []
        for lane_id in self._controlled_lanes:
            try:
                count = conn.lane.getLastStepVehicleNumber(lane_id)
                vehicle_counts.append(float(count))
            except Exception:
                vehicle_counts.append(0.0)

        # Green phase one-hot using _current_green_idx (index into _green_phases)
        num_green = len(self._green_phases)
        phase_one_hot = np.zeros(num_green, dtype=np.float32)
        if 0 <= self._current_green_idx < num_green:
            phase_one_hot[self._current_green_idx] = 1.0
        else:
            phase_one_hot[0] = 1.0

        return np.concatenate([
            np.array(vehicle_counts, dtype=np.float32),
            phase_one_hot,
        ])

    def render(self) -> None:
        pass

    def close(self) -> None:
        self._stop_sumo()
        self._is_initialized = False


class MultiScenarioEnvWrapper(gym.Wrapper):
    """Wraps TrafficLightEnv to rotate traffic scenarios across episodes.

    Modes:
    - round_robin: Cycles through scenarios sequentially
    - random: Picks a random scenario each episode
    - curriculum: Progresses from light to rush_hour (50 episodes per level)
    """

    def __init__(
        self,
        env: TrafficLightEnv,
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
        self.env.unwrapped._cached_routes_path = None

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
