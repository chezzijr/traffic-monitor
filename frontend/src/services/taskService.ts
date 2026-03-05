import { api } from './api';
import type { TaskInfo } from '../types';

export const taskService = {
  async listTasks(): Promise<TaskInfo[]> {
    const response = await api.get<{ tasks: TaskInfo[] }>('/tasks/');
    return response.data.tasks;
  },

  async getTask(taskId: string): Promise<TaskInfo> {
    const response = await api.get<TaskInfo>(`/tasks/${taskId}`);
    return response.data;
  },

  async cancelTask(taskId: string): Promise<void> {
    await api.post(`/tasks/${taskId}/cancel`);
  },
};
