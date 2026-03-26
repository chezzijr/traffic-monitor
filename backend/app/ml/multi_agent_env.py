"""Multi-agent environment for N traffic lights sharing one SUMO instance."""

import logging
import os
from pathlib import Path
from typing import Any

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from app.ml._sumo_compat import get_traci as _get_traci

logger = logging.getLogger(__name__)


class MultiAgentTrafficLightEnv:
    """Multi-agent environment: N traffic lights sharing one SUMO instance.

    NOT a gym.Env subclass. Returns dicts keyed by tl_id.

    Action space restricted to green phases only. Yellow transitions are
    automatically inserted when switching between green phases.
    """

    def __init__(
        self,
        network_path: str,
        network_id: str,
        tl_ids: list[str],
        algorithm: str = "dqn",
        max_steps: int = 3600,
        steps_per_action: int = 10,
        yellow_time: int = 2,
        min_green: int = 10,
        gui: bool = False,
        routes_path: str | None = None,
        scenario: str = "moderate",
    ) -> None:
        self.network_path = network_path
        self.network_id = network_id
        self.tl_ids = tl_ids
        self.algorithm = algorithm
        self.max_steps = max_steps
        self.steps_per_action = steps_per_action
        self.gui = gui
        self.routes_path = routes_path
        self.scenario = scenario

        self._current_step = 0
        self._sumo_running = False
        self._conn_label = f"multi_{network_id}_{id(self)}"
        self._is_initialized = False
        self.yellow_time = yellow_time
        self.min_green = min_green

        # Per-agent data (populated after first reset)
        self._controlled_lanes: dict[str, list[str]] = {}
        self._num_phases: dict[str, int] = {}
        self._green_phases: dict[str, list[int]] = {}
        self._yellow_duration: dict[str, int] = {}
        self._current_green_phase: dict[str, int] = {}
        self.max_green: int = 50
        self._time_since_last_phase_change: dict[str, int] = {}
        self._seen_vehicle_ids: dict[str, set[str]] = {}
        self.observation_spaces: dict[str, spaces.Box] = {}
        self.action_spaces: dict[str, spaces.Discrete] = {}

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

    def _initialize(self) -> None:
        conn = self._get_conn()

        for tl_id in self.tl_ids:
            # Get controlled lanes (deduplicated)
            raw_lanes = list(conn.trafficlight.getControlledLanes(tl_id))
            seen = set()
            unique_lanes = []
            for lane in raw_lanes:
                if lane not in seen:
                    seen.add(lane)
                    unique_lanes.append(lane)
            self._controlled_lanes[tl_id] = unique_lanes

            # Get phases and identify green-only phases
            logics = conn.trafficlight.getAllProgramLogics(tl_id)
            phases = logics[0].phases if logics else []
            num_phases = len(phases) if phases else 4
            self._num_phases[tl_id] = num_phases

            # Green phases: those containing 'G' or 'g' in state string
            green_indices = [
                i for i, p in enumerate(phases)
                if 'G' in p.state or 'g' in p.state
            ]
            self._green_phases[tl_id] = green_indices if green_indices else [0]

            # Yellow duration from constructor parameter (default 2s)
            self._yellow_duration[tl_id] = self.yellow_time
            self._seen_vehicle_ids[tl_id] = set()

            # Action space = number of GREEN phases only
            num_green = len(self._green_phases[tl_id])
            num_lanes = len(unique_lanes)
            obs_dim = num_lanes + num_green
            self.observation_spaces[tl_id] = spaces.Box(
                low=0.0, high=np.inf, shape=(obs_dim,), dtype=np.float32,
            )
            self.action_spaces[tl_id] = spaces.Discrete(num_green)

        self._is_initialized = True
        for tl_id in self.tl_ids:
            logger.info(
                f"[DIAG] TL {tl_id}: {len(self._controlled_lanes[tl_id])} controlled lanes, "
                f"{self._num_phases[tl_id]} total phases, "
                f"{len(self._green_phases[tl_id])} green phases {self._green_phases[tl_id]}, "
                f"yellow_dur={self._yellow_duration[tl_id]}s"
            )
        logger.info(f"Multi-agent env initialized: {len(self.tl_ids)} agents")

    def reset(self, seed: int | None = None) -> dict[str, np.ndarray]:
        self._start_sumo(seed=seed)

        if not self._is_initialized:
            self._initialize()

        self._current_step = 0

        # Initialize each TL to its first green phase
        conn = self._get_conn()
        for tl_id in self.tl_ids:
            self._time_since_last_phase_change[tl_id] = 0
            self._seen_vehicle_ids[tl_id] = set()
            first_green = self._green_phases[tl_id][0]
            conn.trafficlight.setPhase(tl_id, first_green)
            self._current_green_phase[tl_id] = first_green

        observations = {}
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
        conn = self._get_conn()

        # Translate green-index actions and handle yellow transitions
        any_phase_changed = False
        desired_greens: dict[str, int] = {}
        for tl_id, action in actions.items():
            desired_green = self._green_phases[tl_id][int(action)]
            current_green = self._current_green_phase[tl_id]

            # max_green enforcement
            if (
                self._time_since_last_phase_change.get(tl_id, 0) >= self.max_green
                and desired_green == current_green
            ):
                current_idx = self._green_phases[tl_id].index(current_green)
                desired_green = self._green_phases[tl_id][
                    (current_idx + 1) % len(self._green_phases[tl_id])
                ]

            # min_green enforcement: ignore switch if green too short
            if (
                desired_green != current_green
                and self._time_since_last_phase_change.get(tl_id, 0) < self.min_green
            ):
                desired_green = current_green

            desired_greens[tl_id] = desired_green

            if desired_green != current_green:
                any_phase_changed = True
                # Insert yellow: phase immediately after current green (SUMO convention)
                yellow_idx = (current_green + 1) % self._num_phases[tl_id]
                conn.trafficlight.setPhase(tl_id, yellow_idx)

        # Run yellow duration if any phase changed
        if any_phase_changed:
            yellow_dur = max(
                self._yellow_duration[tl_id]
                for tl_id in actions
                if desired_greens[tl_id] != self._current_green_phase[tl_id]
            )
            for _ in range(yellow_dur):
                conn.simulationStep()
                self._current_step += 1

        # Set all desired green phases
        for tl_id in actions:
            if desired_greens[tl_id] != self._current_green_phase[tl_id]:
                self._time_since_last_phase_change[tl_id] = 0
            conn.trafficlight.setPhase(tl_id, desired_greens[tl_id])
            self._current_green_phase[tl_id] = desired_greens[tl_id]

        # Advance simulation, collecting halting counts for reward averaging
        sub_step_halting: dict[str, list[list[int]]] = {
            tl_id: [] for tl_id in self.tl_ids
        }
        for _ in range(self.steps_per_action):
            conn.simulationStep()
            self._current_step += 1
            for tl_id in self.tl_ids:
                self._time_since_last_phase_change[tl_id] = self._time_since_last_phase_change.get(tl_id, 0) + 1
            for tl_id in self.tl_ids:
                halting = [
                    conn.lane.getLastStepHaltingNumber(lane)
                    for lane in self._controlled_lanes[tl_id]
                ]
                sub_step_halting[tl_id].append(halting)

        observations = {}
        rewards = {}
        terminateds = {}
        truncateds = {}
        infos = {}

        truncated = self._current_step >= self.max_steps

        # Periodic diagnostic logging
        if self._current_step % 500 == 0:
            total_vehicles = conn.vehicle.getIDCount()
            per_tl_vehicles = {}
            for tl_id in self.tl_ids:
                tl_veh_count = sum(
                    conn.lane.getLastStepVehicleNumber(lane)
                    for lane in self._controlled_lanes[tl_id]
                )
                tl_halt_count = sum(
                    conn.lane.getLastStepHaltingNumber(lane)
                    for lane in self._controlled_lanes[tl_id]
                )
                per_tl_vehicles[tl_id] = f"{tl_veh_count}({tl_halt_count}halting)"
            logger.info(
                f"[DIAG] sim_step={self._current_step}, "
                f"total_vehicles={total_vehicles}, "
                f"per_tl={per_tl_vehicles}"
            )

        for tl_id in self.tl_ids:
            observations[tl_id] = self._get_observation(tl_id)

            # Compute reward averaged over all sub-steps (LibSignal pattern)
            all_halting = sub_step_halting[tl_id]
            if all_halting and all_halting[0]:
                avg_halting = [
                    float(np.mean([step[i] for step in all_halting]))
                    for i in range(len(all_halting[0]))
                ]
                rewards[tl_id] = -float(np.mean(avg_halting)) * 12.0
            else:
                rewards[tl_id] = 0.0

            terminateds[tl_id] = False
            truncateds[tl_id] = truncated

            # Per-agent waiting time from vehicles on controlled lanes
            lane_vehicle_ids = []
            for lane in self._controlled_lanes[tl_id]:
                lane_vehicle_ids.extend(conn.lane.getLastStepVehicleIDs(lane))
            waiting_time = sum(
                conn.vehicle.getWaitingTime(vid) for vid in lane_vehicle_ids
            )
            num_vehicles = len(lane_vehicle_ids)

            queue_length = sum(
                conn.lane.getLastStepHaltingNumber(lane)
                for lane in self._controlled_lanes[tl_id]
            )
            # Track unique vehicles served per junction
            self._seen_vehicle_ids[tl_id].update(lane_vehicle_ids)
            infos[tl_id] = {
                "step": self._current_step,
                "action": actions.get(tl_id, 0),
                "avg_waiting_time": waiting_time / max(num_vehicles, 1),
                "avg_queue_length": queue_length / max(len(self._controlled_lanes[tl_id]), 1),
                "throughput": len(self._seen_vehicle_ids[tl_id]),
                "reward": rewards[tl_id],
            }

        return observations, rewards, terminateds, truncateds, infos

    def _get_observation(self, tl_id: str) -> np.ndarray:
        """Per-agent observation: [lane_vehicle_counts, green_phase_one_hot]."""
        conn = self._get_conn()

        vehicle_counts = []
        for lane_id in self._controlled_lanes[tl_id]:
            try:
                count = conn.lane.getLastStepVehicleNumber(lane_id)
                vehicle_counts.append(float(count))
            except Exception:
                vehicle_counts.append(0.0)

        # One-hot for green phase index (not total phase index)
        green_phases = self._green_phases[tl_id]
        num_green = len(green_phases)
        phase_one_hot = np.zeros(num_green, dtype=np.float32)
        current_green = self._current_green_phase.get(tl_id, green_phases[0])
        try:
            green_idx = green_phases.index(current_green)
            phase_one_hot[green_idx] = 1.0
        except ValueError:
            phase_one_hot[0] = 1.0

        return np.concatenate([
            np.array(vehicle_counts, dtype=np.float32),
            phase_one_hot,
        ])

    def close(self) -> None:
        self._stop_sumo()
        self._is_initialized = False


class SingleAgentEnvAdapter(gym.Env):
    """Stub gym.Env for SB3 model construction only.

    Copies observation/action spaces from MultiAgentTrafficLightEnv for a
    specific tl_id. step() and reset() raise NotImplementedError.
    """

    def __init__(self, multi_env: MultiAgentTrafficLightEnv, tl_id: str):
        super().__init__()
        self.observation_space = multi_env.observation_spaces[tl_id]
        self.action_space = multi_env.action_spaces[tl_id]
        self.tl_id = tl_id

    def reset(self, **kwargs):
        raise NotImplementedError("SingleAgentEnvAdapter is for model construction only")

    def step(self, action):
        raise NotImplementedError("SingleAgentEnvAdapter is for model construction only")
