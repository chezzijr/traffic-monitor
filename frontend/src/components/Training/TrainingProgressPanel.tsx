import { ArrowDown, ArrowUp, X } from 'lucide-react';
import { useTrainingStore } from '../../store/trainingStore';
import { taskService } from '../../services/taskService';
import { TrainingChart } from './TrainingChart';
import toast from 'react-hot-toast';
import type { TrainingProgressEvent } from '../../types';

interface MetricCardProps {
  label: string;
  value: number;
  baseline?: number;
  lowerIsBetter?: boolean;
  unit?: string;
}

function MetricCard({ label, value, baseline, lowerIsBetter = false, unit = '' }: MetricCardProps) {
  const delta = baseline != null ? value - baseline : null;
  const isImproved = delta != null && (lowerIsBetter ? delta < 0 : delta > 0);

  return (
    <div className="bg-gray-50 rounded-lg p-3 flex-1 min-w-0">
      <p className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">{label}</p>
      <p className="text-lg font-bold text-gray-800">
        {value.toFixed(1)}{unit}
      </p>
      {delta != null && (
        <div className={`flex items-center gap-0.5 text-xs mt-0.5 ${isImproved ? 'text-green-600' : 'text-red-500'}`}>
          {isImproved ? <ArrowDown size={10} /> : <ArrowUp size={10} />}
          <span>{Math.abs(delta).toFixed(1)}</span>
          {baseline != null && baseline !== 0 && (
            <span className="text-gray-400 ml-0.5">
              ({Math.abs((delta / baseline) * 100).toFixed(0)}%)
            </span>
          )}
        </div>
      )}
    </div>
  );
}

interface TrainingProgressPanelProps {
  progressHistory: TrainingProgressEvent[];
}

export function TrainingProgressPanel({ progressHistory }: TrainingProgressPanelProps) {
  const activeTaskId = useTrainingStore((s) => s.activeTaskId);
  const latestProgress = useTrainingStore((s) =>
    s.activeTaskId ? s.liveProgress[s.activeTaskId] ?? null : null
  );

  const handleCancel = async () => {
    if (!activeTaskId) return;
    try {
      await taskService.cancelTask(activeTaskId);
      toast.success('Task cancelled');
    } catch {
      toast.error('Failed to cancel task');
    }
  };

  if (!activeTaskId || !latestProgress) {
    return (
      <div className="h-full flex items-center justify-center text-sm text-gray-400">
        No active training task. Start training to see progress.
      </div>
    );
  }

  const progressPct = Math.round(latestProgress.progress * 100);
  const canCancel = latestProgress.status === 'running' || latestProgress.status === 'queued';

  return (
    <div className="h-full flex flex-col gap-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-gray-700">Training Progress</h3>
          <p className="text-xs text-gray-500 font-mono">
            Step {latestProgress.timestep.toLocaleString()} / {latestProgress.total_timesteps.toLocaleString()}
            {' '}({progressPct}%)
          </p>
        </div>
        {canCancel && (
          <button
            onClick={handleCancel}
            className="flex items-center gap-1 text-xs px-2 py-1 rounded bg-red-50 text-red-600 hover:bg-red-100 transition-colors"
          >
            <X size={12} />
            Cancel
          </button>
        )}
      </div>

      {/* Progress bar */}
      <div className="w-full h-2 bg-gray-200 rounded-full overflow-hidden">
        <div
          className="h-full bg-blue-500 rounded-full transition-all duration-500"
          style={{ width: `${progressPct}%` }}
        />
      </div>

      {/* Metrics + Chart */}
      <div className="flex-1 flex gap-4 min-h-0">
        {/* Metric cards */}
        <div className="flex flex-col gap-2 w-52 shrink-0">
          <MetricCard
            label="Avg Waiting Time"
            value={latestProgress.avg_waiting_time}
            baseline={latestProgress.baseline_avg_waiting_time}
            lowerIsBetter
            unit="s"
          />
          <MetricCard
            label="Avg Queue Length"
            value={latestProgress.avg_queue_length}
            baseline={latestProgress.baseline_avg_queue_length}
            lowerIsBetter
          />
          <MetricCard
            label="Throughput"
            value={latestProgress.throughput}
            baseline={latestProgress.baseline_throughput}
          />
          <MetricCard
            label="Mean Reward"
            value={latestProgress.mean_reward}
          />
        </div>

        {/* Chart */}
        <div className="flex-1 min-w-0">
          <TrainingChart data={progressHistory} />
        </div>
      </div>
    </div>
  );
}
