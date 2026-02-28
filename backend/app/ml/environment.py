"""Gymnasium environment for traffic light optimization using SUMO."""

import logging
import os
import random
from pathlib import Path
from typing import Any

import gymnasium as gym
import numpy as np
from gymnasium import spaces

logger = logging.getLogger(__name__)

# Lazy import traci
_traci = None

def _get_traci():
    global _traci
    if _traci is None:
        try:
            import traci
            _traci = traci
        except ImportError:
            raise RuntimeError("SUMO TraCI not available. Set SUMO_HOME.")
    return _traci


class TrafficLightEnv(gym.Env):
    """Gymnasium environment for single traffic light optimization.

    Observation: [lane_vehicle_counts..., phase_one_hot...]
    Action: Discrete(num_phases) - select next traffic light phase
    Reward: Algorithm-specific via rewards.py
    """

    metadata = {"render_modes": ["human"]}

    def __init__(
        self,
        network_path: str,
        network_id: str,
        tl_id: str,
        algorithm: str = "dqn",
        max_steps: int = 3600,
        steps_per_action: int = 5,
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

        # Get controlled lanes
        self._controlled_lanes = list(conn.trafficlight.getControlledLanes(self.tl_id))
        # Remove duplicates while preserving order
        seen = set()
        unique_lanes = []
        for lane in self._controlled_lanes:
            if lane not in seen:
                seen.add(lane)
                unique_lanes.append(lane)
        self._controlled_lanes = unique_lanes

        # Get number of phases
        logics = conn.trafficlight.getAllProgramLogics(self.tl_id)
        self._num_phases = len(logics[0].phases) if logics else 4

        # Action space
        self.action_space = spaces.Discrete(self._num_phases)

        # Observation: lane_vehicle_counts + phase_one_hot
        num_lanes = len(self._controlled_lanes)
        obs_dim = num_lanes + self._num_phases
        self.observation_space = spaces.Box(
            low=0.0, high=np.inf, shape=(obs_dim,), dtype=np.float32,
        )

        self._is_initialized = True
        logger.info(
            f"Env initialized: {num_lanes} lanes, {self._num_phases} phases, obs_dim={obs_dim}"
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

        observation = self._get_observation()
        info = {
            "step": self._current_step,
            "tl_id": self.tl_id,
            "num_lanes": len(self._controlled_lanes),
            "num_phases": self._num_phases,
        }
        return observation, info

    def step(self, action: int) -> tuple[np.ndarray, float, bool, bool, dict[str, Any]]:
        conn = self._get_conn()

        # Set traffic light phase
        conn.trafficlight.setPhase(self.tl_id, int(action))

        # Advance simulation
        for _ in range(self.steps_per_action):
            conn.simulationStep()
            self._current_step += 1

        # Compute reward using rewards.py
        from app.ml.rewards import compute_reward
        reward = compute_reward(self.algorithm, self._controlled_lanes, conn)

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
        """Observation: [lane_vehicle_counts, phase_one_hot]."""
        conn = self._get_conn()

        # Lane vehicle counts (NOT halting, NOT waiting times)
        vehicle_counts = []
        for lane_id in self._controlled_lanes:
            try:
                count = conn.lane.getLastStepVehicleNumber(lane_id)
                vehicle_counts.append(float(count))
            except Exception:
                vehicle_counts.append(0.0)

        # Phase one-hot
        try:
            current_phase = conn.trafficlight.getPhase(self.tl_id)
        except Exception:
            current_phase = 0
        phase_one_hot = np.zeros(self._num_phases, dtype=np.float32)
        if 0 <= current_phase < self._num_phases:
            phase_one_hot[current_phase] = 1.0

        observation = np.concatenate([
            np.array(vehicle_counts, dtype=np.float32),
            phase_one_hot,
        ])
        return observation

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
        if self.mode == "round_robin":
            scenario = self.scenarios[self._scenario_index % len(self.scenarios)]
            self._scenario_index += 1
            return scenario
        elif self.mode == "random":
            return random.choice(self.scenarios)
        elif self.mode == "curriculum":
            level = min(
                self._episode_count // self.curriculum_threshold,
                len(self.scenarios) - 1,
            )
            return self.scenarios[level]
        return self.scenarios[0]
