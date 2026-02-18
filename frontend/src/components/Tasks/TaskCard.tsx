import { memo } from 'react';
import {
  Clock,
  Play,
  CheckCircle,
  XCircle,
  AlertCircle,
  X,
  Loader2,
  TrendingDown,
  TrendingUp,
} from 'lucide-react';
import type { Task, TaskStatus } from '../../types';

interface TaskCardProps {
  task: Task;
  onCancel: (taskId: string) => void;
  isCancelling: boolean;
}

const statusConfig: Record<
  TaskStatus,
  { icon: typeof Clock; color: string; bgColor: string; label: string }
> = {
  pending: {
    icon: Clock,
    color: 'text-yellow-600',
    bgColor: 'bg-yellow-50 border-yellow-200',
    label: 'Pending',
  },
  running: {
    icon: Play,
    color: 'text-blue-600',
    bgColor: 'bg-blue-50 border-blue-200',
    label: 'Running',
  },
  completed: {
    icon: CheckCircle,
    color: 'text-green-600',
    bgColor: 'bg-green-50 border-green-200',
    label: 'Completed',
  },
  failed: {
    icon: XCircle,
    color: 'text-red-600',
    bgColor: 'bg-red-50 border-red-200',
    label: 'Failed',
  },
  cancelled: {
    icon: AlertCircle,
    color: 'text-gray-600',
    bgColor: 'bg-gray-50 border-gray-200',
    label: 'Cancelled',
  },
};

