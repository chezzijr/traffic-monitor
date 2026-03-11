import { create } from 'zustand';
import type { TrainedModel, Deployment } from '../types';

interface ModelState {
  models: TrainedModel[];
  deployments: Deployment[];
  isPanelOpen: boolean;

  // Actions
  setModels: (models: TrainedModel[]) => void;
  addModel: (model: TrainedModel) => void;
  removeModel: (modelId: string) => void;
  setDeployments: (deployments: Deployment[]) => void;
  addDeployment: (deployment: Deployment) => void;
  removeDeployment: (tlId: string) => void;
  togglePanel: () => void;
}

export const useModelStore = create<ModelState>((set) => ({
  models: [],
  deployments: [],
  isPanelOpen: false,

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
  togglePanel: () =>
    set((state) => ({ isPanelOpen: !state.isPanelOpen })),
}));
