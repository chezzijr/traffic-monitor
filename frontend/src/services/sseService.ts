import type { TrainingProgressEvent } from '../types';
import { API_BASE_URL } from './api';

type ProgressHandler = (data: TrainingProgressEvent) => void;
type CompleteHandler = (data: { task_id: string; model_path?: string }) => void;
type ErrorHandler = (error: { task_id: string; error: string }) => void;

interface SSEHandlers {
  onProgress?: ProgressHandler;
  onComplete?: CompleteHandler;
  onError?: ErrorHandler;
}

export class TrainingSSE {
  private eventSource: EventSource | null = null;
  private onProgress: ProgressHandler | null = null;
  private onComplete: CompleteHandler | null = null;
  private onError: ErrorHandler | null = null;

  setHandlers(handlers: SSEHandlers): void {
    this.onProgress = handlers.onProgress ?? null;
    this.onComplete = handlers.onComplete ?? null;
    this.onError = handlers.onError ?? null;
  }

  connect(taskId: string): void {
    this.disconnect();
    this.eventSource = new EventSource(`${API_BASE_URL}/tasks/${taskId}/stream`);

    this.eventSource.addEventListener('progress', (e: MessageEvent) => {
      if (this.onProgress) {
        try {
          const data = JSON.parse(e.data) as TrainingProgressEvent;
          this.onProgress(data);
        } catch {
          console.error('Failed to parse SSE progress data:', e.data);
        }
      }
    });

    this.eventSource.addEventListener('complete', (e: MessageEvent) => {
      if (this.onComplete) {
        try {
          const data = JSON.parse(e.data) as { task_id: string; model_path?: string };
          this.onComplete(data);
        } catch {
          console.error('Failed to parse SSE complete data:', e.data);
        }
      }
      this.disconnect();
    });

    // Application-level error event (server sends event: error with JSON data)
    this.eventSource.addEventListener('error', (e: MessageEvent) => {
      if (e.data && this.onError) {
        try {
          const data = JSON.parse(e.data) as { task_id: string; error: string };
          this.onError(data);
        } catch {
          console.error('Failed to parse SSE error data:', e.data);
        }
      }
      this.disconnect();
    });

    // Transport-level error (connection lost) — EventSource auto-reconnects by default
    this.eventSource.onerror = () => {
      if (this.eventSource?.readyState === EventSource.CLOSED) {
        this.disconnect();
      }
    };
  }

  disconnect(): void {
    if (this.eventSource) {
      this.eventSource.close();
      this.eventSource = null;
    }
  }
}
