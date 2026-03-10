import { api } from './api';
import type { TrafficLightSimState } from '../types';

export const trafficLightSimService = {
  async getState(intersectionId: string): Promise<TrafficLightSimState> {
    const response = await api.get<TrafficLightSimState>(
      '/traffic_light_sim/state',
      { params: { intersection_id: intersectionId } },
    );
    return response.data;
  },
};
