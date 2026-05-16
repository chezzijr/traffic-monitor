import { useEffect, useState } from 'react';
import { Activity, Package, Monitor } from 'lucide-react';
import { useModelStore } from '../../store/modelStore';
import { digitalTwinDeployService } from '../../services/digitalTwinDeployService';

export function Header() {
  const togglePanel = useModelStore((s) => s.togglePanel);
  const modelCount = useModelStore((s) => s.models.length);
  const deploymentCount = useModelStore((s) => s.deployments.length);

  // Live deploy status — gives the user at-a-glance verification that the
  // simulation is actually stepping. Without this they have to open
  // /simulation/view or click a purple marker to know whether the deploy is
  // alive (the screenshot review surfaced this gap).
  const [liveStep, setLiveStep] = useState<number | null>(null);
  const [liveRunning, setLiveRunning] = useState(false);
  const [liveTlCount, setLiveTlCount] = useState<number>(0);
  const [liveHealth, setLiveHealth] = useState<string>('idle');
  const [liveVehicles, setLiveVehicles] = useState<number>(0);

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const snap = await digitalTwinDeployService.getSnapshot();
        if (cancelled) return;
        setLiveStep(snap.step ?? 0);
        setLiveRunning(!!snap.running);
        setLiveTlCount((snap.controlled_tl_ids ?? []).length);
        setLiveHealth(((snap as { health?: string }).health) ?? 'idle');
        setLiveVehicles(snap.metrics?.num_vehicles ?? 0);
      } catch {
        if (!cancelled) {
          setLiveRunning(false);
          setLiveHealth('offline');
        }
      }
    };
    poll();
    const id = window.setInterval(poll, 1500);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  const healthColor =
    liveHealth === 'error' ? 'text-red-600 border-red-300 bg-red-50' :
    liveHealth === 'offline' ? 'text-gray-400 border-gray-200 bg-gray-50' :
    liveRunning ? 'text-green-700 border-green-300 bg-green-50' :
    'text-gray-500 border-gray-200 bg-gray-50';

  return (
    <header className="h-12 bg-white border-b px-4 flex items-center justify-between">
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2 text-sm text-gray-600">
          <Activity size={16} />
          <a href="/" className="hover:text-gray-900 transition-colors">
            HCMC Traffic Light Optimization
          </a>
        </div>

      </div>
      <div className="flex items-center gap-2">
        {/* At-a-glance deploy status: confirms simulation is stepping without
            requiring a /simulation/view trip or marker click. */}
        {(liveRunning || deploymentCount > 0) && (
          <div
            className={`flex items-center gap-2 px-2.5 py-1 text-[11px] rounded-lg border ${healthColor}`}
            title={`Deploy health: ${liveHealth}`}
          >
            <span className={`inline-block w-2 h-2 rounded-full ${liveRunning && liveHealth === 'ok' ? 'bg-green-500 animate-pulse' : liveHealth === 'error' ? 'bg-red-500' : 'bg-gray-400'}`} />
            <span className="font-medium">
              {liveRunning ? (liveHealth === 'error' ? 'Error' : 'Live') : 'Idle'}
            </span>
            {liveRunning && (
              <>
                <span className="text-gray-400">·</span>
                <span className="font-mono">step {liveStep ?? 0}</span>
                <span className="text-gray-400">·</span>
                <span className="font-mono">{liveTlCount} TL</span>
                <span className="text-gray-400">·</span>
                <span className="font-mono">{liveVehicles} veh</span>
              </>
            )}
          </div>
        )}
        <a
          href="/simulation/view"
          className="flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-lg border border-gray-200 hover:bg-gray-50 transition-colors text-gray-700"
          title="Open SUMO simulation debug view"
        >
          <Monitor size={14} />
          Live Debug View
          {deploymentCount > 0 && (
            <span className="bg-purple-500 text-white text-[10px] px-1.5 py-0.5 rounded-full font-medium">
              {deploymentCount}
            </span>
          )}
        </a>
        <button
          onClick={togglePanel}
          className="flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-lg border border-gray-200 hover:bg-gray-50 transition-colors text-gray-700"
        >
          <Package size={14} />
          Models
          {modelCount > 0 && (
            <span className="bg-blue-500 text-white text-[10px] px-1.5 py-0.5 rounded-full font-medium">
              {modelCount}
            </span>
          )}
        </button>
      </div>
    </header>
  );
}
