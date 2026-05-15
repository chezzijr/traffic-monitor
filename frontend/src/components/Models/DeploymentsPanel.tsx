import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Zap, ZapOff, XCircle, Eye, Square } from 'lucide-react';
import toast from 'react-hot-toast';
import { useModelStore } from '../../store/modelStore';
import { deploymentService } from '../../services/deploymentService';
import { modelService } from '../../services/modelService';
import { digitalTwinDeployService } from '../../services/digitalTwinDeployService';

export function DeploymentsPanel() {
  const navigate = useNavigate();
  const deployments = useModelStore((s) => s.deployments);
  const setDeployments = useModelStore((s) => s.setDeployments);
  const removeDeployment = useModelStore((s) => s.removeDeployment);
  const clearDeployments = useModelStore((s) => s.clearDeployments);
  const [stoppingAll, setStoppingAll] = useState(false);

  // Real agent state comes from the digital twin service, not the stale backend store
  const [agentEnabled, setAgentEnabled] = useState(true);
  const [toggling, setToggling] = useState(false);

  useEffect(() => {
    deploymentService.listDeployments()
      .then(setDeployments)
      .catch(() => toast.error('Failed to load deployments'));
  }, [setDeployments]);

  useEffect(() => {
    digitalTwinDeployService.getStatus()
      .then((s) => setAgentEnabled(s.agent_enabled ?? true))
      .catch(() => {}); // digital twin might not be running yet
  }, []);

  const handleToggle = async () => {
    setToggling(true);
    try {
      const result = await digitalTwinDeployService.toggleAgent(!agentEnabled);
      setAgentEnabled(result.agent_enabled);
      toast.success(`AI control ${result.agent_enabled ? 'enabled' : 'disabled'}`);
    } catch {
      toast.error('Failed to toggle AI control');
    } finally {
      setToggling(false);
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

  const handleView = () => {
    navigate('/simulation/view');
  };

  const handleStopAll = async () => {
    if (deployments.length === 0) return;
    if (!window.confirm(`Stop the entire deploy? This will stop the Digital Twin simulation and clear all ${deployments.length} deployment(s).`)) {
      return;
    }
    setStoppingAll(true);
    try {
      const result = await deploymentService.stopAll();
      clearDeployments();
      if (result.error) {
        toast.error(`Stopped with error: ${result.error}`);
      } else {
        toast.success('All deployments stopped');
      }
    } catch {
      toast.error('Failed to stop all deployments');
    } finally {
      setStoppingAll(false);
    }
  };

  return (
    <div className="p-4 border-t border-gray-200">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-base font-semibold text-gray-800 flex items-center gap-2">
          <Zap size={18} />
          Active Deployments
        </h2>
        {deployments.length > 0 && (
          <button
            onClick={handleStopAll}
            disabled={stoppingAll}
            className="flex items-center gap-1 text-xs px-2.5 py-1 rounded bg-red-600 text-white hover:bg-red-700 transition-colors disabled:opacity-50"
            title="Stop the entire DT simulation and clear all deployments"
          >
            <Square size={12} />
            {stoppingAll ? 'Stopping…' : 'Stop All'}
          </button>
        )}
      </div>

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
                <span className="text-[10px] text-gray-400">{dep.network_id?.slice(0, 8) ?? '—'}</span>
              </div>

              <div className="flex items-center justify-between">
                <button
                  onClick={handleToggle}
                  disabled={toggling}
                  className={`flex items-center gap-1 text-xs px-2 py-1 rounded transition-colors disabled:opacity-50 ${
                    agentEnabled
                      ? 'bg-green-100 text-green-700'
                      : 'bg-gray-100 text-gray-500'
                  }`}
                >
                  {agentEnabled ? <Zap size={12} /> : <ZapOff size={12} />}
                  {agentEnabled ? 'AI On' : 'AI Off'}
                </button>

                <button
                  onClick={handleView}
                  className="flex items-center gap-1 text-xs px-2 py-1 rounded bg-blue-50 text-blue-600 hover:bg-blue-100 transition-colors"
                  title="View simulation"
                >
                  <Eye size={12} />
                  View
                </button>

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
