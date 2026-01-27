import type { SSEStepEvent, SSEStatusEvent, SSEErrorEvent } from '../types';

interface SimulationSSECallbacks {
  onStep: (data: SSEStepEvent) => void;
  onHeartbeat?: () => void;
  onStopped?: (data: SSEStatusEvent) => void;
  onError?: (data: SSEErrorEvent) => void;
}

export class SimulationSSE {
  private eventSource: EventSource | null = null;
  private callbacks: SimulationSSECallbacks;

  constructor(callbacks: SimulationSSECallbacks) {
    this.callbacks = callbacks;
  }

  connect(stepInterval: number = 100): void {
    // Close existing connection
    this.disconnect();

    // Create new EventSource
    this.eventSource = new EventSource(
      `/api/simulation/stream?step_interval=${stepInterval}`
    );

    // Register event listeners
    this.eventSource.addEventListener('step', (event) => {
      const data = JSON.parse(event.data) as SSEStepEvent;
      this.callbacks.onStep(data);
    });

    this.eventSource.addEventListener('heartbeat', () => {
      this.callbacks.onHeartbeat?.();
    });

    this.eventSource.addEventListener('stopped', (event) => {
      const data = JSON.parse(event.data) as SSEStatusEvent;
      this.callbacks.onStopped?.(data);
    });

    this.eventSource.addEventListener('error', (event) => {
      // Check if this is a custom error event from the server
      if (event instanceof MessageEvent && event.data) {
        const data = JSON.parse(event.data) as SSEErrorEvent;
        this.callbacks.onError?.(data);
      }
    });

    // Handle connection error
    this.eventSource.onerror = () => {
      this.callbacks.onError?.({ message: 'SSE connection error' });
      this.disconnect();
    };
  }

  disconnect(): void {
    if (this.eventSource) {
      this.eventSource.close();
      this.eventSource = null;
    }
  }
}
