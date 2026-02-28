"""Multi-agent environment for N traffic lights sharing one SUMO instance."""

import logging
import os
from pathlib import Path
from typing import Any

import gymnasium as gym
import numpy as np
from gymnasium import spaces

logger = logging.getLogger(__name__)

from app.ml._sumo_compat import get_traci as _get_traci


class MultiAgentTrafficLightEnv:
    """Multi-agent environment: N traffic lights sharing one SUMO instance.

    NOT a gym.Env subclass. Returns dicts keyed by tl_id.
    """

    def __init__(
        self,
        network_path: str,
        network_id: str,
        tl_ids: list[str],
        algorithm: str = "dqn",
        max_steps: int = 3600,
        steps_per_action: int = 5,
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

        # Per-agent data (populated after first reset)
        self._controlled_lanes: dict[str, list[str]] = {}
        self._num_phases: dict[str, int] = {}
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

            # Get phases
            logics = conn.trafficlight.getAllProgramLogics(tl_id)
            num_phases = len(logics[0].phases) if logics else 4
            self._num_phases[tl_id] = num_phases

            # Observation/action spaces
            num_lanes = len(unique_lanes)
            obs_dim = num_lanes + num_phases
            self.observation_spaces[tl_id] = spaces.Box(
                low=0.0, high=np.inf, shape=(obs_dim,), dtype=np.float32,
            )
            self.action_spaces[tl_id] = spaces.Discrete(num_phases)

        self._is_initialized = True
        logger.info(f"Multi-agent env initialized: {len(self.tl_ids)} agents")

    def reset(self, seed: int | None = None) -> dict[str, np.ndarray]:
        self._start_sumo(seed=seed)

        if not self._is_initialized:
            self._initialize()

        self._current_step = 0

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

        # Set all traffic light phases simultaneously
        for tl_id, action in actions.items():
            conn.trafficlight.setPhase(tl_id, int(action))

        # Advance simulation
        for _ in range(self.steps_per_action):
            conn.simulationStep()
            self._current_step += 1

        # Compute per-agent results
        from app.ml.rewards import compute_reward

        observations = {}
        rewards = {}
        terminateds = {}
        truncateds = {}
        infos = {}

        truncated = self._current_step >= self.max_steps

        for tl_id in self.tl_ids:
            observations[tl_id] = self._get_observation(tl_id)
            rewards[tl_id] = compute_reward(
                self.algorithm, self._controlled_lanes[tl_id], conn
            )
            terminateds[tl_id] = False
            truncateds[tl_id] = truncated

            queue_length = sum(
                conn.lane.getLastStepHaltingNumber(lane)
                for lane in self._controlled_lanes[tl_id]
            )
            infos[tl_id] = {
                "step": self._current_step,
                "action": actions.get(tl_id, 0),
                "avg_queue_length": queue_length / max(len(self._controlled_lanes[tl_id]), 1),
                "throughput": conn.simulation.getArrivedNumber(),
            }

        return observations, rewards, terminateds, truncateds, infos

    def _get_observation(self, tl_id: str) -> np.ndarray:
        """Per-agent observation: [lane_vehicle_counts, phase_one_hot]."""
        conn = self._get_conn()

        vehicle_counts = []
        for lane_id in self._controlled_lanes[tl_id]:
            try:
                count = conn.lane.getLastStepVehicleNumber(lane_id)
                vehicle_counts.append(float(count))
            except Exception:
                vehicle_counts.append(0.0)

        try:
            current_phase = conn.trafficlight.getPhase(tl_id)
        except Exception:
            current_phase = 0

        num_phases = self._num_phases[tl_id]
        phase_one_hot = np.zeros(num_phases, dtype=np.float32)
        if 0 <= current_phase < num_phases:
            phase_one_hot[current_phase] = 1.0

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
