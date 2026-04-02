import { useState } from 'react';
import { ArrowDown, ArrowUp, CheckCircle, X } from 'lucide-react';
import { useTrainingStore } from '../../store/trainingStore';
import { useModelStore } from '../../store/modelStore';
import { taskService } from '../../services/taskService';
import { modelService } from '../../services/modelService';
import { TrainingChart } from './TrainingChart';
import toast from 'react-hot-toast';
import type { TrainingProgressEvent, TrainingCompletionEvent } from '../../types';

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
          {baseline != null && baseline !== 0 && !(lowerIsBetter && baseline < 1.0) && (
            <span className="text-gray-400 ml-0.5">
              ({Math.abs((delta / baseline) * 100).toFixed(0)}%)
            </span>
          )}
        </div>
      )}
    </div>
  );
}

interface CompletionSummaryProps {
  completion: TrainingCompletionEvent;
  progressHistory: TrainingProgressEvent[];
  onDismiss: () => void;
}

function CompletionSummary({ completion, progressHistory, onDismiss }: CompletionSummaryProps) {
  const [deploying, setDeploying] = useState(false);
  const addDeployment = useModelStore((s) => s.addDeployment);

  const modelFilename = completion.model_path.split('/').pop() || completion.model_path;
  const junctionId = completion.tl_id || (completion.tl_ids ? completion.tl_ids.join(', ') : '—');

  const handleDeploy = async () => {
    setDeploying(true);
    try {
      const deployment = await modelService.deployModel({
        tl_id: completion.tl_id || (completion.tl_ids ? completion.tl_ids[0] : ''),
        model_path: completion.model_path,
        network_id: completion.network_id,
      });
      addDeployment(deployment);
      toast.success('Model deployed successfully');
    } catch {
      toast.error('Failed to deploy model');
    } finally {
      setDeploying(false);
    }
  };

  return (
    <div className="h-full flex flex-col gap-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <CheckCircle size={18} className="text-green-600" />
          <h3 className="text-sm font-semibold text-green-700">Training Complete</h3>
        </div>
        <button
          onClick={onDismiss}
          className="p-1 rounded hover:bg-gray-100 transition-colors"
        >
          <X size={14} className="text-gray-500" />
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 flex gap-4 min-h-0">
        {/* Model Info */}
        <div className="flex flex-col gap-2 w-52 shrink-0">
          <div className="bg-green-50 rounded-lg p-3">
            <p className="text-[10px] text-gray-500 uppercase tracking-wider mb-2">Model Info</p>
            <div className="space-y-1.5 text-xs">
              <div>
                <span className="text-gray-500">Network: </span>
                <span className="font-mono text-gray-700">{completion.network_id.slice(0, 10)}...</span>
              </div>
              <div>
                <span className="text-gray-500">Junction: </span>
                <span className="font-mono text-gray-700">{junctionId.length > 14 ? junctionId.slice(0, 14) + '...' : junctionId}</span>
              </div>
              <div>
                <span className="text-gray-500">Algorithm: </span>
                <span className="font-semibold text-gray-700 uppercase">{completion.algorithm}</span>
              </div>
              <div>
                <span className="text-gray-500">Model: </span>
                <span className="font-mono text-gray-700">{modelFilename.length > 14 ? '...' + modelFilename.slice(-14) : modelFilename}</span>
              </div>
            </div>
          </div>

          {/* Final metrics */}
          <MetricCard
            label="Avg Waiting Time"
            value={completion.avg_waiting_time}
            baseline={completion.baseline_avg_waiting_time}
            lowerIsBetter
            unit="s"
          />
          <MetricCard
            label="Avg Queue Length"
            value={completion.avg_queue_length}
            baseline={completion.baseline_avg_queue_length}
            lowerIsBetter
          />
          <MetricCard
            label="Throughput"
            value={completion.throughput}
            baseline={completion.baseline_throughput}
          />
          <MetricCard
            label="Mean Reward"
            value={completion.mean_reward}
          />
        </div>

        {/* Chart + Actions */}
        <div className="flex-1 flex flex-col min-w-0 gap-3">
          <div className="flex-1 min-h-0">
            <TrainingChart data={progressHistory} />
          </div>
          <div className="flex gap-2 justify-end">
            <button
              onClick={handleDeploy}
              disabled={deploying}
              className="px-4 py-1.5 text-xs font-medium rounded bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 transition-colors"
            >
              {deploying ? 'Deploying...' : 'Deploy'}
            </button>
            <button
              onClick={onDismiss}
              className="px-4 py-1.5 text-xs font-medium rounded bg-gray-100 text-gray-700 hover:bg-gray-200 transition-colors"
            >
              Dismiss
            </button>
          </div>
        </div>
      </div>
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
  const completion = useTrainingStore((s) =>
    s.activeTaskId ? s.completions[s.activeTaskId] ?? null : null
  );
  const dismissCompletion = useTrainingStore((s) => s.dismissCompletion);

  // Show completion summary if task is complete
  if (activeTaskId && completion) {
    return (
      <CompletionSummary
        completion={completion}
        progressHistory={progressHistory}
        onDismiss={() => dismissCompletion(activeTaskId)}
      />
    );
  }

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
