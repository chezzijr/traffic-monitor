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
        self._green_phases: list[int] = []
        self._yellow_duration: int = 4
        self._current_green_phase: int = 0
        self.max_green: int = 50
        self._time_since_last_phase_change: int = 0
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

    def _initialize_spaces(self) -> None:
        """Initialize action and observation spaces from SUMO."""
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

        green_indices = [
            i for i, p in enumerate(phases)
            if 'G' in p.state or 'g' in p.state
        ]
        self._green_phases = green_indices if green_indices else [0]

        # Yellow duration from first yellow phase
        for p in phases:
            if 'y' in p.state:
                self._yellow_duration = max(int(float(p.duration)), 1)
                break

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
            f"Env initialized: {num_lanes} lanes, {self._num_phases} total phases, "
            f"{num_green} green phases {self._green_phases}, "
            f"yellow_dur={self._yellow_duration}s, obs_dim={obs_dim}"
        )

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

        # Initialize to first green phase
        conn = self._get_conn()
        self._current_green_phase = self._green_phases[0]
        conn.trafficlight.setPhase(self.tl_id, self._current_green_phase)

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

        # Translate green-index to SUMO phase with yellow transition
        desired_green = self._green_phases[int(action)]

        # max_green enforcement: force next phase if held too long
        if (
            self._time_since_last_phase_change >= self.max_green
            and desired_green == self._current_green_phase
        ):
            current_idx = self._green_phases.index(self._current_green_phase)
            desired_green = self._green_phases[(current_idx + 1) % len(self._green_phases)]

        if desired_green != self._current_green_phase:
            yellow_idx = (self._current_green_phase + 1) % self._num_phases
            conn.trafficlight.setPhase(self.tl_id, yellow_idx)
            for _ in range(self._yellow_duration):
                conn.simulationStep()
                self._current_step += 1
            self._time_since_last_phase_change = 0

        # Set desired green phase
        conn.trafficlight.setPhase(self.tl_id, desired_green)
        self._current_green_phase = desired_green

        # Advance simulation, collecting halting counts for reward averaging
        sub_step_halting: list[list[int]] = []
        for _ in range(self.steps_per_action):
            conn.simulationStep()
            self._current_step += 1
            self._time_since_last_phase_change += 1
            halting = [
                conn.lane.getLastStepHaltingNumber(lane)
                for lane in self._controlled_lanes
            ]
            sub_step_halting.append(halting)

        # Compute reward averaged over all sub-steps (LibSignal pattern)
        if sub_step_halting and sub_step_halting[0]:
            avg_halting = [
                float(np.mean([step[i] for step in sub_step_halting]))
                for i in range(len(sub_step_halting[0]))
            ]
            if self.algorithm.lower() == "dqn":
                reward = -float(np.mean(avg_halting)) * 12.0
            else:
                # PPO: use waiting time based reward
                lane_vehicle_ids = []
                for lane in self._controlled_lanes:
                    lane_vehicle_ids.extend(conn.lane.getLastStepVehicleIDs(lane))
                waiting_times = [
                    conn.vehicle.getWaitingTime(vid) for vid in lane_vehicle_ids
                ]
                mean_wait = float(np.mean(waiting_times)) if waiting_times else 0.0
                reward = float(np.clip(-mean_wait / 224.0, -4.0, 4.0))
        else:
            reward = 0.0

        observation = self._get_observation()

        terminated = False
        truncated = self._current_step >= self.max_steps

        # Collect info metrics
        total_vehicles = conn.vehicle.getIDCount()
        total_waiting = sum(
            conn.vehicle.getWaitingTime(vid) for vid in conn.vehicle.getIDList()
        )
        avg_waiting = total_waiting / max(total_vehicles, 1)
        queue_length = sum(
            conn.lane.getLastStepHaltingNumber(lane) for lane in self._controlled_lanes
        )

        info = {
            "step": self._current_step,
            "action": action,
            "total_vehicles": total_vehicles,
            "avg_waiting_time": avg_waiting,
            "avg_queue_length": queue_length / max(len(self._controlled_lanes), 1),
            "throughput": conn.simulation.getArrivedNumber(),
        }

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

        # Green phase one-hot
        num_green = len(self._green_phases)
        phase_one_hot = np.zeros(num_green, dtype=np.float32)
        try:
            green_idx = self._green_phases.index(self._current_green_phase)
            phase_one_hot[green_idx] = 1.0
        except ValueError:
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
