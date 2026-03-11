import { useEffect, useMemo } from 'react';
import { Package } from 'lucide-react';
import toast from 'react-hot-toast';
import { useModelStore } from '../../store/modelStore';
import { modelService } from '../../services/modelService';
import { ModelCard } from './ModelCard';
import type { TrainedModel } from '../../types';

export function ModelsPanel() {
  const models = useModelStore((s) => s.models);
  const setModels = useModelStore((s) => s.setModels);
  const removeModel = useModelStore((s) => s.removeModel);
  const addDeployment = useModelStore((s) => s.addDeployment);

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

  const handleDeploy = async (model: TrainedModel) => {
    try {
      const deployment = await modelService.deployModel({
        tl_id: model.tl_id,
        model_path: model.model_path,
        network_id: model.network_id,
      });
      addDeployment(deployment);
      toast.success(`Model deployed to ${model.tl_id}`);
    } catch {
      toast.error('Failed to deploy model');
    }
  };

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
                    onDeploy={handleDeploy}
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
