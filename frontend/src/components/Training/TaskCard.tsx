import { X } from 'lucide-react';
import type { TaskInfo, TaskStatus } from '../../types';

const STATUS_STYLES: Record<TaskStatus, string> = {
  queued: 'bg-gray-100 text-gray-600',
  running: 'bg-blue-100 text-blue-700',
  completed: 'bg-green-100 text-green-700',
  failed: 'bg-red-100 text-red-700',
  cancelled: 'bg-yellow-100 text-yellow-700',
};

interface TaskCardProps {
  task: TaskInfo;
  isActive: boolean;
  onClick: () => void;
  onCancel: () => void;
}

export function TaskCard({ task, isActive, onClick, onCancel }: TaskCardProps) {
  const canCancel = task.status === 'queued' || task.status === 'running';
  const progressPct = Math.round(task.progress * 100);

  return (
    <button
      onClick={onClick}
      className={`w-full text-left p-2 rounded-lg border transition-colors ${
        isActive ? 'border-blue-400 bg-blue-50' : 'border-gray-200 bg-white hover:bg-gray-50'
      }`}
    >
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs font-mono text-gray-600 truncate max-w-[120px]">
          {task.task_id.slice(0, 8)}...
        </span>
        <div className="flex items-center gap-1">
          {task.algorithm && (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-50 text-blue-600 font-medium uppercase">
              {task.algorithm}
            </span>
          )}
          <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${STATUS_STYLES[task.status]}`}>
            {task.status}
          </span>
        </div>
      </div>

      {/* Progress bar */}
      <div className="w-full h-1.5 bg-gray-200 rounded-full overflow-hidden">
        <div
          className="h-full bg-blue-500 rounded-full transition-all duration-300"
          style={{ width: `${progressPct}%` }}
        />
      </div>

      <div className="flex items-center justify-between mt-1">
        <span className="text-[10px] text-gray-500">{progressPct}%</span>
        {canCancel && (
          <button
            onClick={(e) => {
              e.stopPropagation();
              onCancel();
            }}
            className="text-gray-400 hover:text-red-500 transition-colors"
            title="Cancel task"
          >
            <X size={12} />
          </button>
        )}
      </div>
    </button>
  );
}
