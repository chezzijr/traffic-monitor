import { useState, useEffect } from 'react';
import { Cpu, Power, XCircle, RefreshCw } from 'lucide-react';
import { useMLStore } from '../../store/mlStore';
import { mlService } from '../../services/mlService';

export function DeploymentPanel() {
  const [isLoading, setIsLoading] = useState(false);

  const { deployments, setDeployments, removeDeployment, updateDeployment, setError, isLoadingDeployments, setLoadingDeployments } = useMLStore();

  // Load deployments on mount
  useEffect(() => {
    loadDeployments();
  }, []);

  const loadDeployments = async () => {
    setLoadingDeployments(true);
    try {
      const data = await mlService.getDeployments();
      setDeployments(data);
    } catch (error) {
      setError(error instanceof Error ? error.message : 'Failed to load deployments');
    } finally {
      setLoadingDeployments(false);
    }
  };

  const handleToggleAI = async (tlId: string, currentEnabled: boolean) => {
    setIsLoading(true);
    try {
      const result = await mlService.toggleAIControl(tlId, !currentEnabled);
      updateDeployment(tlId, { ai_control_enabled: result.ai_control_enabled });
    } catch (error) {
      setError(error instanceof Error ? error.message : 'Failed to toggle AI control');
    } finally {
      setIsLoading(false);
    }
  };

  const handleUndeploy = async (modelId: string, tlId: string) => {
    if (!confirm(`Undeploy model from ${tlId}?`)) return;

    setIsLoading(true);
    try {
      await mlService.undeployModel(modelId);
      removeDeployment(tlId);
    } catch (error) {
      setError(error instanceof Error ? error.message : 'Failed to undeploy model');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="bg-white rounded-lg shadow p-4">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold flex items-center gap-2">
          <Cpu size={20} />
          Deployments
        </h3>
        <button
          onClick={loadDeployments}
          disabled={isLoadingDeployments}
          className="p-2 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded"
          title="Refresh"
        >
          <RefreshCw size={16} className={isLoadingDeployments ? 'animate-spin' : ''} />
        </button>
      </div>

      {isLoadingDeployments && deployments.length === 0 ? (
        <p className="text-sm text-gray-500">Loading deployments...</p>
      ) : deployments.length === 0 ? (
        <p className="text-sm text-gray-500">No active deployments</p>
      ) : (
        <div className="space-y-3">
          {deployments.map((deployment) => (
            <div
              key={deployment.tl_id}
              className={`border rounded-lg p-3 ${
                deployment.ai_control_enabled ? 'border-green-300 bg-green-50' : 'border-gray-200'
              }`}
            >
              <div className="flex items-center justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <span className={`w-2 h-2 rounded-full ${
                      deployment.ai_control_enabled ? 'bg-green-500' : 'bg-gray-400'
                    }`} />
                    <p className="font-medium text-sm">{deployment.tl_id}</p>
                  </div>
                  <p className="text-xs text-gray-500 mt-1">
                    Model: {deployment.model_id}
                  </p>
                </div>
                <div className="flex gap-1">
                  <button
                    onClick={() => handleToggleAI(deployment.tl_id, deployment.ai_control_enabled)}
                    disabled={isLoading}
                    className={`p-2 rounded ${
                      deployment.ai_control_enabled
                        ? 'text-green-600 hover:bg-green-100'
                        : 'text-gray-400 hover:bg-gray-100'
                    }`}
                    title={deployment.ai_control_enabled ? 'Disable AI' : 'Enable AI'}
                  >
                    <Power size={16} />
                  </button>
                  <button
                    onClick={() => handleUndeploy(deployment.model_id, deployment.tl_id)}
                    disabled={isLoading}
                    className="p-2 text-red-500 hover:bg-red-50 rounded"
                    title="Undeploy"
                  >
                    <XCircle size={16} />
                  </button>
                </div>
              </div>

              {deployment.ai_control_enabled && (
                <div className="mt-2 pt-2 border-t border-green-200">
                  <p className="text-xs text-green-700">
                    AI is controlling this traffic light
                  </p>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
