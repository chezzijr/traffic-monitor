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

export interface VideoPrecheckResult {
  ok: boolean;
  exists?: boolean;
  path?: string;
  error?: string | null;
  hint?: string | null;
  size_bytes?: number;
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

  async precheckVideo(modelId?: string): Promise<VideoPrecheckResult> {
    const params = modelId ? { model_id: modelId } : undefined;
    const response = await api.get<VideoPrecheckResult>('/deployment/precheck', { params });
    return response.data;
  },

  async stopAll(): Promise<{ status: string; dt_stopped: boolean; error?: string }> {
    const response = await api.post<{ status: string; dt_stopped: boolean; error?: string }>(
      '/deployment/stop-all',
    );
    return response.data;
  },
};
