// Training SSE service - real-time training progress updates

import { useMLStore } from '../store/mlStore';
import type { TrainingStatus } from '../types/ml';

let eventSource: EventSource | null = null;

const API_URL = import.meta.env.VITE_API_URL || '';

export function connectTrainingSSE(): void {
  // Close existing connection if any
  if (eventSource) {
    eventSource.close();
  }

  const url = `${API_URL}/api/training/status/stream`;
  eventSource = new EventSource(url);

  eventSource.addEventListener('status', (event: MessageEvent) => {
    try {
      const data = JSON.parse(event.data);
      const store = useMLStore.getState();
      store.setTrainingStatus(data.status as TrainingStatus);
      if (data.job) {
        store.setTrainingJob(data.job);
      }
    } catch (error) {
      console.error('Error parsing training status event:', error);
    }
  });

  eventSource.addEventListener('completed', (event: MessageEvent) => {
    try {
      const data = JSON.parse(event.data);
      const store = useMLStore.getState();
      store.setTrainingStatus(data.status as TrainingStatus);
      if (data.job) {
        store.setTrainingJob(data.job);
      }
      // Disconnect after completion
      disconnectTrainingSSE();
    } catch (error) {
      console.error('Error parsing training completed event:', error);
    }
  });

  eventSource.addEventListener('error', (event: MessageEvent) => {
    try {
      const data = JSON.parse(event.data);
      const store = useMLStore.getState();
      store.setError(data.error || 'Training error occurred');
      store.setTrainingStatus('failed');
    } catch {
      console.error('Training SSE error event');
    }
  });

  eventSource.onerror = () => {
    console.error('Training SSE connection error');
    disconnectTrainingSSE();
  };
}

export function disconnectTrainingSSE(): void {
  if (eventSource) {
    eventSource.close();
    eventSource = null;
  }
}

export function isTrainingSSEConnected(): boolean {
  return eventSource !== null && eventSource.readyState === EventSource.OPEN;
}
