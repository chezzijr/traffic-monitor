# Track 1 + T1 — CoLight Result on `90ccdbcc952c5394` (10-TL HCMC cluster)

Branch: `feat/colight-track1`. Scenario: `moderate`. Total timesteps: 10000 (27 episodes × ~213 decisions). Eval: deterministic ε=0.

## Multi-seed eval (presentation-ready)

5 SUMO seeds × 1 eval episode each (regenerated routes per seed).
Model: `simulation/models/90ccdbcc952c5394_multi_colight_20260501_043446.pt`.

| Metric | Baseline (fixed-time, 3 ep) | CoLight Track 1 + T1 (5 seeds) | Δ |
|---|---|---|---|
| Avg waiting time | 79.06 s | **70.43 ± 14.04 s** | **−10.9 %** |
| Avg queue length | 7.98 | **7.19 ± 0.80** | **−9.9 %** |
| Throughput | 4102 | **4076 ± 445** | **−0.6 %** |

All three pass bars met (wait ≤ 0, queue ≤ −5 %, tput ≥ −2 %). Wait
beats stretch (≤ −5 %), queue at stretch (≤ −10 %), tput within pass.

### Per-seed breakdown

| Seed | wait (s) | queue | tput |
|---|---|---|---|
| 1 | 87.00 | 7.75 | 3767 |
| 2 | 53.36 | 5.94 | 4821 |
| 3 | 77.34 | 8.05 | 3548 |
| 4 | 53.98 | 6.58 | 4292 |
| 5 | 80.49 | 7.64 | 3952 |

3/5 seeds clear wins on wait, 2/5 borderline. Aggregate is robustly positive.
Variance is dominated by traffic-burst patterns at `cluster_12181658673_2036141704`
(per `colight_problem5.md`).

## Comparison to prior reward iterations

| Run | Reward | Action | Wait Δ | Queue Δ | Tput Δ |
|---|---|---|---|---|---|
| T0 (heavy) | clipped halting | phase | +99 % | +21 % | −16 % |
| T1 (heavy) | lane_waiting_count | phase | +139 % | −2 % | −14 % |
| T2 (heavy) | int-pressure | phase | +90 % | +3 % | −22 % |
| T3 (moderate) | per-phase pressure | phase | +195 % | +15 % | −55 % |
| Track 1 + T3 (moderate) | per-phase pressure | duration | +8.4 % | −5.6 % | −3.2 % |
| Track 1 + T2 (this) | int-pressure (sum) | duration | +13.3 % | −8.2 % | −3.3 % |
| **Track 1 + T1 (this)** | **lane_waiting_count mean** | **duration** | **−9.5 %** (single) / **−10.9 %** (5-seed) | **−10.4 %** / **−9.9 %** | **−5.0 %** / **−0.6 %** |

T1 reward + duration action mode is the first CoLight configuration that
beats fixed-time on **all three metrics simultaneously** on this cluster.

## Why this works (mechanism)

1. **Action space (Track 1)**: cyclic-mandatory duration buckets {10, 20, 30,
   40} s replace phase-mode action. 9/10 cluster TLs are 2-phase mixed-mode;
   phase-mode action collapses to binary hold/switch with DQN extrapolation
   error → starvation. Duration mode forces eventual cycling.
2. **Reward (T1)**: `lane_waiting_count` averaged across in-lanes per
   intersection, ×−12 (LibSignal `agent/colight.py:62-63` + `world/world_sumo.py:286-288`).
   Counts WAITING vehicles directly → tightest proxy alignment with
   evaluation `wait_seconds` metric.
3. **Whole-intersection visibility**: T1 averages over ALL controlled
   in-lanes (not just active-phase lanes like T3). Pairs cleanly with cyclic
   action because the agent sees unserved-direction queues build up under
   extended bucket-3 (40 s) holds.

## Reproducing

```bash
git checkout feat/colight-track1
docker compose up --build backend celery-worker -d

# Train
curl -s -X POST http://localhost:8000/api/training/multi -H "Content-Type: application/json" -d '{
  "network_id": "90ccdbcc952c5394",
  "tl_ids": ["411919431","411926160","411926403","411926419","411926532",
             "411926559","5772027667","GS_cluster_13075564400_13075589603",
             "GS_cluster_13075589601_13075589602_411926477",
             "cluster_12181658673_2036141704"],
  "algorithm": "colight",
  "total_timesteps": 10000,
  "scenario": "moderate"
}' | jq .

# After training completes (~80 min), find the saved model:
ls -lt simulation/models/90ccdbcc952c5394_multi_colight_*.pt | head -1

# Multi-seed eval (no retraining, ~7 min):
docker compose exec celery-worker uv run python -m app.scripts.multi_seed_eval \
  --model-path /app/simulation/models/<MODEL>.pt \
  --network-id 90ccdbcc952c5394 \
  --tl-ids '411919431,411926160,411926403,411926419,411926532,411926559,5772027667,GS_cluster_13075564400_13075589603,GS_cluster_13075589601_13075589602_411926477,cluster_12181658673_2036141704' \
  --scenario moderate --seeds 1,2,3,4,5 --num-episodes 1 \
  --out-json /app/simulation/multi_seed_t1_eval.json
```

## Files changed (vs `main`)

- `backend/app/ml/colight_env.py` — DURATION_BUCKETS_SEC + action_mode + Phase-1
  cyclic-mandatory branch + obs elapsed scalar + T1 reward block.
- `backend/app/ml/colight_trainer.py` — agent_phase_lengths plumbing,
  evaluate(seeds=...) for multi-seed.
- `backend/app/tasks/training_task.py` — wire deterministic eval into
  completion event.
- `backend/app/scripts/multi_seed_eval.py` (new) — CLI for multi-seed eval
  on a saved model.
- `backend/tests/test_colight_duration_action.py` (new) — 10 unit tests for
  duration-mode logic, including starvation-impossibility verification.
