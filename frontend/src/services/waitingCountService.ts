import { api } from './api';
import type { WaitingCountResponse } from '../types';

export const waitingCountService = {
  async getWaitingCount(idCamera: string): Promise<WaitingCountResponse> {
    const response = await api.get<WaitingCountResponse>('/waiting_count', {
      params: { id_camera: idCamera },
    });
    return response.data;
  },
};
