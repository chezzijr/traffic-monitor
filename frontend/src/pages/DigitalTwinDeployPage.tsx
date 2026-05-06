import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowLeft, Play, Square, Gauge, Cpu, Video, AlertTriangle } from 'lucide-react';
import { digitalTwinDeployService, type DeployModelInfo, type DeploySnapshot, type DeployStatus } from '../services/digitalTwinDeployService';

export function DigitalTwinDeployPage() {
  const navigate = useNavigate();
  const [models, setModels] = useState<DeployModelInfo[]>([]);
  const [selectedModel, setSelectedModel] = useState<string>('');
  const [tlId, setTlId] = useState('');
  const [snapshot, setSnapshot] = useState<DeploySnapshot | null>(null);
  const [status, setStatus] = useState<DeployStatus | null>(null);
  const [starting, setStarting] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    digitalTwinDeployService.listModels()
      .then((data) => {
        setModels(data);
        if (data.length > 0) setSelectedModel(data[0].path);
      })
      .catch((err) => setError(err.message || 'Failed to load models'));
  }, []);

  useEffect(() => {
    const poll = async () => {
      try {
        const [snap, stat] = await Promise.all([
          digitalTwinDeployService.getSnapshot(),
          digitalTwinDeployService.getStatus(),
        ]);
        setSnapshot(snap);
        setStatus(stat);
      } catch {
        // ignore transient errors
      }
    };

    poll();
    pollRef.current = setInterval(poll, 250);

    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  const handleStart = async () => {
    if (!selectedModel) return;
    setStarting(true);
    setError(null);
    try {
      await digitalTwinDeployService.startDeploy(selectedModel, tlId || undefined);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to start deploy';
      setError(msg);
    } finally {
      setStarting(false);
    }
  };

  const handleStop = async () => {
    setStopping(true);
    try {
      await digitalTwinDeployService.stopDeploy();
    } finally {
      setStopping(false);
    }
  };

  const phaseLabel = useMemo(() => {
    if (!snapshot?.tl_state) return '--';
    return `Phase ${snapshot.tl_state.phase}`;
  }, [snapshot?.tl_state]);

  const phaseColor = useMemo(() => {
    const state = snapshot?.tl_state?.state || '';
    if (state.includes('G') || state.includes('g')) return 'bg-emerald-500';
    if (state.includes('y')) return 'bg-amber-400';
    return 'bg-red-500';
  }, [snapshot?.tl_state?.state]);

  return (
    <div
      className="min-h-screen text-white"
      style={{
        fontFamily: '"Space Grotesk", "IBM Plex Sans", sans-serif',
        background: 'radial-gradient(1200px circle at 10% 0%, #1f2937 0%, #0b0f1a 45%, #070b12 100%)',
      }}
    >
      {/* Header */}
      <header className="border-b border-white/10 bg-black/40 backdrop-blur">
        <div className="max-w-6xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <button
              onClick={() => navigate('/')}
              className="p-2 rounded-lg hover:bg-white/10 transition-colors"
            >
              <ArrowLeft size={18} />
            </button>
            <div className="flex items-center gap-2">
              <Cpu size={18} className="text-cyan-400" />
              <h1 className="text-lg font-semibold tracking-wide">Digital Twin Deploy</h1>
            </div>
          </div>
          <div className="flex items-center gap-3 text-xs text-slate-300">
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full" style={{ background: status?.running ? '#22c55e' : '#64748b' }} />
              {status?.running ? 'Running' : 'Idle'}
            </div>
            <div className="px-2.5 py-1 rounded-full bg-white/5 border border-white/10">
              Step {status?.step ?? 0}
            </div>
          </div>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-6 py-8 grid grid-cols-1 lg:grid-cols-[360px,1fr] gap-6">
        {/* Control panel */}
        <section className="bg-white/5 border border-white/10 rounded-2xl p-5 shadow-lg shadow-black/30">
          <div className="flex items-center gap-2 mb-4">
            <Gauge size={16} className="text-cyan-400" />
            <h2 className="text-sm font-semibold uppercase tracking-widest text-slate-300">Deploy Control</h2>
          </div>

          <label className="text-xs text-slate-400">Model</label>
          <div className="mt-2 space-y-2">
            {models.length === 0 ? (
              <div className="text-sm text-slate-400">No models found.</div>
            ) : (
              models.map((model) => (
                <label
                  key={model.path}
                  className={`flex items-center justify-between px-3 py-2 rounded-xl border transition-colors cursor-pointer ${
                    selectedModel === model.path
                      ? 'border-cyan-400/60 bg-cyan-400/10'
                      : 'border-white/10 hover:border-white/20'
                  }`}
                >
                  <div className="flex items-center gap-3">
                    <input
                      type="radio"
                      name="model"
                      value={model.path}
                      checked={selectedModel === model.path}
                      onChange={() => setSelectedModel(model.path)}
                      className="accent-cyan-400"
                    />
                    <div>
                      <div className="text-sm text-slate-200">{model.name}</div>
                      <div className="text-xs text-slate-500">{model.size_mb} MB</div>
                    </div>
                  </div>
                </label>
              ))
            )}
          </div>

          <div className="mt-4">
            <label className="text-xs text-slate-400">Traffic Light ID (optional)</label>
            <input
              type="text"
              value={tlId}
              onChange={(e) => setTlId(e.target.value)}
              placeholder="Auto-select if empty"
              className="mt-2 w-full bg-black/30 border border-white/10 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-cyan-400/60"
            />
          </div>

          {error && (
            <div className="mt-4 flex items-center gap-2 text-xs text-red-300 bg-red-500/10 border border-red-500/30 rounded-lg px-3 py-2">
              <AlertTriangle size={14} />
              {error}
            </div>
          )}

          <div className="mt-5 flex gap-2">
            <button
              onClick={handleStart}
              disabled={starting || !selectedModel}
              className="flex-1 flex items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold bg-cyan-500/80 hover:bg-cyan-400 transition-colors disabled:opacity-40"
            >
              <Play size={14} />
              {starting ? 'Starting…' : 'Start'}
            </button>
            <button
              onClick={handleStop}
              disabled={stopping || !status?.running}
              className="flex-1 flex items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold bg-red-500/30 hover:bg-red-500/40 transition-colors disabled:opacity-40"
            >
              <Square size={14} />
              {stopping ? 'Stopping…' : 'Stop'}
            </button>
          </div>

          <div className="mt-6 grid grid-cols-2 gap-3 text-xs text-slate-400">
            <div className="bg-white/5 border border-white/10 rounded-lg p-3">
              <div className="text-[10px] uppercase tracking-widest text-slate-500">TL ID</div>
              <div className="text-sm text-slate-200 mt-1">{status?.tl_id || '—'}</div>
            </div>
            <div className="bg-white/5 border border-white/10 rounded-lg p-3">
              <div className="text-[10px] uppercase tracking-widest text-slate-500">Last Action</div>
              <div className="text-sm text-slate-200 mt-1">{status?.last_action ?? '—'}</div>
            </div>
          </div>
        </section>

        {/* Live panels */}
        <section className="space-y-6">
          <div className="bg-white/5 border border-white/10 rounded-2xl overflow-hidden shadow-lg shadow-black/30">
            <div className="px-4 py-2 border-b border-white/10 text-xs uppercase tracking-widest text-slate-400 flex items-center gap-2">
              <Video size={14} className="text-cyan-400" />
              Live Video Feed
            </div>
            <div className="h-[420px] bg-black/40 flex items-center justify-center">
              {snapshot?.video_frame ? (
                <img
                  src={`data:image/jpeg;base64,${snapshot.video_frame}`}
                  alt="Digital twin video"
                  className="max-h-full max-w-full object-contain"
                />
              ) : (
                <div className="text-slate-500 text-sm">Waiting for frames…</div>
              )}
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div className="bg-white/5 border border-white/10 rounded-2xl p-4 shadow-lg shadow-black/30">
              <div className="text-xs uppercase tracking-widest text-slate-400 mb-3">Traffic Light State</div>
              <div className="flex items-center gap-3">
                <div className={`w-3 h-3 rounded-full ${phaseColor}`} />
                <div className="text-sm text-slate-200">{phaseLabel}</div>
              </div>
              <div className="mt-2 text-xs text-slate-500">Program: {snapshot?.tl_state?.program || '—'}</div>
              <div className="mt-2 text-xs text-slate-500">State: {snapshot?.tl_state?.state || '—'}</div>
            </div>

            <div className="bg-white/5 border border-white/10 rounded-2xl p-4 shadow-lg shadow-black/30">
              <div className="text-xs uppercase tracking-widest text-slate-400 mb-3">Simulation Metrics</div>
              <div className="grid grid-cols-2 gap-3 text-xs text-slate-300">
                <div>
                  <div className="text-[10px] uppercase tracking-widest text-slate-500">Vehicles</div>
                  <div className="text-sm text-slate-200">{snapshot?.metrics?.num_vehicles ?? 0}</div>
                </div>
                <div>
                  <div className="text-[10px] uppercase tracking-widest text-slate-500">Arrived</div>
                  <div className="text-sm text-slate-200">{snapshot?.metrics?.arrived ?? 0}</div>
                </div>
                <div>
                  <div className="text-[10px] uppercase tracking-widest text-slate-500">Wait Time</div>
                  <div className="text-sm text-slate-200">{snapshot?.metrics?.total_waiting_time ?? 0}s</div>
                </div>
                <div>
                  <div className="text-[10px] uppercase tracking-widest text-slate-500">Avg Speed</div>
                  <div className="text-sm text-slate-200">{snapshot?.metrics?.avg_speed ?? 0} m/s</div>
                </div>
              </div>
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}
