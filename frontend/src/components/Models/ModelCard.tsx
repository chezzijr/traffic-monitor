import { Trash2, Rocket } from 'lucide-react';
import type { TrainedModel } from '../../types';

interface ModelCardProps {
  model: TrainedModel;
  onDeploy: (model: TrainedModel) => void;
  onDelete: (modelId: string) => void;
}

export function ModelCard({ model, onDeploy, onDelete }: ModelCardProps) {
  const algColor = model.algorithm === 'dqn' ? 'bg-blue-100 text-blue-700' : 'bg-purple-100 text-purple-700';

  return (
    <div className="border border-gray-200 rounded-lg p-3 bg-white">
      <div className="flex items-center justify-between mb-2">
        <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium uppercase ${algColor}`}>
          {model.algorithm}
        </span>
        <span className="text-[10px] text-gray-400">
          {model.created_at ? new Date(model.created_at).toLocaleDateString() : 'N/A'}
        </span>
      </div>

      <p className="text-xs font-mono text-gray-700 truncate mb-1" title={model.tl_id}>
        Junction: {model.tl_id}
      </p>
      <p className="text-[10px] text-gray-400 truncate" title={model.model_id}>
        ID: {model.model_id.slice(0, 16)}...
      </p>

      <div className="flex gap-2 mt-3">
        <button
          onClick={() => onDeploy(model)}
          className="flex-1 flex items-center justify-center gap-1 text-xs py-1.5 rounded bg-green-50 text-green-700 hover:bg-green-100 transition-colors"
        >
          <Rocket size={12} />
          Deploy
        </button>
        <button
          onClick={() => onDelete(model.model_id)}
          className="flex items-center justify-center px-2 py-1.5 rounded bg-red-50 text-red-500 hover:bg-red-100 transition-colors"
          title="Delete model"
        >
          <Trash2 size={12} />
        </button>
      </div>
    </div>
  );
}
