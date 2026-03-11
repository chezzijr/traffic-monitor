import { api } from './api';
import type {
  SingleTrainingRequest,
  MultiTrainingRequest,
  TrainingTaskResponse,
  TaskInfo,
} from '../types';

export const trainingService = {
  async startSingleTraining(req: SingleTrainingRequest): Promise<TrainingTaskResponse> {
    const response = await api.post<TrainingTaskResponse>('/training/single', req);
    return response.data;
  },

  async startMultiTraining(req: MultiTrainingRequest): Promise<TrainingTaskResponse> {
    const response = await api.post<TrainingTaskResponse>('/training/multi', req);
    return response.data;
  },

  async getStatus(taskId: string): Promise<TaskInfo> {
    const response = await api.get<TaskInfo>(`/training/status/${taskId}`);
    return response.data;
  },
};
