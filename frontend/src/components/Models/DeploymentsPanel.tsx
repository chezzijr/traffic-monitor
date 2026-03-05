import { useEffect } from 'react';
import { Zap, ZapOff, XCircle } from 'lucide-react';
import toast from 'react-hot-toast';
import { useModelStore } from '../../store/modelStore';
import { deploymentService } from '../../services/deploymentService';
import { modelService } from '../../services/modelService';

export function DeploymentsPanel() {
  const deployments = useModelStore((s) => s.deployments);
  const setDeployments = useModelStore((s) => s.setDeployments);
  const removeDeployment = useModelStore((s) => s.removeDeployment);

  useEffect(() => {
    deploymentService.listDeployments()
      .then(setDeployments)
      .catch(() => toast.error('Failed to load deployments'));
  }, [setDeployments]);

  const handleToggle = async (tlId: string, enabled: boolean) => {
    try {
      await deploymentService.toggleAIControl(tlId, enabled);
      const current = useModelStore.getState().deployments;
      setDeployments(
        current.map((d) =>
          d.tl_id === tlId ? { ...d, ai_control_enabled: enabled } : d
        )
      );
      toast.success(`AI control ${enabled ? 'enabled' : 'disabled'} for ${tlId}`);
    } catch {
      toast.error('Failed to toggle AI control');
    }
  };

  const handleUndeploy = async (tlId: string) => {
    try {
      await modelService.undeployModel(tlId);
      removeDeployment(tlId);
      toast.success(`Model undeployed from ${tlId}`);
    } catch {
      toast.error('Failed to undeploy model');
    }
  };

  return (
    <div className="p-4 border-t border-gray-200">
      <h2 className="text-base font-semibold text-gray-800 flex items-center gap-2 mb-4">
        <Zap size={18} />
        Active Deployments
      </h2>

      {deployments.length === 0 ? (
        <p className="text-sm text-gray-400 text-center py-4">
          No active deployments.
        </p>
      ) : (
        <div className="space-y-2">
          {deployments.map((dep) => (
            <div
              key={dep.tl_id}
              className="border border-gray-200 rounded-lg p-3 bg-white"
            >
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-mono text-gray-700">{dep.tl_id}</span>
                <span className="text-[10px] text-gray-400">{dep.network_id.slice(0, 8)}...</span>
              </div>

              <div className="flex items-center justify-between">
                {/* AI Control toggle */}
                <button
                  onClick={() => handleToggle(dep.tl_id, !dep.ai_control_enabled)}
                  className={`flex items-center gap-1 text-xs px-2 py-1 rounded transition-colors ${
                    dep.ai_control_enabled
                      ? 'bg-green-100 text-green-700'
                      : 'bg-gray-100 text-gray-500'
                  }`}
                >
                  {dep.ai_control_enabled ? <Zap size={12} /> : <ZapOff size={12} />}
                  {dep.ai_control_enabled ? 'AI On' : 'AI Off'}
                </button>

                {/* Undeploy button */}
                <button
                  onClick={() => handleUndeploy(dep.tl_id)}
                  className="flex items-center gap-1 text-xs px-2 py-1 rounded bg-red-50 text-red-500 hover:bg-red-100 transition-colors"
                  title="Undeploy"
                >
                  <XCircle size={12} />
                  Undeploy
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
