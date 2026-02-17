// Task service - API client for background task management

import { api } from './api';
import type { Task } from '../types';

// API response type (different from frontend Task type)
interface TaskApiResponse {
  task_id: string;
  status: string;
  metadata: {
    network_id?: string;
    tl_id?: string;
    algorithm?: string;
    total_timesteps?: number;
    scenario?: string;
    created_at?: string;
  };
  info: {
    progress?: number | null;
    timestep?: number | null;
    mean_reward?: number | null;
    episode_count?: number | null;
    model_path?: string | null;
  };
  error?: string | null;
}

// Transform API response to frontend Task type
function transformTask(apiTask: TaskApiResponse): Task {
  const { metadata, info } = apiTask;
  return {
    task_id: apiTask.task_id,
    status: apiTask.status as Task['status'],
    type: 'training',
    progress: info.progress ?? 0,
    network_id: metadata.network_id ?? '',
    traffic_light_id: metadata.tl_id ?? '',
    algorithm: (metadata.algorithm?.toUpperCase() as 'DQN' | 'PPO') ?? 'DQN',
    total_timesteps: metadata.total_timesteps ?? 0,
    current_timestep: info.timestep ?? 0,
    mean_reward: info.mean_reward ?? 0,
    episode_count: info.episode_count ?? 0,
    created_at: metadata.created_at ?? '',
    started_at: null,
    completed_at: null,
    error_message: apiTask.error ?? null,
  };
}

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
    const response = await api.get<TaskApiResponse[]>('/tasks');
    return response.data.map(transformTask);
  },

  /**
   * Get task details by ID
   */
  getTask: async (taskId: string): Promise<Task> => {
    const response = await api.get<TaskApiResponse>(`/tasks/${taskId}`);
    return transformTask(response.data);
  },

  /**
   * Cancel a task
   */
  cancelTask: async (taskId: string): Promise<{ status: string }> => {
    const response = await api.post<{ status: string }>(`/tasks/${taskId}/cancel`);
    return response.data;
  },
};
