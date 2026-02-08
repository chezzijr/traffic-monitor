import { create } from 'zustand';
import type {
  TrainingStatus,
  TrainingJobInfo,
  ModelInfo,
  DeploymentInfo,
} from '../types/ml';

interface MLState {
  // Training state
  trainingStatus: TrainingStatus;
  trainingJob: TrainingJobInfo | null;

  // Models
  models: ModelInfo[];
  selectedModelId: string | null;

  // Deployments
  deployments: DeploymentInfo[];

  // Loading states
  isLoadingModels: boolean;
  isLoadingDeployments: boolean;

  // Error state
  error: string | null;

  // Training actions
  setTrainingStatus: (status: TrainingStatus) => void;
  setTrainingJob: (job: TrainingJobInfo | null) => void;

  // Model actions
  setModels: (models: ModelInfo[]) => void;
  addModel: (model: ModelInfo) => void;
  removeModel: (modelId: string) => void;
  setSelectedModelId: (id: string | null) => void;
  setLoadingModels: (loading: boolean) => void;

  // Deployment actions
  setDeployments: (deployments: DeploymentInfo[]) => void;
  addDeployment: (deployment: DeploymentInfo) => void;
  removeDeployment: (tlId: string) => void;
  updateDeployment: (tlId: string, updates: Partial<DeploymentInfo>) => void;
  setLoadingDeployments: (loading: boolean) => void;

  // Error actions
  setError: (error: string | null) => void;

  // Reset
  reset: () => void;
}

const initialState = {
  trainingStatus: 'idle' as TrainingStatus,
  trainingJob: null,
  models: [],
  selectedModelId: null,
  deployments: [],
  isLoadingModels: false,
  isLoadingDeployments: false,
  error: null,
};

export const useMLStore = create<MLState>((set) => ({
  // Initial state
  ...initialState,

  // Training actions
  setTrainingStatus: (status) => set({ trainingStatus: status }),
  setTrainingJob: (job) => set({ trainingJob: job }),

  // Model actions
  setModels: (models) => set({ models }),
  addModel: (model) =>
    set((state) => ({ models: [...state.models, model] })),
  removeModel: (modelId) =>
    set((state) => ({
      models: state.models.filter((m) => m.id !== modelId),
    })),
  setSelectedModelId: (id) => set({ selectedModelId: id }),
  setLoadingModels: (loading) => set({ isLoadingModels: loading }),

  // Deployment actions
  setDeployments: (deployments) => set({ deployments }),
  addDeployment: (deployment) =>
    set((state) => ({ deployments: [...state.deployments, deployment] })),
  removeDeployment: (tlId) =>
    set((state) => ({
      deployments: state.deployments.filter((d) => d.tl_id !== tlId),
    })),
  updateDeployment: (tlId, updates) =>
    set((state) => ({
      deployments: state.deployments.map((d) =>
        d.tl_id === tlId ? { ...d, ...updates } : d
      ),
    })),
  setLoadingDeployments: (loading) => set({ isLoadingDeployments: loading }),

  // Error actions
  setError: (error) => set({ error }),

  // Reset
  reset: () => set(initialState),
}));
