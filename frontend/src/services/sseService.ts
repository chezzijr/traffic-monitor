// TODO: Rewrite for training SSE in Phase 9
// This file is a placeholder — the old SimulationSSE was removed with the simulation flow.

export class TrainingSSE {
  private eventSource: EventSource | null = null;

  connect(_taskId: string): void {
    this.disconnect();
    // Will be implemented in Phase 9
  }

  disconnect(): void {
    if (this.eventSource) {
      this.eventSource.close();
      this.eventSource = null;
    }
  }
}
