import axios from 'axios';

const DIGITAL_TWIN_BASE = '/digital-twin';

export interface ModelInfo {
  name: string;
  path: string;
  size_mb: number;
}

export interface VideoInfo {
  name: string;
  path: string;
  folder: string;
  size_mb: number;
}

export interface SumoVehicle {
  id: string;
  x: number;
  y: number;
  speed: number;
  waiting_time: number;
  lane: string;
  route: string[];
}

export interface TLState {
  tl_id: string;
  phase: number;
  state: string;
  program: string;
}

export interface SyncSnapshot {
  step: number;
  running: boolean;
  video_frame?: string;
  video_timestamp?: number;

  rl_vehicles?: SumoVehicle[];
  rl_tl_state?: TLState;
  rl_metrics?: {
    num_vehicles: number;
    total_waiting_time: number;
    avg_speed: number;
    arrived: number;
  };
  baseline_vehicles?: SumoVehicle[];
  baseline_tl_state?: TLState;
  baseline_metrics?: {
    num_vehicles: number;
    total_waiting_time: number;
    avg_speed: number;
    arrived: number;
  };
  evaluation?: Record<string, unknown>;
}

export interface SyncStatus {
  running: boolean;
  mode: string | null;
  step: number;
  num_sumo_vehicles: number;
  video_complete: boolean;
}

export const evaluationService = {
  async listModels(): Promise<ModelInfo[]> {
    const res = await axios.get<ModelInfo[]>(`${DIGITAL_TWIN_BASE}/sync/models`);
    return res.data;
  },

  async listVideos(): Promise<VideoInfo[]> {
    const res = await axios.get<VideoInfo[]>(`${DIGITAL_TWIN_BASE}/sync/videos`);
    return res.data;
  },

  async startEvaluation(modelPath: string): Promise<{ status: string; mode: string }> {
    const res = await axios.post(`${DIGITAL_TWIN_BASE}/sync/start`, {
      model_path: modelPath,
    });
    return res.data;
  },

  async stopEvaluation(): Promise<{ status: string }> {
    const res = await axios.post(`${DIGITAL_TWIN_BASE}/sync/stop`);
    return res.data;
  },

  async getSnapshot(): Promise<SyncSnapshot> {
    const res = await axios.get<SyncSnapshot>(`${DIGITAL_TWIN_BASE}/sync/snapshot`);
    return res.data;
  },

  async getStatus(): Promise<SyncStatus> {
    const res = await axios.get<SyncStatus>(`${DIGITAL_TWIN_BASE}/sync/status`);
    return res.data;
  },

  async getEvaluation(): Promise<Record<string, unknown>> {
    const res = await axios.get(`${DIGITAL_TWIN_BASE}/sync/evaluation`);
    return res.data;
  },
};
