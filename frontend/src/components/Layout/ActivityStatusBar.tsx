import { Cpu, Activity } from 'lucide-react';
import { useModelStore } from '../../store/modelStore';
import { useTrainingStore } from '../../store/trainingStore';

interface ActivityStatusBarProps {
  /** Open the training progress drawer for a given task. */
  onViewTraining?: (taskId: string) => void;
}

/**
 * Always-visible strip showing the two long-lived activities — a training run
 * and a deployment — so neither is ever lost when the map context switches
 * between training and deploy. Renders nothing when both are idle.
 */
export function ActivityStatusBar({ onViewTraining }: ActivityStatusBarProps) {
  const deployments = useModelStore((s) => s.deployments);
  const togglePanel = useModelStore((s) => s.togglePanel);
  const isPanelOpen = useModelStore((s) => s.isPanelOpen);
  const tasks = useTrainingStore((s) => s.tasks);
  const liveProgress = useTrainingStore((s) => s.liveProgress);

  const runningTasks = tasks.filter((t) => t.status === 'running');
  const queuedCount = tasks.filter((t) => t.status === 'queued').length;
  const hasDeploy = deployments.length > 0;

  if (!hasDeploy && runningTasks.length === 0 && queuedCount === 0) return null;

  const deployTlCount = deployments.reduce(
    (n, d) => n + (d.tl_ids && d.tl_ids.length > 0 ? d.tl_ids.length : 1),
    0,
  );
  const deployNetwork = deployments[0]?.network_id;

  return (
    <div className="flex items-center gap-2 px-4 py-1.5 bg-slate-50 border-b border-gray-200 text-[11px] shrink-0">
      <span className="text-gray-400 font-semibold uppercase tracking-wide">Active</span>

      {hasDeploy && (
        <button
          onClick={() => { if (!isPanelOpen) togglePanel(); }}
          className="flex items-center gap-1.5 px-2 py-0.5 rounded-full border border-purple-300 bg-purple-50 text-purple-700 hover:bg-purple-100 transition-colors"
          title="Manage in the Models panel"
        >
          <Cpu size={11} />
          <span className="font-medium">Deploy</span>
          <span className="text-purple-400">·</span>
          <span className="font-mono">{deployTlCount} TL</span>
          {deployNetwork && (
            <>
              <span className="text-purple-400">·</span>
              <span className="font-mono truncate max-w-[110px]">{deployNetwork}</span>
            </>
          )}
        </button>
      )}

      {runningTasks.map((t) => {
        const pct = Math.round(((liveProgress[t.task_id]?.progress ?? t.progress) || 0) * 100);
        return (
          <button
            key={t.task_id}
            onClick={() => onViewTraining?.(t.task_id)}
            className="flex items-center gap-1.5 px-2 py-0.5 rounded-full border border-blue-300 bg-blue-50 text-blue-700 hover:bg-blue-100 transition-colors"
            title="Open training progress"
          >
            <Activity size={11} />
            <span className="font-medium">Training {pct}%</span>
            {t.network_id && (
              <>
                <span className="text-blue-400">·</span>
                <span className="font-mono truncate max-w-[110px]">{t.network_id}</span>
              </>
            )}
          </button>
        );
      })}

      {queuedCount > 0 && (
        <span className="flex items-center gap-1 px-2 py-0.5 rounded-full border border-gray-300 bg-gray-50 text-gray-500">
          Queued ({queuedCount})
        </span>
      )}
    </div>
  );
}
