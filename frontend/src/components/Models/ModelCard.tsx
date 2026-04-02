import { Trash2, Rocket, ChevronDown, ChevronUp } from 'lucide-react';
import type { TrainedModel, TrainingProgressEvent } from '../../types';
import { MetricsComparisonTable } from './MetricsComparisonTable';
import { ModelMap } from './ModelMap';
import { TrainingChart } from '../Training/TrainingChart';

interface ModelCardProps {
  model: TrainedModel;
  isExpanded: boolean;
  onToggleExpand: () => void;
  onDeploy: (model: TrainedModel) => void;
  onDelete: (modelId: string) => void;
}

function deltaPercent(baseline: number, trained: number, lowerIsBetter = false): number | null {
  if (baseline === 0 || (lowerIsBetter && baseline < 1.0)) return null;
  return ((trained - baseline) / baseline) * 100;
}

export function ModelCard({ model, isExpanded, onToggleExpand, onDeploy, onDelete }: ModelCardProps) {
  const algColor = model.algorithm === 'dqn' ? 'bg-green-100 text-green-700' : 'bg-purple-100 text-purple-700';
  const results = model.results;
  const isMulti = model.type === 'multi' || (model.tl_ids && model.tl_ids.length > 1);
  const trainedJunctionIds = model.tl_ids ?? [model.tl_id];

  const waitDelta = results ? deltaPercent(results.baseline.avg_waiting_time, results.trained.avg_waiting_time, true) : null;
  const queueDelta = results ? deltaPercent(results.baseline.avg_queue_length, results.trained.avg_queue_length, true) : null;
  const throughputDelta = results ? deltaPercent(results.baseline.throughput, results.trained.throughput) : null;

  const chartData: TrainingProgressEvent[] = results
    ? results.progress_history.map((p) => ({
        task_id: '',
        status: 'completed',
        timestep: p.timestep,
        total_timesteps: results.training_config.total_timesteps,
        progress: 0,
        episode_count: 0,
        mean_reward: p.mean_reward,
        avg_waiting_time: p.avg_waiting_time,
        avg_queue_length: 0,
        throughput: p.throughput,
      }))
    : [];

  return (
    <div className="border border-gray-200 rounded-lg bg-white">
      {/* Collapsed state - always shown */}
      <div className="p-3">
        <div className="flex items-start justify-between">
          <div className="flex-1 min-w-0">
            {/* Top row: algorithm badge + date */}
            <div className="flex items-center justify-between mb-2">
              <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium uppercase ${algColor}`}>
                {model.algorithm}
              </span>
              <span className="text-[10px] text-gray-400">
                {model.created_at ? new Date(model.created_at).toLocaleDateString() : 'N/A'}
              </span>
            </div>

            {/* Junction info */}
            <div className="flex items-center gap-1.5 mb-1">
              <p className="text-xs font-mono text-gray-700 truncate" title={model.tl_id}>
                {isMulti
                  ? `${model.tl_ids?.length ?? 0} Junctions`
                  : `Junction: ${model.tl_id}`}
              </p>
              {isMulti && (
                <span className="text-[9px] px-1 py-0.5 rounded bg-amber-100 text-amber-700 font-medium whitespace-nowrap">
                  Multi
                </span>
              )}
            </div>

            {/* Network */}
            <p className="text-[10px] text-gray-400 truncate mb-1" title={model.network_id}>
              Network: {model.network_id.slice(0, 12)}...
            </p>

            {/* Config line (only if results exist) */}
            {results && (
              <p className="text-[10px] text-gray-500 mb-1.5">
                {results.training_config.total_timesteps.toLocaleString()} steps &middot; {results.training_config.scenario}
              </p>
            )}

            {/* Metric deltas (only if results exist) */}
            {results && (
              <div className="flex items-center gap-2">
                {waitDelta !== null && (
                  <span className={`text-[10px] ${waitDelta < 0 ? 'text-green-600' : 'text-red-600'}`}>
                    Wait {waitDelta < 0 ? '\u25BC' : '\u25B2'}{Math.abs(waitDelta).toFixed(0)}%
                  </span>
                )}
                {queueDelta !== null && (
                  <span className={`text-[10px] ${queueDelta < 0 ? 'text-green-600' : 'text-red-600'}`}>
                    Queue {queueDelta < 0 ? '\u25BC' : '\u25B2'}{Math.abs(queueDelta).toFixed(0)}%
                  </span>
                )}
                {throughputDelta !== null && (
                  <span className={`text-[10px] ${throughputDelta > 0 ? 'text-green-600' : 'text-red-600'}`}>
                    Tput {throughputDelta > 0 ? '\u25B2' : '\u25BC'}{Math.abs(throughputDelta).toFixed(0)}%
                  </span>
                )}
              </div>
            )}
          </div>

          {/* Expand/collapse chevron */}
          <button
            onClick={onToggleExpand}
            className="ml-2 mt-0.5 p-1 rounded hover:bg-gray-100 text-gray-400 hover:text-gray-600 transition-colors"
            title={isExpanded ? 'Collapse' : 'Expand'}
          >
            {isExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </button>
        </div>
      </div>

      {/* Expanded state */}
      {isExpanded && (
        <div className="border-t border-gray-100 p-3 space-y-3">
          {results ? (
            <>
              <ModelMap networkId={model.network_id} trainedJunctionIds={trainedJunctionIds} />
              <MetricsComparisonTable baseline={results.baseline} trained={results.trained} />
              <div className="h-40">
                <TrainingChart data={chartData} />
              </div>
            </>
          ) : (
            <p className="text-xs text-gray-400 text-center py-4">
              No training results available
            </p>
          )}

          <div className="flex gap-2 pt-1">
            <button
              onClick={() => onDeploy(model)}
              className="flex-1 flex items-center justify-center gap-1 text-xs py-1.5 rounded bg-green-50 text-green-700 hover:bg-green-100 transition-colors"
            >
              <Rocket size={12} />
              Deploy
            </button>
            <button
              onClick={() => onDelete(model.model_id)}
              className="flex items-center justify-center px-2 py-1.5 rounded bg-red-50 text-red-500 hover:bg-red-100 transition-colors"
              title="Delete model"
            >
              <Trash2 size={12} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
