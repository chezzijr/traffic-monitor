import { api } from './api';
import type { Deployment } from '../types';

export const deploymentService = {
  async listDeployments(): Promise<Deployment[]> {
    const response = await api.get<Deployment[]>('/deployment/');
    return response.data;
  },

  async toggleAIControl(tlId: string, enabled: boolean): Promise<void> {
    await api.post(`/deployment/${tlId}/toggle`, { enabled });
  },
};
