import { memo } from 'react';
import {
  Clock,
  Play,
  CheckCircle,
  XCircle,
  AlertCircle,
  X,
  Loader2,
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

      {/* Metrics for running/completed tasks */}
      {(task.status === 'running' || task.status === 'completed') &&
        task.episode_count > 0 && (
          <div className="mt-3 pt-2 border-t border-gray-200 space-y-1 text-sm">
            <div className="flex justify-between">
              <span className="text-gray-600">Episodes:</span>
              <span className="font-medium">{task.episode_count}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-600">Mean Reward:</span>
              <span className="font-medium">{task.mean_reward.toFixed(2)}</span>
            </div>
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
