import { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowLeft, Square, CheckCircle2, Clock, Loader2 } from 'lucide-react';
import { evaluationService } from '../services/evaluationService';
import type { SyncSnapshot } from '../services/evaluationService';
import { IntersectionDiagram } from '../components/Evaluation/IntersectionDiagram';

export function EvaluateLivePage() {

  const navigate = useNavigate();
  const [snapshot, setSnapshot] = useState<SyncSnapshot | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [stopping, setStopping] = useState(false);
  const startTime = useRef(Date.now());
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Poll snapshot at ~5fps
  const poll = useCallback(async () => {
    try {
      const data = await evaluationService.getSnapshot();
      setSnapshot(data);

      // Stop polling if the run finished
      if (data.running === false && data.evaluation) {
        if (intervalRef.current) {
          clearInterval(intervalRef.current);
          intervalRef.current = null;
        }
      }
    } catch {
      // ignore transient errors
    }
  }, []);

  useEffect(() => {
    poll(); // initial fetch
    intervalRef.current = setInterval(poll, 200); // 5fps
    timerRef.current = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startTime.current) / 1000));
    }, 1000);

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [poll]);

  const handleStop = async () => {
    setStopping(true);
    await evaluationService.stopEvaluation();
    setStopping(false);
  };

  const formatTime = (s: number) => {
    const m = Math.floor(s / 60);
    const sec = s % 60;
    return `${m}:${sec.toString().padStart(2, '0')}`;
  };

  const isComplete = snapshot?.running === false && snapshot?.evaluation;

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-950 via-gray-900 to-gray-950 text-white flex flex-col">
      {/* Header */}
      <header className="border-b border-gray-800/50 bg-gray-900/80 backdrop-blur-sm shrink-0">
        <div className="max-w-[1800px] mx-auto px-6 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <button
              onClick={() => navigate('/evaluate')}
              className="p-2 rounded-lg hover:bg-gray-800 transition-colors"
            >
              <ArrowLeft size={18} />
            </button>
            <h1 className="text-base font-semibold">Live Evaluation</h1>
            {snapshot?.running ? (
              <span className="flex items-center gap-1.5 text-xs text-emerald-400 bg-emerald-400/10 px-2.5 py-1 rounded-full">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                Running
              </span>
            ) : isComplete ? (
              <span className="flex items-center gap-1.5 text-xs text-violet-400 bg-violet-400/10 px-2.5 py-1 rounded-full">
                <CheckCircle2 size={12} />
                Complete
              </span>
            ) : (
              <span className="flex items-center gap-1.5 text-xs text-gray-500 bg-gray-800 px-2.5 py-1 rounded-full">
                Idle
              </span>
            )}
          </div>
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-1.5 text-xs text-gray-400 font-mono">
              <Clock size={13} />
              {typeof snapshot?.video_timestamp === 'number' ? formatTime(snapshot.video_timestamp) : formatTime(elapsed)}
            </div>
            <div className="text-xs text-gray-400 font-mono flex items-center gap-2">
              <span className="text-gray-600">Step:</span>
              <span className="text-indigo-400">{snapshot?.step ?? 0}</span>
            </div>
            {snapshot?.running && (
              <button
                onClick={handleStop}
                disabled={stopping}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-red-500/20 text-red-400 text-xs hover:bg-red-500/30 transition-colors"
              >
                {stopping ? <Loader2 size={13} className="animate-spin" /> : <Square size={13} />}
                Stop
              </button>
            )}
          </div>
        </div>
      </header>

      {/* 3-panel layout */}
      <main className="flex-1 flex overflow-hidden p-4 gap-4">
        {/* Panel 1: Video feed */}
        <div className="flex-1 flex flex-col min-w-0">
          <div className="bg-gray-900/60 border border-gray-800 rounded-xl flex-1 flex flex-col overflow-hidden">
            <div className="px-4 py-2.5 border-b border-gray-800/50 text-xs font-semibold text-gray-400 uppercase tracking-wider">
              Video Feed — Vehicle Tracking
            </div>
            <div className="flex-1 flex items-center justify-center p-2 bg-black/30">
              {snapshot?.video_frame ? (
                <img
                  src={`data:image/jpeg;base64,${snapshot.video_frame}`}
                  alt="Video feed"
                  className="max-w-full max-h-full object-contain rounded-lg"
                />
              ) : (
                <div className="text-gray-600 text-sm flex flex-col items-center gap-2">
                  <Loader2 size={24} className="animate-spin text-gray-700" />
                  Waiting for video…
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Panel 2: RL Agent SUMO */}
        <div className="flex-1 flex flex-col min-w-0">
          <div className="bg-gray-900/60 border border-gray-800 rounded-xl flex-1 flex flex-col overflow-hidden">
            <div className="px-4 py-2.5 border-b border-gray-800/50 text-xs font-semibold text-violet-400 uppercase tracking-wider">
              RL Agent Control
            </div>
            <div className="flex-1 flex items-center justify-center p-4">
              {snapshot?.rl_vehicles ? (
                <IntersectionDiagram
                  vehicles={snapshot.rl_vehicles}
                  tlState={snapshot.rl_tl_state}
                  metrics={snapshot.rl_metrics}
                  label="AI-Controlled"
                />
              ) : (
                <div className="text-gray-600 text-sm">No RL data</div>
              )}
            </div>
          </div>
        </div>

        {/* Panel 3: Fixed-Time Baseline */}
        <div className="flex-1 flex flex-col min-w-0">
          <div className="bg-gray-900/60 border border-gray-800 rounded-xl flex-1 flex flex-col overflow-hidden">
            <div className="px-4 py-2.5 border-b border-gray-800/50 text-xs font-semibold text-amber-400 uppercase tracking-wider">
              Fixed-Time Baseline (35s/3s)
            </div>
            <div className="flex-1 flex items-center justify-center p-4">
              {snapshot?.baseline_vehicles ? (
                <IntersectionDiagram
                  vehicles={snapshot.baseline_vehicles}
                  tlState={snapshot.baseline_tl_state}
                  metrics={snapshot.baseline_metrics}
                  label="Fixed-Time"
                />
              ) : (
                <div className="text-gray-600 text-sm flex flex-col items-center gap-2">
                  <Loader2 size={24} className="animate-spin text-gray-700" />
                  Starting…
                </div>
              )}
            </div>
          </div>
        </div>
      </main>

      {/* Evaluation results (shown when complete) */}
      {isComplete && snapshot.evaluation && (
        <div className="shrink-0 border-t border-gray-800/50 bg-gray-900/80 backdrop-blur-sm px-6 py-4">
          <div className="max-w-[1800px] mx-auto">
            <h3 className="text-sm font-semibold text-gray-300 mb-3">Evaluation Results</h3>
            <div className="grid grid-cols-3 gap-4">
              {(() => {
                const ev = snapshot.evaluation as Record<string, Record<string, unknown>>;
                const rl = ev.rl_metrics as Record<string, number> | undefined;
                const bl = ev.baseline_metrics as Record<string, number> | undefined;
                const imp = ev.improvement_pct as Record<string, string> | undefined;

                if (!rl || !bl) return null;

                return (
                  <>
                    <div className="bg-gray-800/50 rounded-xl p-4">
                      <p className="text-xs text-gray-500 mb-1">Avg Waiting Time</p>
                      <div className="flex items-baseline gap-2">
                        <span className="text-lg font-bold text-violet-400">
                          {rl.avg_waiting_time?.toFixed(1)}s
                        </span>
                        <span className="text-xs text-gray-500">vs {bl.avg_waiting_time?.toFixed(1)}s</span>
                        {imp?.waiting_time && (
                          <span className={`text-xs font-mono ${imp.waiting_time.startsWith('-') ? 'text-emerald-400' : 'text-red-400'}`}>
                            {imp.waiting_time}
                          </span>
                        )}
                      </div>
                    </div>
                    <div className="bg-gray-800/50 rounded-xl p-4">
                      <p className="text-xs text-gray-500 mb-1">Throughput</p>
                      <div className="flex items-baseline gap-2">
                        <span className="text-lg font-bold text-violet-400">{rl.throughput}</span>
                        <span className="text-xs text-gray-500">vs {bl.throughput}</span>
                        {imp?.throughput && (
                          <span className={`text-xs font-mono ${imp.throughput.startsWith('+') ? 'text-emerald-400' : 'text-red-400'}`}>
                            {imp.throughput}
                          </span>
                        )}
                      </div>
                    </div>
                    <div className="bg-gray-800/50 rounded-xl p-4">
                      <p className="text-xs text-gray-500 mb-1">Avg Speed</p>
                      <div className="flex items-baseline gap-2">
                        <span className="text-lg font-bold text-violet-400">
                          {rl.avg_speed?.toFixed(1)} m/s
                        </span>
                        <span className="text-xs text-gray-500">vs {bl.avg_speed?.toFixed(1)}</span>
                        {imp?.avg_speed && (
                          <span className={`text-xs font-mono ${imp.avg_speed.startsWith('+') ? 'text-emerald-400' : 'text-red-400'}`}>
                            {imp.avg_speed}
                          </span>
                        )}
                      </div>
                    </div>
                  </>
                );
              })()}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
