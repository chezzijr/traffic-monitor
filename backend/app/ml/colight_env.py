"""Multi-agent environment for CoLight: N intersections, one SUMO instance, graph topology."""

import logging
import os
import sys
from pathlib import Path

import numpy as np

from app.ml._sumo_compat import get_traci as _get_traci

logger = logging.getLogger(__name__)


# Track 1 (plan.md): duration-bucket action with cyclic phase advance.
# Action ∈ {0,1,2,3} → target green durations in sumo seconds. Phase always
# advances when its age reaches the bucket target → 2-phase TLs cannot
# starve (cycle is mandatory), and DQN argmax has 4 alternatives instead
# of 2 → less prone to extrapolation lock-in. Refs: Liang 2019
# (arxiv 1803.11115), GuideLight (arxiv 2407.10811).
DURATION_BUCKETS_SEC: tuple[int, ...] = (10, 20, 30, 40)


class CoLightEnv:
    """Multi-agent environment for CoLight: N intersections, one SUMO instance, graph topology.

    NOT a gym.Env subclass. Manages N traffic lights in a single SUMO simulation
    with graph-based adjacency for CoLight's attention mechanism.

    Observation per TL: [lane vehicle counts, phase one-hot, elapsed scalar].
    Action semantics depend on `action_mode`:
        - "duration" (Track 1, default): action = duration-bucket index. Phase
          cycles automatically; bucket selects how long the *current* green
          must persist before advancing to the next. 2-phase TLs cannot
          starve by construction.
        - "phase" (legacy): action = green phase index to switch to.
    Reward per TL: T2 intersection-level pressure — count of vehicles whose
    `getWaitingTime > 0` summed over all controlled in-lanes per intersection,
    mean over substeps, * -12 (LibSignal-aligned scaling, no clip).
    """

    def __init__(
        self,
        network_path: str,
        network_id: str,
        tl_ids: list[str],
        max_steps: int = 3600,
        steps_per_action: int = 15,
        yellow_time: int = 2,
        min_green: int = 15,
        vehicle_max: float = 20.0,
        gui: bool = False,
        routes_path: str | None = None,
        scenario: str = "moderate",
        action_mode: str = "duration",
    ):
        self.network_path = network_path
        self.network_id = network_id
        self.tl_ids = tl_ids
        self.max_steps = max_steps
        self.steps_per_action = steps_per_action
        self.min_green = min_green
        self.gui = gui
        self.routes_path = routes_path
        self.scenario = scenario
        if action_mode not in ("duration", "phase"):
            raise ValueError(
                f"action_mode must be 'duration' or 'phase', got {action_mode!r}"
            )
        self.action_mode = action_mode

        self._yellow_time = yellow_time
        self._vehicle_max = vehicle_max
        self._current_step = 0

        # Per-intersection state (populated by _initialize)
        self._controlled_lanes: dict[str, list[str]] = {}
        self._green_phases: dict[str, list[int]] = {}
        self._yellow_dicts: dict[str, dict[str, int]] = {}
        self._full_phases: dict[str, list] = {}
        self._current_green_idx: dict[str, int] = {}
        self._elapsed_in_green: dict[str, int] = {}

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
        """Build adjacency between selected TLs.

        Primary: multi-hop traversal via non-TL junctions (grey-dot SUMO nodes
        between signaled intersections). This recovers the *logical* adjacency
        a human sees on the map — the same algorithm as graph_service uses for
        cluster detection. Subset the full-network TL graph down to just the
        TLs the user selected.

        Fallback: if the primary pass leaves the graph sparse (< N edges for N
        nodes), pad with k-NN by Euclidean distance so CoLight's attention has
        real neighbors instead of collapsing to self-loops.
        """
        sumo_home = os.environ.get("SUMO_HOME", "/usr/share/sumo")
        sumo_tools = os.path.join(sumo_home, "tools")
        if sumo_tools not in sys.path:
            sys.path.append(sumo_tools)
        import sumolib

        from app.services.sumo_graph_utils import (
            parse_network,
            strip_gs,
            tl_neighbors_by_hop,
        )

        # Build node_id2idx for selected TLs only (in user-provided order)
        self.node_id2idx = {tl_id: idx for idx, tl_id in enumerate(self.tl_ids)}
        selected: set[str] = set(self.tl_ids)
        n = len(self.tl_ids)

        # Pass 1: hop-traversal adjacency, restricted to selected TLs
        tl_ids_all, junction_adj, _ = parse_network(self.network_path)
        edges: set[tuple[int, int]] = set()
        for tl_id in self.tl_ids:
            nbrs = tl_neighbors_by_hop(tl_id, tl_ids_all, junction_adj, max_hops=2)
            for nb in nbrs:
                if nb in selected and nb != tl_id:
                    i = self.node_id2idx[tl_id]
                    j = self.node_id2idx[nb]
                    edges.add((i, j))
                    edges.add((j, i))

        # Resolve coordinates via sumolib (stripped id first — geometric junction)
        net = sumolib.net.readNet(self.network_path)

        def _resolve_node(tl_id: str):
            stripped = strip_gs(tl_id)
            for candidate in (stripped, tl_id, f"GS_{stripped}"):
                try:
                    return net.getNode(candidate)
                except KeyError:
                    continue
            return None

        coords: list[tuple[float, float] | None] = []
        for tl_id in self.tl_ids:
            node = _resolve_node(tl_id)
            coords.append(node.getCoord() if node is not None else None)

        missing = [tl for tl, c in zip(self.tl_ids, coords) if c is None]
        if missing:
            logger.error(
                f"Could not resolve coordinates for {len(missing)}/{n} TL(s): {missing[:5]}. "
                "k-NN fallback will skip these — check .net.xml integrity."
            )

        # Pass 2: k-NN fallback, adaptive on N
        # k=2 for tiny (<=4), k=3 for small (5-7), k=4 for larger — empirically
        # balances over-smoothing (too many neighbors) vs. self-loop collapse.
        k = max(2, min(4, (n - 1) // 2)) if n >= 2 else 0
        if n >= 2:
            for i in range(n):
                ci = coords[i]
                if ci is None:
                    continue
                dists: list[tuple[float, int]] = []
                for j in range(n):
                    if i == j:
                        continue
                    cj = coords[j]
                    if cj is None:
                        continue
                    dx, dy = ci[0] - cj[0], ci[1] - cj[1]
                    dists.append((dx * dx + dy * dy, j))
                dists.sort()
                for _, j in dists[:k]:
                    edges.add((i, j))
                    edges.add((j, i))

        if edges:
            self.edge_index = np.array(sorted(edges), dtype=np.int64).T
        else:
            self.edge_index = np.empty((2, 0), dtype=np.int64)

        n_edges = self.edge_index.shape[1]
        logger.info(
            f"Graph built: {n} nodes, {n_edges} directed edges "
            f"(hop-traversal + k-NN k={k})"
        )
        if n_edges < n and n >= 2:
            logger.error(
                f"Graph density too low: {n_edges} edges for {n} nodes. "
                "CoLight attention will degenerate to self-loops."
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

        kept_tl_ids: list[str] = []
        skipped_single_phase: list[str] = []

        for tl_id in self.tl_ids:
            # Deduplicated controlled lanes (same as V1 environment.py:207-214)
            raw_lanes = list(conn.trafficlight.getControlledLanes(tl_id))
            seen: set[str] = set()
            unique_lanes: list[str] = []
            for lane in raw_lanes:
                if lane not in seen:
                    seen.add(lane)
                    unique_lanes.append(lane)

            # Extract green phases (same as V1 environment.py:221-227)
            logics = conn.trafficlight.getAllProgramLogics(tl_id)
            phases = logics[0].phases if logics else []
            green_phase_objects = [p for p in phases if "G" in p.state or "g" in p.state]
            if not green_phase_objects:
                green_phase_objects = list(phases) if phases else []

            # Skip TLs with <= 1 green phase: no decision space, only adds reward noise
            if len(green_phase_objects) <= 1:
                skipped_single_phase.append(tl_id)
                continue

            self._controlled_lanes[tl_id] = unique_lanes

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
            kept_tl_ids.append(tl_id)

            logger.info(
                f"TL {tl_id}: {len(unique_lanes)} lanes, "
                f"{len(green_phase_objects)} green phases, "
                f"{len(yellow_dict)} yellow transitions, "
                f"{len(full_phases)} total phases"
            )

        if skipped_single_phase:
            logger.warning(
                f"Skipped {len(skipped_single_phase)} TL(s) with <=1 green phase "
                f"(no decision space): {skipped_single_phase}"
            )

        if not kept_tl_ids:
            raise RuntimeError(
                "All selected TLs have <=1 green phase; nothing to train. "
                "Pick junctions with multi-phase signals."
            )

        self.tl_ids = kept_tl_ids

        # Compute observation / action dimensions.
        # Observation = [lane vehicle counts padded to max_lanes, phase one-hot padded to num_actions].
        # LibSignal ships phase=False as default but enables phase via one_hot=True; including phase
        # lets the agent distinguish "just switched" from "been green for N steps" without hidden state.
        self._max_lanes = max(len(self._controlled_lanes[tl]) for tl in self.tl_ids)
        self.phase_lengths = [
            len(self._green_phases[tl])
            for tl in self.tl_ids  # ordered by node_id2idx (same order as tl_ids)
        ]
        if self.action_mode == "duration":
            # Track 1: 4 duration buckets, uniform across all TLs.
            # phase_lengths still drives cyclic modulo (per-TL).
            self.num_actions = len(DURATION_BUCKETS_SEC)
        else:
            self.num_actions = max(self.phase_lengths)
        # +1 for normalized elapsed_in_green scalar — without it the agent
        # cannot tell "phase just started" from "phase about to cycle".
        self.ob_length = self._max_lanes + self.num_actions + 1

        # Build graph adjacency
        self._build_graph()

        self._is_initialized = True
        action_desc = (
            f"duration{list(DURATION_BUCKETS_SEC)}"
            if self.action_mode == "duration"
            else "phase"
        )
        logger.info(
            f"CoLightEnv initialized: {len(self.tl_ids)} TLs, "
            f"ob_length={self.ob_length}, num_actions={self.num_actions}, "
            f"phase_lengths={self.phase_lengths}, "
            f"edge_index shape={self.edge_index.shape}"
        )
        total_in_lanes = sum(len(self._controlled_lanes[tl]) for tl in self.tl_ids)
        logger.info(
            f"Scenario sanity: scenario={self.scenario}, "
            f"vehicle_max={self._vehicle_max:.1f}, "
            f"max_steps={self.max_steps}, steps_per_action={self.steps_per_action}, "
            f"total_in_lanes={total_in_lanes}, "
            f"routes_path={self.routes_path or self._cached_routes_path or 'auto-gen'}, "
            f"action_mode={action_desc}, "
            f"reward=t1_lane_waiting_count_mean*-12"
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

    # ------------------------------------------------------------------
    # Observation helpers
    # ------------------------------------------------------------------

    def _get_observation(self, tl_id: str) -> np.ndarray:
        """CoLight observation: [lane vehicle counts, phase one-hot, elapsed scalar].

        - Lane vehicle counts padded with zeros to self._max_lanes.
        - Phase one-hot over self.num_actions slots using current green index.
        - Elapsed scalar = min(elapsed_in_green / max_bucket, 1.0). Required
          for duration-mode decisions to be informed.
        - Total dim = self.ob_length = max_lanes + num_actions + 1.
        """
        conn = self._get_conn()

        lanes = self._controlled_lanes[tl_id]
        vehicle_counts = np.zeros(self._max_lanes, dtype=np.float32)
        for i, lane_id in enumerate(lanes):
            try:
                vehicle_counts[i] = float(conn.lane.getLastStepVehicleNumber(lane_id))
            except Exception:
                pass
        vehicle_counts /= self._vehicle_max

        phase_oh = np.zeros(self.num_actions, dtype=np.float32)
        cur_green = self._current_green_idx.get(tl_id, 0)
        if 0 <= cur_green < self.num_actions:
            phase_oh[cur_green] = 1.0

        max_bucket = float(max(DURATION_BUCKETS_SEC))
        elapsed = float(self._elapsed_in_green.get(tl_id, 0))
        elapsed_scalar = np.array(
            [min(elapsed / max_bucket, 1.0)], dtype=np.float32
        )

        return np.concatenate([vehicle_counts, phase_oh, elapsed_scalar], axis=0)

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
            self._elapsed_in_green[tl_id] = 0

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

        # Phase 1: Determine desired green index per TL.
        # Two interpretations of `actions[i]`:
        #
        # action_mode="duration" (Track 1, default): action = bucket index
        # into DURATION_BUCKETS_SEC. If phase_age >= bucket target, cycle to
        # (current+1) % num_green; else hold. Always cyclic, never reverses
        # — 2-phase TLs cannot starve.
        #
        # action_mode="phase" (legacy): action = green phase index. Subject
        # to DQN extrapolation error on 2-phase TLs (colight_problem5.md).
        for i, tl_id in enumerate(self.tl_ids):
            action = int(actions[i])
            num_green = len(self._green_phases[tl_id])
            current_idx = self._current_green_idx[tl_id]

            if self.action_mode == "duration":
                bucket = action % len(DURATION_BUCKETS_SEC)
                target_age = DURATION_BUCKETS_SEC[bucket]
                if num_green <= 1:
                    desired_green[tl_id] = current_idx
                    needs_yellow[tl_id] = False
                elif self._elapsed_in_green[tl_id] >= target_age:
                    desired_green[tl_id] = (current_idx + 1) % num_green
                    needs_yellow[tl_id] = True
                else:
                    desired_green[tl_id] = current_idx
                    needs_yellow[tl_id] = False
            else:
                action = action % num_green
                wants_switch = action != current_idx
                if wants_switch and self._elapsed_in_green[tl_id] < self.min_green:
                    desired_green[tl_id] = current_idx
                    needs_yellow[tl_id] = False
                else:
                    desired_green[tl_id] = action
                    needs_yellow[tl_id] = wants_switch

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

        # Phase 3: Set green phases for all TLs + reset/advance elapsed tracker
        for tl_id in self.tl_ids:
            new_idx = desired_green[tl_id]
            sumo_phase_idx = self._green_phases[tl_id][new_idx]
            conn.trafficlight.setPhase(tl_id, sumo_phase_idx)
            if needs_yellow[tl_id]:
                # Switched this step — reset elapsed (yellow_time + upcoming
                # steps_per_action count as fresh green, minus yellow_time)
                self._elapsed_in_green[tl_id] = 0
            self._current_green_idx[tl_id] = new_idx

        # Phase 4: Advance simulation for steps_per_action, collecting per-TL
        # per-substep T1 (LibSignal-exact) lane_waiting_count: count of
        # vehicles whose `getWaitingTime > 0` per controlled in-lane,
        # MEAN across in-lanes per intersection. This is what LibSignal's
        # CoLight ships (`agent/colight.py:62-63` LaneVehicleGenerator
        # `lane_waiting_count` average='all', `world/world_sumo.py:286-288`).
        sub_step_pressure: dict[str, list[float]] = {tl_id: [] for tl_id in self.tl_ids}
        for _ in range(self.steps_per_action):
            conn.simulationStep()
            self._current_step += 1
            self._cumulative_throughput += conn.simulation.getArrivedNumber()
            for tl_id in self.tl_ids:
                in_lanes = self._controlled_lanes[tl_id]
                if not in_lanes:
                    sub_step_pressure[tl_id].append(0.0)
                    continue
                waiting_count = 0
                for lane in in_lanes:
                    for v in conn.lane.getLastStepVehicleIDs(lane):
                        if conn.vehicle.getWaitingTime(v) > 0:
                            waiting_count += 1
                mean_waiting_count = waiting_count / max(len(in_lanes), 1)
                sub_step_pressure[tl_id].append(float(mean_waiting_count))

        # Advance elapsed tracker by steps_per_action for all TLs that held
        # their current green (switchers got reset above; also advance them).
        for tl_id in self.tl_ids:
            self._elapsed_in_green[tl_id] += self.steps_per_action

        # Phase 5: T1 reward — mean over substeps, ×−12 (LibSignal scaling).
        rewards = np.zeros(n, dtype=np.float32)
        for i, tl_id in enumerate(self.tl_ids):
            p = sub_step_pressure[tl_id]
            if not p:
                continue
            mean_p = float(np.nan_to_num(np.mean(p), nan=0.0, posinf=0.0, neginf=0.0))
            rewards[i] = -mean_p * 12.0

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
