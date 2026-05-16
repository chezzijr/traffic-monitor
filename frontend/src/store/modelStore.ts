import { create } from 'zustand';
import type { TrainedModel, Deployment } from '../types';

interface ModelState {
  models: TrainedModel[];
  deployments: Deployment[];
  isPanelOpen: boolean;
  selectedDeployModelId: string | null;
  selectedDeployTlId: string | null;
  // True while a deploy/swap is in flight. The backend clears Redis between
  // stop and start, so the deployment list briefly empties mid-swap — this
  // flag lets the map's deploy-cleanup effect ignore that transient empty.
  isDeploying: boolean;

  // Actions
  setModels: (models: TrainedModel[]) => void;
  addModel: (model: TrainedModel) => void;
  removeModel: (modelId: string) => void;
  setDeployments: (deployments: Deployment[]) => void;
  addDeployment: (deployment: Deployment) => void;
  removeDeployment: (tlId: string) => void;
  clearDeployments: () => void;
  togglePanel: () => void;
  expandedModelId: string | null;
  toggleExpandedModel: (modelId: string) => void;
  setSelectedDeployModelId: (modelId: string | null) => void;
  setSelectedDeployTlId: (tlId: string | null) => void;
  setIsDeploying: (value: boolean) => void;
}

export const useModelStore = create<ModelState>((set) => ({
  models: [],
  deployments: [],
  isPanelOpen: false,
  selectedDeployModelId: null,
  selectedDeployTlId: null,
  isDeploying: false,

  setModels: (models) => set({ models }),
  addModel: (model) =>
    set((state) => ({ models: [...state.models, model] })),
  removeModel: (modelId) =>
    set((state) => ({
      models: state.models.filter((m) => m.model_id !== modelId),
    })),
  setDeployments: (deployments) => set({ deployments }),
  addDeployment: (deployment) =>
    set((state) => ({ deployments: [...state.deployments, deployment] })),
  removeDeployment: (tlId) =>
    set((state) => ({
      deployments: state.deployments.filter((d) => d.tl_id !== tlId),
    })),
  clearDeployments: () => set({ deployments: [] }),
  togglePanel: () =>
    set((state) => ({ isPanelOpen: !state.isPanelOpen })),
  expandedModelId: null,
  toggleExpandedModel: (modelId) =>
    set((state) => ({
      expandedModelId: state.expandedModelId === modelId ? null : modelId,
    })),
  setSelectedDeployModelId: (modelId) => set({ selectedDeployModelId: modelId }),
  setSelectedDeployTlId: (tlId) => set({ selectedDeployTlId: tlId }),
  setIsDeploying: (isDeploying) => set({ isDeploying }),
}));
