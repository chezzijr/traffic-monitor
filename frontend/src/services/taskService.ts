// Task service - API client for background task management

import { api } from './api';
import type { Task } from '../types';

// Request types
export interface CreateTrainingTaskRequest {
  network_id: string;
  traffic_light_id: string;
  algorithm: 'DQN' | 'PPO';
  total_timesteps: number;
}

// Response types
export interface CreateTaskResponse {
  task_id: string;
  status: 'pending';
  created_at: string;
}

export const taskService = {
  /**
   * Create a new training task
   */
  createTrainingTask: async (params: CreateTrainingTaskRequest): Promise<CreateTaskResponse> => {
    const response = await api.post<CreateTaskResponse>('/tasks/training', params);
    return response.data;
  },

  /**
   * List all tasks
   */
  listTasks: async (): Promise<Task[]> => {
    const response = await api.get<Task[]>('/tasks');
    return response.data;
  },

  /**
   * Get task details by ID
   */
  getTask: async (taskId: string): Promise<Task> => {
    const response = await api.get<Task>(`/tasks/${taskId}`);
    return response.data;
  },

  /**
   * Cancel a task
   */
  cancelTask: async (taskId: string): Promise<{ status: string }> => {
    const response = await api.post<{ status: string }>(`/tasks/${taskId}/cancel`);
    return response.data;
  },
};
