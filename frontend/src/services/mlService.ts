// ML service - API client for training and deployment endpoints

import { api } from './api';
import type {
  TrainingStatusResponse,
  ModelInfo,
  DeploymentInfo,
  TrainingStartRequest,
} from '../types/ml';

export const mlService = {
  // Training endpoints
  startTraining: async (params: TrainingStartRequest) => {
    const response = await api.post<{ status: string }>('/training/start', params);
    return response.data;
  },

  stopTraining: async () => {
    const response = await api.post<{ status: string }>('/training/stop');
    return response.data;
  },

  getTrainingStatus: async () => {
    const response = await api.get<TrainingStatusResponse>('/training/status');
    return response.data;
  },

  // Model endpoints
  listModels: async () => {
    const response = await api.get<ModelInfo[]>('/models');
    return response.data;
  },

  getModel: async (modelId: string) => {
    const response = await api.get<ModelInfo>(`/models/${modelId}`);
    return response.data;
  },

  deleteModel: async (modelId: string) => {
    const response = await api.delete<{ status: string }>(`/models/${modelId}`);
    return response.data;
  },

  // Deployment endpoints
  deployModel: async (modelId: string, tlId: string) => {
    const response = await api.post<{ status: string }>(`/models/${modelId}/deploy`, {
      tl_id: tlId,
    });
    return response.data;
  },

  undeployModel: async (modelId: string) => {
    const response = await api.post<{ status: string }>(`/models/${modelId}/undeploy`);
    return response.data;
  },

  getDeployments: async () => {
    const response = await api.get<DeploymentInfo[]>('/deployment/status');
    return response.data;
  },

  toggleAIControl: async (tlId: string, enabled: boolean) => {
    const response = await api.post<{ tl_id: string; ai_control_enabled: boolean }>(
      '/deployment/toggle',
      { tl_id: tlId, enabled }
    );
    return response.data;
  },
};
