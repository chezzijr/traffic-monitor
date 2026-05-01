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

    # Baseline (fixed-time) for comparison.
    baseline = trainer.run_baseline(num_episodes=3)
    logger.info(f"Baseline: {baseline}")

    # Multi-seed eval. Repeat seed list to fill num_episodes-per-seed budget.
    eval_seeds = [s for s in seeds for _ in range(args.num_episodes)]
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

    seed_summary = []
    for s, eps in sorted(per_seed.items()):
        wait_arr = np.array([e["wait"] for e in eps])
        queue_arr = np.array([e["queue"] for e in eps])
        tput_arr = np.array([e["throughput"] for e in eps])
        seed_summary.append({
            "seed": s,
            "episodes": len(eps),
            "wait_mean": float(wait_arr.mean()),
            "wait_std": float(wait_arr.std()),
            "queue_mean": float(queue_arr.mean()),
            "queue_std": float(queue_arr.std()),
            "tput_mean": float(tput_arr.mean()),
            "tput_std": float(tput_arr.std()),
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
    print("Per-seed:")
    for s in seed_summary:
        print(
            f"  seed={s['seed']:>4} (n={s['episodes']}): "
            f"wait={s['wait_mean']:.2f}±{s['wait_std']:.2f}  "
            f"queue={s['queue_mean']:.2f}±{s['queue_std']:.2f}  "
            f"tput={s['tput_mean']:.0f}±{s['tput_std']:.0f}"
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