function formatDate(isoString: string | null): string {
  if (!isoString) return '-';
  return new Date(isoString).toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

/**
 * Compute the percentage change between an RL value and a baseline value,
 * and determine whether the change is an improvement.
 *
 * @param rlValue - The value achieved by the RL model
 * @param baseline - The baseline (fixed-time) value
 * @param lowerIsBetter - If true, a decrease is an improvement (e.g., wait time, queue length)
 */
function computeChange(
  rlValue: number,
  baseline: number,
  lowerIsBetter: boolean,
): { percent: number; isImprovement: boolean } {
  if (baseline === 0) {
    return { percent: 0, isImprovement: false };
  }
  const percent = Math.round(Math.abs((rlValue - baseline) / baseline) * 100);
  const decreased = rlValue < baseline;
  const isImprovement = lowerIsBetter ? decreased : !decreased;
  return { percent, isImprovement };
}

interface MetricRowProps {
  label: string;
  rlValue: number | null;
  baseline: number | null;
  unit?: string;
  lowerIsBetter: boolean;
}

function MetricRow({ label, rlValue, baseline, unit = '', lowerIsBetter }: MetricRowProps) {
  if (rlValue === null) return null;

  const formattedRl = Number.isInteger(rlValue) ? rlValue : rlValue.toFixed(1);

  if (baseline === null || baseline === 0) {
    return (
      <div className="flex items-center justify-between text-xs">
        <span className="text-gray-600 w-24 shrink-0">{label}</span>
        <span className="font-medium tabular-nums">
          {formattedRl}{unit}
        </span>
      </div>
    );
  }

  const { percent, isImprovement } = computeChange(rlValue, baseline, lowerIsBetter);
  const formattedBaseline = Number.isInteger(baseline) ? baseline : baseline.toFixed(1);
  const decreased = rlValue < baseline;
  const TrendIcon = decreased ? TrendingDown : TrendingUp;
  const changeColor = isImprovement ? 'text-green-600' : 'text-red-600';
  const arrow = decreased ? '\u2193' : '\u2191';

  return (
    <div className="flex items-center justify-between text-xs gap-2">
      <span className="text-gray-600 w-24 shrink-0">{label}</span>
      <span className="font-medium tabular-nums">
        {formattedRl}{unit}
      </span>
      <span className="text-gray-400 tabular-nums text-[11px]">
        Fixed: {formattedBaseline}{unit}
      </span>
      <span className={`flex items-center gap-0.5 font-semibold tabular-nums ${changeColor}`}>
        <TrendIcon size={12} />
        {arrow}{percent}%
      </span>
    </div>
  );
}

function TaskCardComponent({ task, onCancel, isCancelling }: TaskCardProps) {
  const config = statusConfig[task.status];
  const StatusIcon = config.icon;
  const progressPercent = Math.round(task.progress * 100);
  const canCancel = task.status === 'running' || task.status === 'pending';

  return (
    <div className={`border rounded-lg p-3 ${config.bgColor}`}>
      {/* Header */}
      <div className="flex items-start justify-between mb-2">
        <div className="flex items-center gap-2">
          <StatusIcon size={16} className={config.color} />
          <span className={`text-sm font-medium ${config.color}`}>
            {config.label}
          </span>
        </div>
        {canCancel && (
          <button
            onClick={() => onCancel(task.task_id)}
            disabled={isCancelling}
            className="p-1 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded disabled:opacity-50"
            title="Cancel task"
          >
            {isCancelling ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <X size={14} />
            )}
          </button>
        )}
      </div>

      {/* Task details */}
      <div className="space-y-1 text-sm">
        <div className="flex justify-between">
          <span className="text-gray-600">Traffic Light:</span>
          <span className="font-medium">{task.traffic_light_id}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-600">Algorithm:</span>
          <span className="font-medium">{task.algorithm}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-600">Created:</span>
          <span className="text-gray-700">{formatDate(task.created_at)}</span>
        </div>
      </div>

      {/* Progress bar for running tasks */}
      {task.status === 'running' && (
        <div className="mt-3">
          <div className="flex justify-between text-xs mb-1">
            <span className="text-gray-600">
              Step {task.current_timestep} / {task.total_timesteps}
            </span>
            <span className="font-medium">{progressPercent}%</span>
          </div>
          <div className="w-full bg-gray-200 rounded-full h-2">
            <div
              className="bg-blue-500 h-2 rounded-full transition-all duration-300"
              style={{ width: `${progressPercent}%` }}
            />
          </div>
        </div>
      )}

      {/* Traffic metrics for completed tasks (with baseline comparison) */}
      {task.status === 'completed' &&
        (task.avg_waiting_time !== null ||
          task.avg_queue_length !== null ||
          task.throughput !== null) && (
          <div className="mt-3 pt-2 border-t border-gray-200 space-y-1.5">
            <MetricRow
              label="Avg Wait Time"
              rlValue={task.avg_waiting_time}
              baseline={task.baseline_avg_waiting_time}
              unit="s"
              lowerIsBetter={true}
            />
            <MetricRow
              label="Queue Length"
              rlValue={task.avg_queue_length}
              baseline={task.baseline_avg_queue_length}
              lowerIsBetter={true}
            />
            <MetricRow
              label="Throughput"
              rlValue={task.throughput}
              baseline={task.baseline_throughput}
              lowerIsBetter={false}
            />
            {task.episode_count > 0 && (
              <div className="pt-1 text-[11px] text-gray-400 flex justify-between">
                <span>Episodes: {task.episode_count}</span>
                <span>Mean Reward: {task.mean_reward.toFixed(2)}</span>
              </div>
            )}
          </div>
        )}

      {/* Live metrics for running tasks (no baseline comparison) */}
      {task.status === 'running' &&
        (task.avg_waiting_time !== null || task.avg_queue_length !== null) && (
          <div className="mt-3 pt-2 border-t border-gray-200 space-y-1.5">
            <MetricRow
              label="Avg Wait Time"
              rlValue={task.avg_waiting_time}
              baseline={null}
              unit="s"
              lowerIsBetter={true}
            />
            <MetricRow
              label="Queue Length"
              rlValue={task.avg_queue_length}
              baseline={null}
              lowerIsBetter={true}
            />
            {task.episode_count > 0 && (
              <div className="pt-1 text-[11px] text-gray-400">
                Episodes: {task.episode_count}
              </div>
            )}
          </div>
        )}

      {/* Error message for failed tasks */}
      {task.status === 'failed' && task.error_message && (
        <div className="mt-3 p-2 bg-red-100 border border-red-200 rounded text-sm text-red-700">
          {task.error_message}
        </div>
      )}

      {/* Completion time */}
      {task.status === 'completed' && task.completed_at && (
        <div className="mt-2 text-xs text-gray-500">
          Completed: {formatDate(task.completed_at)}
        </div>
      )}
    </div>
  );
}

export const TaskCard = memo(TaskCardComponent);
