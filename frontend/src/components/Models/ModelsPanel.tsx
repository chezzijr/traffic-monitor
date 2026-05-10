import { useEffect, useMemo } from 'react';
import { Package } from 'lucide-react';
import toast from 'react-hot-toast';
import { useModelStore } from '../../store/modelStore';
import { modelService } from '../../services/modelService';
import { ModelCard } from './ModelCard';
import type { TrainedModel } from '../../types';
import { useMapStore } from '../../store/mapStore';

export function ModelsPanel() {
  const models = useModelStore((s) => s.models);
  const setModels = useModelStore((s) => s.setModels);
  const removeModel = useModelStore((s) => s.removeModel);
  const addDeployment = useModelStore((s) => s.addDeployment);
  const expandedModelId = useModelStore((s) => s.expandedModelId);
  const toggleExpandedModel = useModelStore((s) => s.toggleExpandedModel);
  const selectedDeployModelId = useModelStore((s) => s.selectedDeployModelId);
  const setSelectedDeployModelId = useModelStore((s) => s.setSelectedDeployModelId);
  const selectedDeployTlId = useModelStore((s) => s.selectedDeployTlId);
  const setSelectedDeployTlId = useModelStore((s) => s.setSelectedDeployTlId);

  const intersections = useMapStore((s) => s.intersections);
  const sumoTrafficLights = useMapStore((s) => s.sumoTrafficLights);
  const selectedJunctionIds = useMapStore((s) => s.selectedJunctionIds);
  const currentNetworkId = useMapStore((s) => s.currentNetworkId);

  useEffect(() => {
    modelService.listModels()
      .then(setModels)
      .catch(() => toast.error('Failed to load models'));
  }, [setModels]);

  const groupedModels = useMemo(() => {
    const groups: Record<string, TrainedModel[]> = {};
    for (const model of models) {
      const key = model.network_id;
      if (!groups[key]) groups[key] = [];
      groups[key].push(model);
    }
    return groups;
  }, [models]);

  const handleSelectModel = (model: TrainedModel) => {
    setSelectedDeployModelId(model.model_id);
    if (!selectedDeployTlId && model.tl_id) {
      setSelectedDeployTlId(model.tl_id);
    }
  };

  const selectedModel = useMemo(
    () => models.find((m) => m.model_id === selectedDeployModelId) || null,
    [models, selectedDeployModelId],
  );

  const tlOptions = useMemo(() => {
    const nameByTlId = new Map<string, string>();
    for (const inter of intersections) {
      if (inter.sumo_tl_id) {
        nameByTlId.set(inter.sumo_tl_id, inter.name || `Junction ${inter.sumo_tl_id}`);
      }
    }
    return sumoTrafficLights.map((tl) => ({
      id: tl.id,
      label: nameByTlId.get(tl.id) || `Junction ${tl.id}`,
    }));
  }, [intersections, sumoTrafficLights]);

  const handleDeploySelected = async () => {
    if (!selectedModel) {
      toast.error('Select a model first');
      return;
    }
    if (currentNetworkId && selectedModel.network_id !== currentNetworkId) {
      toast.error('Model network does not match the selected map network');
      return;
    }
    const isMulti = selectedModel.type === 'multi' || (selectedModel.tl_ids && selectedModel.tl_ids.length > 1);

    try {
      if (isMulti) {
        // Multi-agent: single deploy call — Digital Twin handles all TLs
        const primaryTlId = selectedModel.tl_ids?.[0] || selectedModel.tl_id || '';
        const result = await modelService.deployModel({
          tl_id: primaryTlId,
          model_path: selectedModel.model_path,
          network_id: selectedModel.network_id,
        });
        addDeployment(result);
        toast.success(`Deployed multi-agent model to ${selectedModel.tl_ids?.length || 1} intersection(s)`);
      } else {
        // Single-agent: deploy per selected TL
        const targetTlIds = selectedJunctionIds.length > 0
          ? selectedJunctionIds
          : (selectedDeployTlId ? [selectedDeployTlId] : []);

        if (targetTlIds.length === 0) {
          toast.error('Select intersections on the map or choose one in the list');
          return;
        }

        const results = await Promise.allSettled(
          targetTlIds.map((tlId) =>
            modelService.deployModel({
              tl_id: tlId,
              model_path: selectedModel.model_path,
              network_id: selectedModel.network_id,
            })
          )
        );
        const successes = results.filter((r) => r.status === 'fulfilled') as PromiseFulfilledResult<any>[];
        const failures = results.length - successes.length;

        successes.forEach((r) => addDeployment(r.value));

        if (failures > 0) {
          toast.error(`Deployed ${successes.length}, failed ${failures}`);
        } else {
          toast.success(`Deployed to ${successes.length} intersection(s)`);
        }
      }
    } catch {
      toast.error('Failed to deploy model');
    }
  };

  const isSelectedMulti = selectedModel && (selectedModel.type === 'multi' || (selectedModel.tl_ids && selectedModel.tl_ids.length > 1));
  const canDeploy = !!selectedModel
    && (selectedJunctionIds.length > 0 || !!selectedDeployTlId || (isSelectedMulti && (selectedModel.tl_ids?.length ?? 0) > 0))
    && (!currentNetworkId || selectedModel?.network_id === currentNetworkId);

  const handleDelete = async (modelId: string) => {
    try {
      await modelService.deleteModel(modelId);
      removeModel(modelId);
      toast.success('Model deleted');
    } catch {
      toast.error('Failed to delete model');
    }
  };

  const networkIds = Object.keys(groupedModels);

  return (
    <div className="p-4">
      <h2 className="text-base font-semibold text-gray-800 flex items-center gap-2 mb-4">
        <Package size={18} />
        Trained Models
      </h2>

      {models.length === 0 ? (
        <div className="text-center py-8 text-sm text-gray-400">
          <Package size={32} className="mx-auto mb-2 text-gray-300" />
          <p>No trained models yet.</p>
          <p className="text-xs mt-1">Start training to create models.</p>
        </div>
      ) : (
        <div className="space-y-4">
          <div className="border border-gray-200 rounded-lg p-3 bg-gray-50">
            <p className="text-xs text-gray-500 font-medium mb-2">Deploy Flow</p>
            <div className="space-y-2">
              <div className="text-xs text-gray-600">
                Selected model: <span className="font-mono text-gray-800">{selectedModel?.model_id || 'None'}</span>
              </div>
              {selectedModel && currentNetworkId && selectedModel.network_id !== currentNetworkId && (
                <div className="text-[10px] text-red-500">
                  Model network does not match current map network.
                </div>
              )}
              <div>
                <label className="text-xs text-gray-500">Map selection</label>
                <div className="mt-1 text-xs text-gray-700">
                  {selectedJunctionIds.length > 0
                    ? `${selectedJunctionIds.length} intersection(s) selected on map`
                    : 'None selected'}
                </div>
              </div>
              <div>
                <label className="text-xs text-gray-500">Intersection (manual)</label>
                <select
                  value={selectedDeployTlId ?? ''}
                  onChange={(e) => setSelectedDeployTlId(e.target.value || null)}
                  className="mt-1 w-full text-xs border border-gray-200 rounded px-2 py-1.5 bg-white"
                  disabled={selectedJunctionIds.length > 0}
                >
                  <option value="">Select intersection</option>
                  {tlOptions.map((opt) => (
                    <option key={opt.id} value={opt.id}>
                      {opt.label}
                    </option>
                  ))}
                </select>
                {selectedJunctionIds.length > 0 && (
                  <p className="text-[10px] text-gray-400 mt-1">Using map selection. Clear map selection to pick manually.</p>
                )}
                {tlOptions.length === 0 && selectedJunctionIds.length === 0 && (
                  <p className="text-[10px] text-gray-400 mt-1">Load SUMO network to list intersections.</p>
                )}
              </div>
              <button
                onClick={handleDeploySelected}
                className="w-full text-xs py-1.5 rounded bg-green-600 text-white hover:bg-green-700 transition-colors disabled:opacity-50"
                disabled={!canDeploy}
              >
                {selectedJunctionIds.length > 0
                  ? `Deploy Selected (${selectedJunctionIds.length})`
                  : 'Deploy'}
              </button>
            </div>
          </div>
          {networkIds.map((networkId) => (
            <div key={networkId}>
              <p className="text-xs text-gray-500 font-mono mb-2 truncate" title={networkId}>
                Network: {networkId.slice(0, 16)}...
              </p>
              <div className="space-y-2">
                {groupedModels[networkId].map((model) => (
                  <ModelCard
                    key={model.model_id}
                    model={model}
                    isExpanded={expandedModelId === model.model_id}
                    isSelected={selectedDeployModelId === model.model_id}
                    onToggleExpand={() => toggleExpandedModel(model.model_id)}
                    onSelect={handleSelectModel}
                    onDelete={handleDelete}
                  />
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
