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
  agent_enabled?: boolean;
  video_frame?: string;
  video_frame_annotated?: string;
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
  tl_state?: Record<string, {
    tl_id: string;
    phase: number;
    state: string;
    program: string;
  }> | {
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
  ai_action?: number | number[] | null;
  is_multi_agent?: boolean;
  controlled_tl_ids?: string[];
  fixed_tl_ids?: string[];
  network_geometry?: {
    junctions: Array<{
      id: string;
      x: number;
      y: number;
    }>;
    edges: Array<{
      id: string;
      lanes: Array<{
        id: string;
        shape: Array<{ x: number; y: number }>;
      }>;
    }>;
  };
  tl_link_metadata?: TlLinkMetadataMap;
}

/** One physical incoming road at a traffic light. `angle_deg` is the
 *  compass bearing (0=N, 90=E, clockwise) of the approach as it enters
 *  the junction. `link_indices` are the SUMO state-string positions that
 *  belong to this approach (use to extract the bulb color via majority). */
export interface ApproachMeta {
  angle_deg: number;
  link_indices: number[];
  from_edge: string;
}

/** Per-TL link → approach mapping, computed once at deploy start from
 *  SUMO net topology. Renderers use this to position bulbs at correct
 *  compass angles. The shape is the single source of truth — both the
 *  marker icon and the modal import it. */
export type TlLinkMetadataMap = Record<string, { approaches: ApproachMeta[] }>;

export interface DeployStatus {
  running: boolean;
  step: number;
  num_sumo_vehicles: number;
  video_complete: boolean;
  model_path?: string | null;
  tl_id?: string | null;
  tl_ids?: string[];
  last_action?: number | number[] | null;
  is_multi_agent?: boolean;
  controlled_tl_ids?: string[];
  fixed_tl_ids?: string[];
  agent_enabled?: boolean;
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

  async startDeploy(modelPath: string, tlId?: string, networkId?: string, tlIds?: string[]): Promise<{ status: string }>{
    const res = await axios.post(`${DIGITAL_TWIN_BASE}/deploy/start`, {
      model_path: modelPath,
      tl_id: tlId || null,
      tl_ids: tlIds || null,
      network_id: networkId || null,
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

  async toggleAgent(enabled: boolean): Promise<{ agent_enabled: boolean }> {
    const res = await axios.post<{ agent_enabled: boolean }>(
      `${DIGITAL_TWIN_BASE}/deploy/agent/toggle`,
      null,
      { params: { enabled } },
    );
    return res.data;
  },
};
