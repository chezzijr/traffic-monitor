import axios from 'axios';

const DIGITAL_TWIN_BASE = '/digital-twin';

export interface DeployModelInfo {
  name: string;
  path: string;
  size_mb: number;
}

export interface DeployVideoInfo {
  name: string;
  path: string;
  folder: string;
  size_mb: number;
}

export interface DeploySnapshot {
  step: number;
  running: boolean;
  video_frame?: string | null;
  video_timestamp?: number;
  vehicles?: Array<{
    id: string;
    x: number;
    y: number;
    speed: number;
    waiting_time: number;
    lane: string;
    route: string[];
  }>;
  tl_state?: {
    tl_id: string;
    phase: number;
    state: string;
    program: string;
  };
  metrics?: {
    num_vehicles: number;
    total_waiting_time: number;
    avg_speed: number;
    arrived: number;
  };
  ai_action?: number | null;
}

export interface DeployStatus {
  running: boolean;
  step: number;
  num_sumo_vehicles: number;
  video_complete: boolean;
  model_path?: string | null;
  tl_id?: string | null;
  last_action?: number | null;
}

export const digitalTwinDeployService = {
  async listModels(): Promise<DeployModelInfo[]> {
    const res = await axios.get<DeployModelInfo[]>(`${DIGITAL_TWIN_BASE}/deploy/models`);
    return res.data;
  },

  async listVideos(): Promise<DeployVideoInfo[]> {
    const res = await axios.get<DeployVideoInfo[]>(`${DIGITAL_TWIN_BASE}/deploy/videos`);
    return res.data;
  },

  async startDeploy(modelPath: string, tlId?: string): Promise<{ status: string }>{
    const res = await axios.post(`${DIGITAL_TWIN_BASE}/deploy/start`, {
      model_path: modelPath,
      tl_id: tlId || null,
    });
    return res.data;
  },

  async stopDeploy(): Promise<{ status: string }>{
    const res = await axios.post(`${DIGITAL_TWIN_BASE}/deploy/stop`);
    return res.data;
  },

  async getSnapshot(): Promise<DeploySnapshot> {
    const res = await axios.get<DeploySnapshot>(`${DIGITAL_TWIN_BASE}/deploy/snapshot`);
    return res.data;
  },

  async getStatus(): Promise<DeployStatus> {
    const res = await axios.get<DeployStatus>(`${DIGITAL_TWIN_BASE}/deploy/status`);
    return res.data;
  },
};
