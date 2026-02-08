import { useState, useEffect } from 'react';
import { Database, Trash2, Upload, RefreshCw } from 'lucide-react';
import { useMLStore } from '../../store/mlStore';
import { useMapStore } from '../../store/mapStore';
import { mlService } from '../../services/mlService';
import type { ModelInfo } from '../../types/ml';

export function ModelsPanel() {
  const [isLoading, setIsLoading] = useState(false);
  const [deployingModelId, setDeployingModelId] = useState<string | null>(null);
  const [selectedTlId, setSelectedTlId] = useState('');

  const { models, setModels, removeModel, setError, isLoadingModels, setLoadingModels } = useMLStore();
  const intersections = useMapStore((state) => state.intersections);

  // Get traffic lights from intersections
  const trafficLights = intersections.filter((i) => i.has_traffic_light && i.sumo_tl_id);

  // Load models on mount
  useEffect(() => {
    loadModels();
  }, []);

  const loadModels = async () => {
    setLoadingModels(true);
    try {
      const data = await mlService.listModels();
      setModels(data);
    } catch (error) {
      setError(error instanceof Error ? error.message : 'Failed to load models');
    } finally {
      setLoadingModels(false);
    }
  };

  const handleDelete = async (model: ModelInfo) => {
    if (!confirm(`Delete model ${model.id}?`)) return;

    setIsLoading(true);
    try {
      await mlService.deleteModel(model.id);
      removeModel(model.id);
    } catch (error) {
      setError(error instanceof Error ? error.message : 'Failed to delete model');
    } finally {
      setIsLoading(false);
    }
  };

  const handleDeploy = async (model: ModelInfo) => {
    if (!selectedTlId) {
      setError('Select a traffic light to deploy to');
      return;
    }

    setIsLoading(true);
    try {
      await mlService.deployModel(model.id, selectedTlId);
      setDeployingModelId(null);
      setSelectedTlId('');
      // Refresh deployments in parent
    } catch (error) {
      setError(error instanceof Error ? error.message : 'Failed to deploy model');
    } finally {
      setIsLoading(false);
    }
  };

  const formatBytes = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const formatDate = (isoString: string) => {
    return new Date(isoString).toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  return (
    <div className="bg-white rounded-lg shadow p-4">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold flex items-center gap-2">
          <Database size={20} />
          Models
        </h3>
        <button
          onClick={loadModels}
          disabled={isLoadingModels}
          className="p-2 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded"
          title="Refresh"
        >
          <RefreshCw size={16} className={isLoadingModels ? 'animate-spin' : ''} />
        </button>
      </div>

      {isLoadingModels && models.length === 0 ? (
        <p className="text-sm text-gray-500">Loading models...</p>
      ) : models.length === 0 ? (
        <p className="text-sm text-gray-500">No trained models yet</p>
      ) : (
        <div className="space-y-3">
          {models.map((model) => (
            <div
              key={model.id}
              className="border rounded-lg p-3"
            >
              <div className="flex items-start justify-between">
                <div className="flex-1 min-w-0">
                  <p className="font-medium text-sm truncate">{model.id}</p>
                  <p className="text-xs text-gray-500">
                    {model.algorithm.toUpperCase()} | {formatBytes(model.size_bytes)}
                  </p>
                  <p className="text-xs text-gray-500">
                    TL: {model.tl_id} | {formatDate(model.created_at)}
                  </p>
                </div>
                <div className="flex gap-1">
                  <button
                    onClick={() => setDeployingModelId(deployingModelId === model.id ? null : model.id)}
                    disabled={isLoading}
                    className="p-2 text-blue-500 hover:bg-blue-50 rounded"
                    title="Deploy"
                  >
                    <Upload size={16} />
                  </button>
                  <button
                    onClick={() => handleDelete(model)}
                    disabled={isLoading}
                    className="p-2 text-red-500 hover:bg-red-50 rounded"
                    title="Delete"
                  >
                    <Trash2 size={16} />
                  </button>
                </div>
              </div>

              {/* Deploy panel */}
              {deployingModelId === model.id && (
                <div className="mt-3 pt-3 border-t">
                  <label className="block text-xs font-medium text-gray-700 mb-1">
                    Deploy to Traffic Light
                  </label>
                  <div className="flex gap-2">
                    <select
                      value={selectedTlId}
                      onChange={(e) => setSelectedTlId(e.target.value)}
                      className="flex-1 px-2 py-1 text-sm border border-gray-300 rounded focus:outline-none focus:ring-1 focus:ring-blue-500"
                    >
                      <option value="">Select TL</option>
                      {trafficLights.map((tl) => (
                        <option key={tl.sumo_tl_id} value={tl.sumo_tl_id}>
                          {tl.sumo_tl_id}
                        </option>
                      ))}
                    </select>
                    <button
                      onClick={() => handleDeploy(model)}
                      disabled={isLoading || !selectedTlId}
                      className="px-3 py-1 text-sm bg-blue-500 text-white rounded hover:bg-blue-600 disabled:opacity-50"
                    >
                      Deploy
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
