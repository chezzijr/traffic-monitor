import { Component, type ReactNode } from 'react';

interface Props { children: ReactNode; }
interface State { hasError: boolean; error?: Error; }

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  render() {
    if (this.state.hasError) {
      return (
        <div
          className="min-h-screen flex flex-col items-center justify-center gap-4"
          style={{ background: '#0b0f1a', color: 'white' }}
        >
          <p className="text-slate-300 text-sm">Something went wrong rendering this page.</p>
          <p className="text-slate-500 text-xs font-mono">{this.state.error?.message}</p>
          <button
            onClick={() => window.location.reload()}
            className="px-4 py-2 bg-cyan-500/80 hover:bg-cyan-400 rounded-lg text-sm font-semibold transition-colors"
          >
            Reload Page
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
