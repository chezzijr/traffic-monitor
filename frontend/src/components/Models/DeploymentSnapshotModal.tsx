import { useEffect, useMemo, useRef, useState } from 'react';
import { X, Loader } from 'lucide-react';
import { deploymentService, type DeploymentSnapshot } from '../../services/deploymentService';

interface DeploymentSnapshotModalProps {
  tlId: string | null;
  onClose: () => void;
}

export function DeploymentSnapshotModal({ tlId, onClose }: DeploymentSnapshotModalProps) {
  const [snapshot, setSnapshot] = useState<DeploymentSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (!tlId) return;

    const fetchSnapshot = async () => {
      try {
        const data = await deploymentService.getSnapshot(tlId);
        setSnapshot(data);
        setError(null);
      } catch (err: unknown) {
        const anyErr = err as { response?: { data?: { detail?: string } } };
        const detail = anyErr?.response?.data?.detail;
        const msg = detail || (err instanceof Error ? err.message : 'Failed to load snapshot');
        setError(msg);
      }
    };

    fetchSnapshot();
    intervalRef.current = setInterval(fetchSnapshot, 1000);

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [tlId]);

  const vehicleRows = useMemo(() => {
    if (!snapshot?.vehicles) return [];
    return snapshot.vehicles.slice(0, 20);
  }, [snapshot?.vehicles]);

  if (!tlId) return null;

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-[1500]">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between p-4 border-b">
          <div>
            <h3 className="text-sm font-semibold text-gray-800">Deployment Snapshot</h3>
            <p className="text-xs text-gray-500">TL: {tlId}</p>
          </div>
          <button onClick={onClose} className="p-1 rounded hover:bg-gray-100">
            <X size={18} />
          </button>
        </div>

        <div className="p-4 space-y-4">
          {error && (
            <div className="text-xs text-red-600 bg-red-50 border border-red-100 rounded p-2">
              {error}
            </div>
          )}

          {!snapshot && !error && (
            <div className="flex items-center gap-2 text-xs text-gray-500">
              <Loader size={14} className="animate-spin" />
              Loading snapshot...
            </div>
          )}

          {snapshot && (
            <>
              <div className="grid grid-cols-2 gap-3">
                <div className="border border-gray-200 rounded p-3">
                  <p className="text-[10px] text-gray-500">Vehicles</p>
                  <p className="text-lg font-semibold text-gray-800">{snapshot.vehicle_count}</p>
                </div>
                <div className="border border-gray-200 rounded p-3">
                  <p className="text-[10px] text-gray-500">Waiting</p>
                  <p className="text-lg font-semibold text-gray-800">{snapshot.waiting_count}</p>
                </div>
                <div className="border border-gray-200 rounded p-3">
                  <p className="text-[10px] text-gray-500">Phase</p>
                  <p className="text-sm font-mono text-gray-700">{snapshot.phase}</p>
                </div>
                <div className="border border-gray-200 rounded p-3">
                  <p className="text-[10px] text-gray-500">State</p>
                  <p className="text-sm font-mono text-gray-700">{snapshot.state}</p>
                </div>
              </div>

              <div className="border border-gray-200 rounded">
                <div className="px-3 py-2 border-b text-[10px] text-gray-500 uppercase tracking-wider">
                  Vehicles (top 20)
                </div>
                {vehicleRows.length === 0 ? (
                  <div className="p-3 text-xs text-gray-400">No vehicles in controlled lanes.</div>
                ) : (
                  <div className="divide-y">
                    {vehicleRows.map((v) => (
                      <div key={v.id} className="px-3 py-2 text-xs text-gray-700 flex items-center justify-between">
                        <span className="font-mono">{v.id}</span>
                        <span className="text-gray-500">speed: {v.speed.toFixed(2)} m/s</span>
                        <span className="text-gray-500">wait: {v.waiting_time.toFixed(1)} s</span>
                        <span className="text-gray-400">lane: {v.lane_id}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
