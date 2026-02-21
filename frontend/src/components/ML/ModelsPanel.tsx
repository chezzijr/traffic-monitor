import { useState, useEffect, useMemo } from 'react';
import { Database, Trash2, Upload, RefreshCw, Filter } from 'lucide-react';
import { useMLStore } from '../../store/mlStore';
import { useMapStore } from '../../store/mapStore';
import { mlService } from '../../services/mlService';
import type { ModelInfo } from '../../types/ml';

/** Format a network_id to its first 8 characters for display. */
function abbreviateNetworkId(networkId: string): string {
  return networkId.length > 8 ? networkId.slice(0, 8) : networkId;
}

/** Render the TL identifier text for a model, handling multi-junction. */
function formatTlLabel(model: ModelInfo): string {
  if (model.mode === 'multi_junction' && model.tl_ids && model.tl_ids.length > 0) {
    return `Multi-junction (${model.tl_ids.length} TLs)`;
  }
  return model.tl_id;
}

export function ModelsPanel() {
  const [isLoading, setIsLoading] = useState(false);
  const [deployingModelId, setDeployingModelId] = useState<string | null>(null);
  const [selectedTlId, setSelectedTlId] = useState('');
  const [networkFilter, setNetworkFilter] = useState<string>('all');

  const { models, setModels, removeModel, setError, isLoadingModels, setLoadingModels } = useMLStore();
  const intersections = useMapStore((state) => state.intersections);

  // Get traffic lights from intersections
  const trafficLights = intersections.filter((i) => i.has_traffic_light && i.sumo_tl_id);

  // Derive unique network IDs from models
  const networkIds = useMemo(() => {
    const ids = new Set(models.map((m) => m.network_id));
    return Array.from(ids).sort();
  }, [models]);

  // Filter models by selected network
  const filteredModels = useMemo(() => {
    if (networkFilter === 'all') return models;
    return models.filter((m) => m.network_id === networkFilter);
  }, [models, networkFilter]);

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

      {/* Network filter - only shown when multiple networks have models */}
      {networkIds.length > 1 && (
        <div className="flex items-center gap-2 mb-3">
          <Filter size={14} className="text-gray-400 shrink-0" />
          <select
            value={networkFilter}
            onChange={(e) => setNetworkFilter(e.target.value)}
            className="flex-1 px-2 py-1 text-xs border border-gray-300 rounded focus:outline-none focus:ring-1 focus:ring-blue-500"
          >
            <option value="all">All Networks ({models.length})</option>
            {networkIds.map((nid) => (
              <option key={nid} value={nid}>
                {abbreviateNetworkId(nid)} ({models.filter((m) => m.network_id === nid).length})
              </option>
            ))}
          </select>
        </div>
      )}

      {isLoadingModels && models.length === 0 ? (
        <p className="text-sm text-gray-500">Loading models...</p>
      ) : models.length === 0 ? (
        <p className="text-sm text-gray-500">No trained models yet</p>
      ) : filteredModels.length === 0 ? (
        <p className="text-sm text-gray-500">No models for selected network</p>
      ) : (
        <div className="space-y-3">
          {filteredModels.map((model) => (
            <div
              key={model.id}
              className="border rounded-lg p-3"
            >
              <div className="flex items-start justify-between">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <p className="font-medium text-sm">{model.algorithm.toUpperCase()} Model</p>
                    <span
                      className="inline-block px-1.5 py-0.5 text-[10px] font-mono bg-gray-100 text-gray-600 rounded"
                      title={model.network_id}
                    >
                      {abbreviateNetworkId(model.network_id)}
                    </span>
                  </div>
                  <p className="text-xs text-gray-500">
                    TL: {formatTlLabel(model)} · {formatDate(model.created_at)} · {formatBytes(model.size_bytes)}
                  </p>
                  <p className="text-xs text-gray-400 truncate" title={model.id}>
                    {model.id}
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
