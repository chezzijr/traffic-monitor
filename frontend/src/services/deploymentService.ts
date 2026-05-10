import { api } from './api';
import type { Deployment } from '../types';

export interface DeploymentSnapshot {
  tl_id: string;
  model_id: string;
  model_path: string;
  network_id: string;
  ai_control_enabled: boolean;
  phase: number;
  program: string;
  state: string;
  phase_duration: number;
  controlled_lanes: string[];
  vehicle_count: number;
  waiting_count: number;
  vehicles: Array<{
    id: string;
    speed: number;
    waiting_time: number;
    lane_id: string;
  }>;
}

export const deploymentService = {
  async listDeployments(): Promise<Deployment[]> {
    const response = await api.get<Deployment[]>('/deployment/');
    return response.data;
  },

  async toggleAIControl(tlId: string, enabled: boolean): Promise<void> {
    await api.post(`/deployment/${tlId}/toggle`, { enabled });
  },

  async getSnapshot(tlId: string): Promise<DeploymentSnapshot> {
    const response = await api.get<DeploymentSnapshot>(`/deployment/${tlId}/snapshot`);
    return response.data;
  },
};
