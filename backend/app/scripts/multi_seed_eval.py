"""Multi-seed deterministic eval for a saved CoLight model.

Usage (inside celery-worker container):
    uv run python -m app.scripts.multi_seed_eval \
        --model-path /app/simulation/models/90ccdbcc952c5394_multi_colight_20260501_043446.pt \
        --network-id 90ccdbcc952c5394 \
        --tl-ids 411919431,411926160,411926403,411926419,411926532,411926559,5772027667,GS_cluster_13075564400_13075589603,GS_cluster_13075589601_13075589602_411926477,cluster_12181658673_2036141704\
        --scenario moderate \
        --seeds 1,2,3,4,5

Reports baseline, eval mean ± std, and pass-bar deltas. No retraining.
"""

import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--model-path", required=True)
    p.add_argument("--network-id", required=True)
    p.add_argument("--tl-ids", required=True, help="comma-separated TL IDs")
    p.add_argument("--scenario", default="moderate")
    p.add_argument("--seeds", required=True, help="comma-separated SUMO seeds")
    p.add_argument("--num-episodes", type=int, default=3,
                   help="episodes per seed (default 3)")
    p.add_argument("--out-json", default=None,
                   help="optional JSON file path for results")
    args = p.parse_args()

    from app.config import settings
    from app.ml.colight_env import CoLightEnv
    from app.ml.colight_trainer import CoLightTrainer

    tl_ids = [s.strip() for s in args.tl_ids.split(",") if s.strip()]
    seeds = [int(s) for s in args.seeds.split(",") if s.strip()]
    network_path = str(settings.simulation_networks_dir / f"{args.network_id}.net.xml")
    if not Path(network_path).exists():
        logger.error(f"Network not found: {network_path}")
        return 1

    env = CoLightEnv(
        network_path=network_path,
        network_id=args.network_id,
        tl_ids=tl_ids,
        scenario=args.scenario,
    )
    trainer = CoLightTrainer(env=env)
    trainer.load(args.model_path)

    # Build interleaved seed list so baseline & eval see same per-ep traffic.
    eval_seeds = [s for s in seeds for _ in range(args.num_episodes)]

    # Baseline on the SAME seeds (apples-to-apples per-seed comparison).
    baseline = trainer.run_baseline(num_episodes=len(eval_seeds), seeds=eval_seeds)
    logger.info(f"Baseline (seeded): {baseline}")

    # Multi-seed agent eval.
    eval_metrics = trainer.evaluate(num_episodes=len(eval_seeds), seeds=eval_seeds)

    bw = baseline["avg_waiting_time"] or 1e-9
    bq = baseline["avg_queue_length"] or 1e-9
    bt = baseline["throughput"] or 1
    dw = (eval_metrics["avg_waiting_time"] - bw) / bw * 100.0
    dq = (eval_metrics["avg_queue_length"] - bq) / bq * 100.0
    dt = (eval_metrics["throughput"] - bt) / bt * 100.0

    # Per-seed aggregation.
    per_seed: dict[int, list[dict]] = {}
    for m in eval_metrics["per_episode"]:
        seed_val = m.get("seed")
        try:
            seed_f = float(seed_val) if seed_val is not None else float("nan")
        except (TypeError, ValueError):
            seed_f = float("nan")
        s = int(seed_f) if not np.isnan(seed_f) else -1
        per_seed.setdefault(s, []).append(m)

    # Same aggregation for baseline.
    base_per_seed: dict[int, list[dict]] = {}
    for m in baseline.get("per_episode", []):
        seed_val = m.get("seed")
        try:
            seed_f = float(seed_val) if seed_val is not None else float("nan")
        except (TypeError, ValueError):
            seed_f = float("nan")
        s = int(seed_f) if not np.isnan(seed_f) else -1
        base_per_seed.setdefault(s, []).append(m)

    seed_summary = []
    for s, eps in sorted(per_seed.items()):
        wait_arr = np.array([e["wait"] for e in eps])
        queue_arr = np.array([e["queue"] for e in eps])
        tput_arr = np.array([e["throughput"] for e in eps])
        b_eps = base_per_seed.get(s, [])
        b_wait = np.array([e["wait"] for e in b_eps]) if b_eps else None
        b_queue = np.array([e["queue"] for e in b_eps]) if b_eps else None
        b_tput = np.array([e["throughput"] for e in b_eps]) if b_eps else None
        per_seed_dw = (wait_arr.mean() - b_wait.mean()) / max(b_wait.mean(), 1e-9) * 100.0 if b_wait is not None else None
        per_seed_dq = (queue_arr.mean() - b_queue.mean()) / max(b_queue.mean(), 1e-9) * 100.0 if b_queue is not None else None
        per_seed_dt = (tput_arr.mean() - b_tput.mean()) / max(b_tput.mean(), 1e-9) * 100.0 if b_tput is not None else None
        seed_summary.append({
            "seed": s,
            "episodes": len(eps),
            "agent_wait_mean": float(wait_arr.mean()),
            "agent_queue_mean": float(queue_arr.mean()),
            "agent_tput_mean": float(tput_arr.mean()),
            "baseline_wait_mean": float(b_wait.mean()) if b_wait is not None else None,
            "baseline_queue_mean": float(b_queue.mean()) if b_queue is not None else None,
            "baseline_tput_mean": float(b_tput.mean()) if b_tput is not None else None,
            "delta_wait_pct": per_seed_dw,
            "delta_queue_pct": per_seed_dq,
            "delta_tput_pct": per_seed_dt,
        })

    summary = {
        "model_path": args.model_path,
        "network_id": args.network_id,
        "scenario": args.scenario,
        "seeds": seeds,
        "num_episodes_per_seed": args.num_episodes,
        "total_eval_episodes": len(eval_seeds),
        "baseline": baseline,
        "eval_aggregate": {
            "wait_mean": eval_metrics["avg_waiting_time"],
            "wait_std": eval_metrics["wait_std"],
            "queue_mean": eval_metrics["avg_queue_length"],
            "queue_std": eval_metrics["queue_std"],
            "tput_mean": eval_metrics["throughput"],
            "tput_std": eval_metrics["throughput_std"],
        },
        "deltas_pct_vs_baseline": {
            "wait": dw,
            "queue": dq,
            "throughput": dt,
        },
        "per_seed": seed_summary,
        "per_episode": eval_metrics["per_episode"],
    }

    print("\n" + "=" * 72)
    print(f"MULTI-SEED EVAL — {args.network_id} / {args.scenario}")
    print(f"Model: {args.model_path}")
    print(f"Seeds: {seeds} × {args.num_episodes} eps = {len(eval_seeds)} total")
    print("=" * 72)
    print(f"Baseline: wait={bw:.2f}s queue={bq:.2f} tput={bt}")
    print(
        f"Eval:     wait={eval_metrics['avg_waiting_time']:.2f}±{eval_metrics['wait_std']:.2f} "
        f"({dw:+.1f}%), "
        f"queue={eval_metrics['avg_queue_length']:.2f}±{eval_metrics['queue_std']:.2f} "
        f"({dq:+.1f}%), "
        f"tput={eval_metrics['throughput']}±{eval_metrics['throughput_std']:.0f} "
        f"({dt:+.1f}%)"
    )
    print()
    print("Per-seed (agent vs fixed-time on SAME traffic):")
    for s in seed_summary:
        if s["baseline_wait_mean"] is not None:
            print(
                f"  seed={s['seed']:>4}: agent wait={s['agent_wait_mean']:.1f}s "
                f"vs base={s['baseline_wait_mean']:.1f}s ({s['delta_wait_pct']:+.1f}%)  "
                f"queue={s['agent_queue_mean']:.2f} vs {s['baseline_queue_mean']:.2f} "
                f"({s['delta_queue_pct']:+.1f}%)  "
                f"tput={s['agent_tput_mean']:.0f} vs {s['baseline_tput_mean']:.0f} "
                f"({s['delta_tput_pct']:+.1f}%)"
            )
        else:
            print(
                f"  seed={s['seed']:>4}: agent wait={s['agent_wait_mean']:.1f}s "
                f"queue={s['agent_queue_mean']:.2f}  tput={s['agent_tput_mean']:.0f}"
            )
    print("=" * 72)

    if args.out_json:
        with open(args.out_json, "w") as f:
            json.dump(summary, f, indent=2)
        logger.info(f"Results saved to {args.out_json}")

    env.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
