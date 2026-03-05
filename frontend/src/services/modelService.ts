import { api } from './api';
import type { TrainedModel, Deployment } from '../types';

export const modelService = {
  async listModels(): Promise<TrainedModel[]> {
    const response = await api.get<TrainedModel[]>('/models/');
    return response.data;
  },

  async deleteModel(modelId: string): Promise<void> {
    await api.delete(`/models/${modelId}`);
  },

  async deployModel(req: { tl_id: string; model_path: string; network_id: string }): Promise<Deployment> {
    const response = await api.post<Deployment>('/deployment/deploy', req);
    return response.data;
  },

  async undeployModel(tlId: string): Promise<void> {
    await api.post('/deployment/undeploy', { tl_id: tlId });
  },
};
