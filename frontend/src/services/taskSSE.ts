// Task SSE service - real-time task progress updates via Server-Sent Events

import { useTaskStore } from '../store/taskStore';
import type { TaskStatus } from '../types';

const API_URL = import.meta.env.VITE_API_URL || '';

// Map of task ID to EventSource connection
const activeConnections = new Map<string, EventSource>();

// SSE Event data types
interface ProgressEventData {
  timestep: number;
  progress: number;
}

interface MetricsEventData {
  mean_reward: number;
  episode_count: number;
}

interface CompletedEventData {
  model_path: string;
}

interface FailedEventData {
  error: string;
}

/**
 * Subscribe to real-time updates for a specific task
 */
export function subscribeToTask(taskId: string): void {
  // Close existing connection if any
  if (activeConnections.has(taskId)) {
    unsubscribeFromTask(taskId);
  }

  const url = `${API_URL}/api/tasks/${taskId}/stream`;
  const eventSource = new EventSource(url);

  // Store the connection
  activeConnections.set(taskId, eventSource);

  // Handle progress updates
  eventSource.addEventListener('progress', (event: MessageEvent) => {
    try {
      const data: ProgressEventData = JSON.parse(event.data);
      const store = useTaskStore.getState();
      store.updateTask(taskId, {
        current_timestep: data.timestep,
        progress: data.progress,
        status: 'running' as TaskStatus,
      });
    } catch (error) {
      console.error('Error parsing task progress event:', error);
    }
  });

  // Handle metrics updates
  eventSource.addEventListener('metrics', (event: MessageEvent) => {
    try {
      const data: MetricsEventData = JSON.parse(event.data);
      const store = useTaskStore.getState();
      store.updateTask(taskId, {
        mean_reward: data.mean_reward,
        episode_count: data.episode_count,
      });
    } catch (error) {
      console.error('Error parsing task metrics event:', error);
    }
  });

  // Handle task completion
  eventSource.addEventListener('completed', (event: MessageEvent) => {
    try {
      const data: CompletedEventData = JSON.parse(event.data);
      const store = useTaskStore.getState();
      store.updateTask(taskId, {
        status: 'completed' as TaskStatus,
        progress: 1.0,
        completed_at: new Date().toISOString(),
      });
      console.log(`Task ${taskId} completed. Model saved at: ${data.model_path}`);
      // Close connection after completion
      unsubscribeFromTask(taskId);
    } catch (error) {
      console.error('Error parsing task completed event:', error);
    }
  });

  // Handle task failure
  eventSource.addEventListener('failed', (event: MessageEvent) => {
    try {
      const data: FailedEventData = JSON.parse(event.data);
      const store = useTaskStore.getState();
      store.updateTask(taskId, {
        status: 'failed' as TaskStatus,
        error_message: data.error,
        completed_at: new Date().toISOString(),
      });
      // Close connection after failure
      unsubscribeFromTask(taskId);
    } catch (error) {
      console.error('Error parsing task failed event:', error);
    }
  });

  // Handle connection errors
  eventSource.onerror = () => {
    console.error(`Task SSE connection error for task ${taskId}`);
    unsubscribeFromTask(taskId);
  };
}

/**
 * Unsubscribe from task updates
 */
export function unsubscribeFromTask(taskId: string): void {
  const eventSource = activeConnections.get(taskId);
  if (eventSource) {
    eventSource.close();
    activeConnections.delete(taskId);
  }
}

/**
 * Unsubscribe from all active task subscriptions
 */
export function unsubscribeFromAllTasks(): void {
  for (const [taskId, eventSource] of activeConnections) {
    eventSource.close();
    activeConnections.delete(taskId);
  }
}

/**
 * Check if a task subscription is active
 */
export function isTaskSubscriptionActive(taskId: string): boolean {
  const eventSource = activeConnections.get(taskId);
  return eventSource !== null && eventSource !== undefined && eventSource.readyState === EventSource.OPEN;
}

/**
 * Get list of all active task subscriptions
 */
export function getActiveTaskSubscriptions(): string[] {
  return Array.from(activeConnections.keys());
}
