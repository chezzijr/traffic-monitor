import axios from 'axios';

/** Matches the digital twin's /traffic_light_state response. */
export interface DigitalTwinDirectionLight {
  state: 'red' | 'yellow' | 'green';
  duration: number; // -1 means unknown
}

export interface DigitalTwinLightState {
  north: DigitalTwinDirectionLight;
  south: DigitalTwinDirectionLight;
  east: DigitalTwinDirectionLight;
  west: DigitalTwinDirectionLight;
}

// The digital twin service runs on port 8001
const DIGITAL_TWIN_BASE_URL = '/digital-twin';

const dtApi = axios.create({
  baseURL: DIGITAL_TWIN_BASE_URL,
  headers: { 'Content-Type': 'application/json' },
});

export const digitalTwinLightService = {
  async getLightState(): Promise<DigitalTwinLightState> {
    const response = await dtApi.get<DigitalTwinLightState>('/traffic_light_state');
    return response.data;
  },

  async startStream(): Promise<{ status: string }> {
    const response = await dtApi.post<{ status: string }>('/stream/start');
    return response.data;
  },

  async stopStream(): Promise<{ status: string }> {
    const response = await dtApi.post<{ status: string }>('/stream/stop');
    return response.data;
  },
};
