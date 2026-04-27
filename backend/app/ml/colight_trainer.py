"""Trainer for CoLight multi-agent traffic light optimization.

Custom DQN training loop following V1 TrafficLightTrainer pattern,
adapted for CoLight's graph-based multi-agent structure.
"""

import logging
from pathlib import Path
from typing import Any

import numpy as np
import torch

from app.ml.colight_env import CoLightEnv
from app.ml.networks.colight_network import CoLightAgent
from app.ml.trainer import TrainingCallback

logger = logging.getLogger(__name__)


class CoLightTrainer:
    """Trainer for CoLight multi-agent traffic light optimization.

    Uses a custom DQN training loop with graph-batched transitions
    and the same TrainingCallback interface as the V1 trainer.
    """

    def __init__(
        self,
        env: CoLightEnv,
        seed: int | None = None,
    ) -> None:
        self.env = env
        self._seed = seed
        self._episode_rewards: list[float] = []
        self._baseline: dict[str, float] | None = None

        # Trigger lazy initialization so env dimensions are available
        self.env.reset(seed=seed)

        device = "cuda" if torch.cuda.is_available() else "cpu"

        self.agent = CoLightAgent(
            ob_length=env.ob_length,
            num_actions=env.num_actions,
            num_intersections=len(env.tl_ids),
            phase_lengths=env.phase_lengths,
            edge_index=env.edge_index,
            lr=1e-3,
            gamma=0.95,
            epsilon_start=0.5,
            epsilon_min=0.05,
            epsilon_decay=0.9997,
            grad_clip=5.0,
            buffer_size=20000,
            batch_size=64,
            device=device,
            n_layers=1,
            node_emb_dim=[128, 128],
            num_heads=[5, 5],
            dims_per_head=[16, 16],
        )

        logger.info(
            f"CoLightTrainer initialized: {len(env.tl_ids)} intersections, "
            f"ob_length={env.ob_length}, num_actions={env.num_actions}, "
            f"device={device}"
        )

    def train(
        self,
        total_timesteps: int,
        callbacks: list[TrainingCallback] | None = None,
    ) -> None:
        """Train the CoLight agent using DQN with graph attention.

        Converts total_timesteps to episodes (~360 decisions per episode)
        and runs the DQN training loop.
        """
        logger.info(f"Starting CoLight training for {total_timesteps} timesteps")

        agent = self.agent
        num_episodes = max(total_timesteps // 360, 10)
        learning_start = 3600
        update_model_rate = 1
        update_target_rate = 10
        total_decisions = 0

        for episode in range(num_episodes):
            obs = self.env.reset()  # [N, ob_length]
            episode_reward = 0.0
            episode_steps = 0
            done = False
            info: dict = {}

            ep_losses: list[float] = []
            ep_q_abs: list[float] = []
            per_tl_reward_sum = np.zeros(len(self.env.tl_ids), dtype=np.float64)
            obs_min = float("inf")
            obs_max = float("-inf")
            action_counts = np.zeros(agent.num_actions, dtype=np.int64)

            while not done:
                actions = agent.select_action(obs)  # [N]
                for a in actions:
                    action_counts[int(a)] += 1
                obs_min = min(obs_min, float(np.min(obs)))
                obs_max = max(obs_max, float(np.max(obs)))

                next_obs, rewards, done, info = self.env.step(actions)

                agent.remember(obs, actions, rewards, next_obs, float(done))
                total_decisions += 1
                episode_reward += float(np.mean(rewards))
                per_tl_reward_sum += np.asarray(rewards, dtype=np.float64)
                episode_steps += 1

                loss = None
                if total_decisions > learning_start and total_decisions % update_model_rate == 0:
                    if agent.can_train():
                        loss = agent.update(agent.sample_batch())
                        agent.decay_epsilon()
                        if loss is not None:
                            ep_losses.append(float(loss))
                            with torch.no_grad():
                                obs_t = torch.as_tensor(obs, dtype=torch.float32, device=agent.device)
                                q = agent.q_network(obs_t, agent.adj_matrix)
                                ep_q_abs.append(float(q.abs().mean().item()))

                if total_decisions > learning_start and total_decisions % update_target_rate == 0:
                    agent.update_target_network()

                for cb in (callbacks or []):
                    cb.on_step(total_decisions, loss, info)

                obs = next_obs

            self._episode_rewards.append(episode_reward)
            mean_loss = float(np.mean(ep_losses)) if ep_losses else float("nan")
            mean_q_abs = float(np.mean(ep_q_abs)) if ep_q_abs else float("nan")
            per_tl_str = ",".join(f"{r:.0f}" for r in per_tl_reward_sum)
            action_dist = action_counts / max(action_counts.sum(), 1)
            action_dist_str = ",".join(f"{p:.2f}" for p in action_dist)
            wait = float(info.get("avg_waiting_time", 0.0))
            queue = float(info.get("avg_queue_length", 0.0))
            throughput = int(info.get("throughput", 0))
            if self._baseline is not None:
                bw = self._baseline.get("avg_waiting_time", 0.0) or 1e-9
                bq = self._baseline.get("avg_queue_length", 0.0) or 1e-9
                bt = self._baseline.get("throughput", 0) or 1
                dw = (wait - bw) / bw * 100.0
                dq = (queue - bq) / bq * 100.0
                dt = (throughput - bt) / bt * 100.0
                metric_str = (
                    f"wait={wait:.2f}s({dw:+.1f}%), "
                    f"queue={queue:.2f}({dq:+.1f}%), "
                    f"throughput={throughput}({dt:+.1f}%)"
                )
            else:
                metric_str = f"wait={wait:.2f}s, queue={queue:.2f}, throughput={throughput}"
            logger.info(
                f"Episode {episode + 1}/{num_episodes}: reward={episode_reward:.2f}, "
                f"steps={episode_steps}, decisions={total_decisions}, "
                f"epsilon={agent.epsilon:.4f}, "
                f"buffer={len(agent.replay_buffer)}, "
                f"loss_mean={mean_loss:.2f}, q_abs_mean={mean_q_abs:.2f}, "
                f"{metric_str}, "
                f"obs_range=[{obs_min:.3f},{obs_max:.3f}], "
                f"action_dist=[{action_dist_str}], per_tl_reward=[{per_tl_str}]"
            )

            for cb in (callbacks or []):
                if not cb.on_episode_end(episode, num_episodes, episode_reward, info):
                    logger.info("Training cancelled by callback")
                    return

        logger.info("CoLight training complete")

    def save(self, path: str | Path) -> Path:
        """Save the trained model as a PyTorch checkpoint."""
        agent = self.agent
        save_data: dict[str, Any] = {
            "algorithm": "colight",
            "ob_length": agent.ob_length,
            "num_actions": agent.num_actions,
            "num_intersections": agent.num_intersections,
            "phase_lengths": agent.phase_lengths,
            "edge_index": self.env.edge_index,
            "tl_ids": self.env.tl_ids,
            "model_state": agent.q_network.state_dict(),
            "target_state": agent.target_network.state_dict(),
            "network_params": {
                "n_layers": len(agent.q_network.attention_layers),
                "node_emb_dim": [128, 128],
                "num_heads": [5, 5],
                "dims_per_head": [16, 16],
            },
        }

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        torch.save(save_data, str(path))
        logger.info(f"CoLight model saved to {path}")
        return path

    def load(self, path: str | Path) -> None:
        """Load a trained model from checkpoint."""
        path = Path(path)
        checkpoint = torch.load(str(path), map_location=self.agent.device, weights_only=False)

        self.agent.q_network.load_state_dict(checkpoint["model_state"])
        if "target_state" in checkpoint:
            self.agent.target_network.load_state_dict(checkpoint["target_state"])

        logger.info(f"CoLight model loaded from {path}")

    def run_baseline(self, num_episodes: int = 3) -> dict[str, float]:
        """Run baseline episodes with SUMO's default timing.

        Returns dict with avg_waiting_time, avg_queue_length, throughput.
        """
        logger.info(f"Running {num_episodes} baseline episodes")
        total_waiting = 0.0
        total_queue = 0.0
        total_throughput = 0

        for _ in range(num_episodes):
            self.env.reset()
            conn = self.env._get_conn()

            # Restore SUMO's default fixed-time program for all TLs
            for tl_id in self.env.tl_ids:
                conn.trafficlight.setProgram(tl_id, "0")

            ep_waiting = 0.0
            ep_queue = 0.0
            ep_throughput = 0
            steps = 0

            for sim_step in range(self.env.max_steps):
                conn.simulationStep()
                ep_throughput += conn.simulation.getArrivedNumber()

                if (sim_step + 1) % self.env.steps_per_action == 0:
                    per_tl_waiting: list[float] = []
                    per_tl_queue: list[float] = []

                    for tl_id in self.env.tl_ids:
                        lanes = self.env._controlled_lanes[tl_id]
                        lane_vids: list[str] = []
                        for lane in lanes:
                            lane_vids.extend(conn.lane.getLastStepVehicleIDs(lane))
                        wait = sum(conn.vehicle.getWaitingTime(v) for v in lane_vids)
                        per_tl_waiting.append(wait / max(len(lane_vids), 1))

                        queue = sum(conn.lane.getLastStepHaltingNumber(lane) for lane in lanes)
                        per_tl_queue.append(queue / max(len(lanes), 1))

                    ep_waiting += float(np.mean(per_tl_waiting)) if per_tl_waiting else 0.0
                    ep_queue += float(np.mean(per_tl_queue)) if per_tl_queue else 0.0
                    steps += 1

            if steps > 0:
                total_waiting += ep_waiting / steps
                total_queue += ep_queue / steps
            total_throughput += ep_throughput

        baseline = {
            "avg_waiting_time": total_waiting / max(num_episodes, 1),
            "avg_queue_length": total_queue / max(num_episodes, 1),
            "throughput": total_throughput // max(num_episodes, 1),
        }
        logger.info(f"Baseline metrics: {baseline}")
        self._baseline = baseline
        return baseline
