import { MapPin } from 'lucide-react';
import { useMapStore } from '../../store/mapStore';
import { useTrainingStore } from '../../store/trainingStore';
import { useModelStore } from '../../store/modelStore';

interface SidebarProps {
  children: React.ReactNode;
}

export function Sidebar({ children }: SidebarProps) {
  const { selectionMode, setSelectionMode, currentNetworkId, networkSource, reset } = useMapStore();
  const tasks = useTrainingStore((s) => s.tasks);
  const deployments = useModelStore((s) => s.deployments);

  const hasRunningTraining = tasks.some(
    (t) => t.status === 'running' || t.status === 'queued',
  );
  const hasActiveDeploy = deployments.length > 0;

  // Entering region-selection re-points the map. If a training run or a
  // deployment is live, confirm — it keeps running in the background and
  // stays reachable from the activity status bar.
  const handleToggleSelection = () => {
    if (!selectionMode && (hasRunningTraining || hasActiveDeploy)) {
      const what =
        hasRunningTraining && hasActiveDeploy
          ? 'A training run and a deployment are'
          : hasRunningTraining
            ? 'A training run is'
            : 'A deployment is';
      if (
        !window.confirm(
          `${what} still active. It keeps running in the background (see the status bar). Switch the map to select a new region?`,
        )
      ) {
        return;
      }
    }
    setSelectionMode(!selectionMode);
  };

  // "New Region" wipes the training map context. The backend task is NOT
  // stopped — confirm so the user knows it keeps running.
  const handleNewRegion = () => {
    if (
      hasRunningTraining &&
      !window.confirm(
        'A training run is still active — this will not stop it. Clear the map anyway?',
      )
    ) {
      return;
    }
    reset();
  };

  return (
    <aside className="w-80 bg-gray-50 border-r overflow-y-auto flex flex-col">
      <div className="p-4 border-b">
        <h1 className="text-xl font-bold flex items-center gap-2">
          <MapPin className="text-blue-500" />
          Traffic Monitor
        </h1>
      </div>

      <div className="p-4 border-b">
        <button
          onClick={handleToggleSelection}
          className={`w-full px-4 py-2 rounded font-medium transition-colors ${
            selectionMode
              ? 'bg-blue-500 text-white'
              : 'bg-white border border-gray-300 hover:bg-gray-50'
          }`}
        >
          {selectionMode ? 'Cancel Selection' : 'Select Region'}
        </button>
        {/* Training-only: in deploy mode there is no training network to
            discard, and a bare reset() would just be re-seeded from the
            active deployment. Use "Select Region" to start a fresh region. */}
        {currentNetworkId && networkSource === 'training' && (
          <div className="mt-2 flex items-center justify-between gap-2">
            <p className="text-sm text-gray-500 truncate flex-1">
              Network: {currentNetworkId}
            </p>
            <button
              onClick={handleNewRegion}
              className="text-xs text-red-500 hover:text-red-700 whitespace-nowrap"
            >
              New Region
            </button>
          </div>
        )}
      </div>

      <div className="flex-1 p-4 space-y-4">
        {children}
      </div>
    </aside>
  );
}
