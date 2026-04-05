"""Multi-agent environment for CoLight: N intersections, one SUMO instance, graph topology."""

import logging
import os
import sys
from pathlib import Path

import numpy as np

from app.ml._sumo_compat import get_traci as _get_traci

logger = logging.getLogger(__name__)


class CoLightEnv:
    """Multi-agent environment for CoLight: N intersections, one SUMO instance, graph topology.

    NOT a gym.Env subclass. Manages N traffic lights in a single SUMO simulation
    with graph-based adjacency for CoLight's attention mechanism.

    Observation per TL: normalized lane vehicle counts (LibSignal CoLight, phase=False), padded to ob_length.
    Action per TL: int index selecting a green phase.
    Reward per TL: -mean(halting_over_substeps) * 12.0 (LibSignal unified reward).
    """

    def __init__(
        self,
        network_path: str,
        network_id: str,
        tl_ids: list[str],
        max_steps: int = 3600,
        steps_per_action: int = 10,
        yellow_time: int = 2,
        vehicle_max: float = 1.0,
        gui: bool = False,
        routes_path: str | None = None,
        scenario: str = "moderate",
    ):
        self.network_path = network_path
        self.network_id = network_id
        self.tl_ids = tl_ids
        self.max_steps = max_steps
        self.steps_per_action = steps_per_action
        self.gui = gui
        self.routes_path = routes_path
        self.scenario = scenario

        self._yellow_time = yellow_time
        self._vehicle_max = vehicle_max
        self._current_step = 0

        # Per-intersection state (populated by _initialize)
        self._controlled_lanes: dict[str, list[str]] = {}
        self._green_phases: dict[str, list[int]] = {}
        self._yellow_dicts: dict[str, dict[str, int]] = {}
        self._full_phases: dict[str, list] = {}
        self._current_green_idx: dict[str, int] = {}

        # Graph data (populated by _initialize -> _build_graph)
        self.edge_index: np.ndarray = np.empty((2, 0), dtype=np.int64)
        self.node_id2idx: dict[str, int] = {}
        self.ob_length: int = 0
        self.phase_lengths: list[int] = []
        self.num_actions: int = 0

        # Cumulative metrics
        self._cumulative_throughput: int = 0
        self._cumulative_waiting: float = 0.0
        self._cumulative_queue: float = 0.0
        self._num_info_steps: int = 0

        self._cached_routes_path: str | None = None
        self._is_initialized = False
        self._sumo_running = False
        self._conn_label = f"colight_{network_id}_{id(self)}"

    # ------------------------------------------------------------------
    # Graph construction
    # ------------------------------------------------------------------

    def _build_graph(self) -> None:
        """Build adjacency between selected TLs using sumolib.

        Port of LibSignal's build_index_intersection_map_sumo, scoped to
        the selected tl_ids only.
        """
        sumo_home = os.environ.get("SUMO_HOME", "/usr/share/sumo")
        sumo_tools = os.path.join(sumo_home, "tools")
        if sumo_tools not in sys.path:
            sys.path.append(sumo_tools)
        import sumolib

        net = sumolib.net.readNet(self.network_path)

        # Build node_id2idx for selected TLs only
        self.node_id2idx = {tl_id: idx for idx, tl_id in enumerate(self.tl_ids)}

        def _strip_gs(node_id: str) -> str:
            return node_id[3:] if node_id.startswith("GS_") else node_id

        sparse_adj: list[list[int]] = []
        for edge in net.getEdges():
            from_id = _strip_gs(edge.getFromNode().getID())
            to_id = _strip_gs(edge.getToNode().getID())
            if from_id in self.node_id2idx and to_id in self.node_id2idx:
                sparse_adj.append([self.node_id2idx[from_id], self.node_id2idx[to_id]])

        if sparse_adj:
            self.edge_index = np.array(sparse_adj, dtype=np.int64).T
        else:
            self.edge_index = np.empty((2, 0), dtype=np.int64)
            logger.warning(
                "No edges found between selected TLs — intersections are disconnected. "
                "Self-loops will be added by the attention layer."
            )

        logger.info(
            f"Graph built: {len(self.tl_ids)} nodes, {self.edge_index.shape[1]} directed edges"
        )

    # ------------------------------------------------------------------
    # Yellow phase creation
    # ------------------------------------------------------------------

    def _create_yellows_for_tl(
        self, tl_id: str, green_phase_objects: list
    ) -> tuple[list, dict[str, int]]:
        """Create yellow transition phases between all pairs of green phases.

        Exact same logic as V1's TrafficLightEnv._create_yellows.
        Returns (full_phases_list, yellow_dict).
        """
        traci = _get_traci()
        full_phases = list(green_phase_objects)
        yellow_dict: dict[str, int] = {}

        num_greens = len(green_phase_objects)
        if num_greens <= 1:
            logger.debug(f"TL {tl_id}: only {num_greens} green phase(s), no yellows needed")
            return full_phases, yellow_dict

        for i in range(num_greens):
            for j in range(num_greens):
                if i == j:
                    continue
                state_i = green_phase_objects[i].state
                state_j = green_phase_objects[j].state
                yellow_str = ""
                need_yellow = False
                for pos in range(len(state_i)):
                    if state_i[pos] in ("G", "g") and state_j[pos] in ("r", "s"):
                        yellow_str += "r"
                        need_yellow = True
                    else:
                        yellow_str += state_i[pos]

                if need_yellow:
                    new_idx = len(full_phases)
                    yellow_phase = traci.trafficlight.Phase(self._yellow_time, yellow_str)
                    full_phases.append(yellow_phase)
                    yellow_dict[f"{i}_{j}"] = new_idx

        logger.debug(
            f"TL {tl_id}: created {len(yellow_dict)} yellow transitions, "
            f"yellow_dict={yellow_dict}"
        )
        return full_phases, yellow_dict

    # ------------------------------------------------------------------
    # Initialization (first reset only)
    # ------------------------------------------------------------------

    def _initialize(self) -> None:
        """Initialize per-intersection state from the running SUMO instance."""
        traci = _get_traci()
        conn = self._get_conn()

        for tl_id in self.tl_ids:
            # Deduplicated controlled lanes (same as V1 environment.py:207-214)
            raw_lanes = list(conn.trafficlight.getControlledLanes(tl_id))
            seen: set[str] = set()
            unique_lanes: list[str] = []
            for lane in raw_lanes:
                if lane not in seen:
                    seen.add(lane)
                    unique_lanes.append(lane)
            self._controlled_lanes[tl_id] = unique_lanes

            # Extract green phases (same as V1 environment.py:221-227)
            logics = conn.trafficlight.getAllProgramLogics(tl_id)
            phases = logics[0].phases if logics else []
            green_phase_objects = [p for p in phases if "G" in p.state or "g" in p.state]
            if not green_phase_objects:
                green_phase_objects = list(phases) if phases else []

            # Create yellows
            full_phases, yellow_dict = self._create_yellows_for_tl(tl_id, green_phase_objects)
            self._full_phases[tl_id] = full_phases
            self._yellow_dicts[tl_id] = yellow_dict
            self._green_phases[tl_id] = list(range(len(green_phase_objects)))

            # Install RL program (same as V1 environment.py:239-243)
            rl_logic = traci.trafficlight.Logic(
                f"{tl_id}_rl", 0, 0, full_phases
            )
            conn.trafficlight.setProgramLogic(tl_id, rl_logic)
            conn.trafficlight.setProgram(tl_id, f"{tl_id}_rl")

            # Initialize counters
            self._current_green_idx[tl_id] = 0

            logger.info(
                f"TL {tl_id}: {len(unique_lanes)} lanes, "
                f"{len(green_phase_objects)} green phases, "
                f"{len(yellow_dict)} yellow transitions, "
                f"{len(full_phases)} total phases"
            )

        # Compute observation / action dimensions
        # LibSignal CoLight observation = lane vehicle counts only (phase=False)
        self.ob_length = max(
            len(self._controlled_lanes[tl]) for tl in self.tl_ids
        )
        self.phase_lengths = [
            len(self._green_phases[tl])
            for tl in self.tl_ids  # ordered by node_id2idx (same order as tl_ids)
        ]
        self.num_actions = max(self.phase_lengths)

        # Build graph adjacency
        self._build_graph()

        self._is_initialized = True
        logger.info(
            f"CoLightEnv initialized: {len(self.tl_ids)} TLs, "
            f"ob_length={self.ob_length}, num_actions={self.num_actions}, "
            f"phase_lengths={self.phase_lengths}, "
            f"edge_index shape={self.edge_index.shape}"
        )

    # ------------------------------------------------------------------
    # SUMO lifecycle
    # ------------------------------------------------------------------

    def _start_sumo(self, seed: int | None = None) -> None:
        """Start a SUMO instance owned by this environment."""
        traci = _get_traci()
        self._stop_sumo()

        # Resolve routes
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
                route_result = route_service.generate_routes(
                    network_path=self.network_path,
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
    # Observation helpers
    # ------------------------------------------------------------------

    def _get_observation(self, tl_id: str) -> np.ndarray:
        """CoLight observation: normalized lane vehicle counts, padded to ob_length.

        Matches LibSignal colight.yml (phase=False, vehicle_max normalized).
        """
        conn = self._get_conn()

        vehicle_counts: list[float] = []
        for lane_id in self._controlled_lanes[tl_id]:
            try:
                count = conn.lane.getLastStepVehicleNumber(lane_id)
                vehicle_counts.append(float(count))
            except Exception:
                vehicle_counts.append(0.0)

        raw_obs = np.array(vehicle_counts, dtype=np.float32) / self._vehicle_max

        # Pad to ob_length
        if len(raw_obs) < self.ob_length:
            raw_obs = np.concatenate([
                raw_obs,
                np.zeros(self.ob_length - len(raw_obs), dtype=np.float32),
            ])

        return raw_obs

    def _get_all_observations(self) -> np.ndarray:
        """Stack per-TL observations in node index order -> [N, ob_length]."""
        obs_list = [self._get_observation(tl_id) for tl_id in self.tl_ids]
        return np.stack(obs_list, axis=0)

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def reset(self, seed: int | None = None) -> np.ndarray:
        """Reset the environment and return initial observations [N, ob_length]."""
        self._start_sumo(seed=seed)

        if not self._is_initialized:
            self._initialize()

        # Re-install RL programs (SUMO restart loses custom programs)
        traci = _get_traci()
        conn = self._get_conn()
        for tl_id in self.tl_ids:
            if self._full_phases[tl_id]:
                rl_logic = traci.trafficlight.Logic(
                    f"{tl_id}_rl", 0, 0, self._full_phases[tl_id]
                )
                conn.trafficlight.setProgramLogic(tl_id, rl_logic)
                conn.trafficlight.setProgram(tl_id, f"{tl_id}_rl")
            conn.trafficlight.setPhase(tl_id, 0)
            self._current_green_idx[tl_id] = 0

        self._current_step = 0
        self._cumulative_throughput = 0
        self._cumulative_waiting = 0.0
        self._cumulative_queue = 0.0
        self._num_info_steps = 0

        return self._get_all_observations()

    def step(
        self, actions: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray, bool, dict]:
        """Advance the environment by one decision step for all intersections.

        Args:
            actions: [N] int array, one action per intersection (green phase index).

        Returns:
            observations: [N, ob_length] float array.
            rewards: [N] float array.
            done: bool, True when max_steps reached.
            info: dict with aggregated metrics.
        """
        conn = self._get_conn()

        n = len(self.tl_ids)
        desired_green: dict[str, int] = {}
        needs_yellow: dict[str, bool] = {}

        # Phase 1: Determine desired green index per TL
        # LibSignal CoLight lets the agent freely switch phases (no min/max green).
        for i, tl_id in enumerate(self.tl_ids):
            action = int(actions[i])
            # Clamp action to valid range for this TL
            num_green = len(self._green_phases[tl_id])
            action = action % num_green

            current_idx = self._current_green_idx[tl_id]
            desired_green[tl_id] = action
            needs_yellow[tl_id] = action != current_idx

        # Phase 2: Yellow transitions (shared simulation, all TLs advance together)
        any_yellow = any(needs_yellow.values())
        if any_yellow:
            # Set yellow phase for TLs that need it
            for tl_id in self.tl_ids:
                if needs_yellow[tl_id]:
                    current_idx = self._current_green_idx[tl_id]
                    y_key = f"{current_idx}_{desired_green[tl_id]}"
                    if y_key in self._yellow_dicts[tl_id]:
                        conn.trafficlight.setPhase(
                            tl_id, self._yellow_dicts[tl_id][y_key]
                        )

            # Advance simulation for yellow_time steps
            for _ in range(self._yellow_time):
                conn.simulationStep()
                self._current_step += 1
                self._cumulative_throughput += conn.simulation.getArrivedNumber()

        # Phase 3: Set green phases for all TLs
        for tl_id in self.tl_ids:
            sumo_phase_idx = self._green_phases[tl_id][desired_green[tl_id]]
            conn.trafficlight.setPhase(tl_id, sumo_phase_idx)
            self._current_green_idx[tl_id] = desired_green[tl_id]

        # Phase 4: Advance simulation for steps_per_action, collecting halting per TL
        # sub_step_halting[tl_id] = list of per-substep halting counts
        sub_step_halting: dict[str, list[int]] = {tl_id: [] for tl_id in self.tl_ids}
        for _ in range(self.steps_per_action):
            conn.simulationStep()
            self._current_step += 1
            self._cumulative_throughput += conn.simulation.getArrivedNumber()
            for tl_id in self.tl_ids:
                halting = sum(
                    conn.lane.getLastStepHaltingNumber(lane)
                    for lane in self._controlled_lanes[tl_id]
                )
                sub_step_halting[tl_id].append(halting)

        # Phase 5: Compute per-TL rewards
        rewards = np.zeros(n, dtype=np.float32)
        for i, tl_id in enumerate(self.tl_ids):
            counts = sub_step_halting[tl_id]
            if counts:
                avg_halting = float(np.mean(counts))
                rewards[i] = -avg_halting * 12.0
            else:
                rewards[i] = 0.0

        # Phase 6: Observations
        observations = self._get_all_observations()

        # Phase 7: Done check
        done = self._current_step >= self.max_steps

        # Phase 8: Info with per-TL and aggregated metrics
        per_tl_waiting: list[float] = []
        per_tl_queue: list[float] = []
        for tl_id in self.tl_ids:
            junction_vids: list[str] = []
            for lane in self._controlled_lanes[tl_id]:
                junction_vids.extend(conn.lane.getLastStepVehicleIDs(lane))
            waiting = sum(conn.vehicle.getWaitingTime(v) for v in junction_vids)
            avg_waiting = waiting / max(len(junction_vids), 1)
            per_tl_waiting.append(avg_waiting)

            queue = sum(
                conn.lane.getLastStepHaltingNumber(lane)
                for lane in self._controlled_lanes[tl_id]
            )
            per_tl_queue.append(queue / max(len(self._controlled_lanes[tl_id]), 1))

        self._cumulative_waiting += float(np.mean(per_tl_waiting)) if per_tl_waiting else 0.0
        self._cumulative_queue += float(np.mean(per_tl_queue)) if per_tl_queue else 0.0
        self._num_info_steps += 1

        info = {
            "step": self._current_step,
            "avg_waiting_time": self._cumulative_waiting / max(self._num_info_steps, 1),
            "avg_queue_length": self._cumulative_queue / max(self._num_info_steps, 1),
            "throughput": self._cumulative_throughput,
        }

        # Periodic debug logging
        if self._current_step % 100 == 0:
            logger.debug(
                f"[DIAG] CoLight step={self._current_step}, "
                f"mean_reward={float(np.mean(rewards)):.2f}, "
                f"throughput={self._cumulative_throughput}"
            )

        return observations, rewards, done, info

    def close(self) -> None:
        """Stop SUMO and reset initialization flag."""
        self._stop_sumo()
        self._is_initialized = False
