import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowLeft, Play, Square, Gauge, Cpu, Video, AlertTriangle, Map, Layers, Eye } from 'lucide-react';
import { digitalTwinDeployService, type DeploySnapshot, type DeployStatus } from '../services/digitalTwinDeployService';
import { mapService } from '../services/mapService';
import { modelService } from '../services/modelService';
import type { TrainedModel } from '../types';

export function DigitalTwinDeployPage() {
  const navigate = useNavigate();
  const [trainedModels, setTrainedModels] = useState<TrainedModel[]>([]);
  const [networks, setNetworks] = useState<string[]>([]);
  const [selectedModel, setSelectedModel] = useState<string>('');
  const [selectedModelObj, setSelectedModelObj] = useState<TrainedModel | null>(null);
  const [selectedNetwork, setSelectedNetwork] = useState<string>('');
  const [tlId, setTlId] = useState('');
  const [snapshot, setSnapshot] = useState<DeploySnapshot | null>(null);
  const [status, setStatus] = useState<DeployStatus | null>(null);
  const [starting, setStarting] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    Promise.all([
      modelService.listModels(),
      mapService.getNetworks(),
    ])
      .then(([models, nets]) => {
        setTrainedModels(models);
        setNetworks(nets);
        if (models.length > 0) {
          setSelectedModel(models[0].model_path);
          setSelectedModelObj(models[0]);
          setSelectedNetwork(models[0].network_id);
        }
      })
      .catch((err) => setError(err.message || 'Failed to load data'));
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
      const tlIds = selectedModelObj?.tl_ids;
      await digitalTwinDeployService.startDeploy(
        selectedModel,
        tlId || undefined,
        selectedNetwork || undefined,
        tlIds,
      );
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to start deploy';
      setError(msg);
    } finally {
      setStarting(false);
    }
  };

  const handleModelSelect = (model: TrainedModel) => {
    setSelectedModel(model.model_path);
    setSelectedModelObj(model);
    setSelectedNetwork(model.network_id);
    if (model.tl_id) {
      setTlId(model.tl_id);
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

  const isMultiAgent = status?.is_multi_agent || snapshot?.is_multi_agent;

  const phaseLabel = useMemo(() => {
    if (!snapshot?.tl_state) return '--';
    if (isMultiAgent && typeof snapshot.tl_state === 'object' && !('phase' in snapshot.tl_state)) {
      const states = snapshot.tl_state as Record<string, { phase: number }>;
      const keys = Object.keys(states);
      if (keys.length === 0) return '--';
      return `${keys.length} TLs active`;
    }
    const st = snapshot.tl_state as { phase: number };
    return `Phase ${st.phase}`;
  }, [snapshot?.tl_state, isMultiAgent]);

  const phaseColor = useMemo(() => {
    if (!snapshot?.tl_state) return 'bg-slate-500';
    if (isMultiAgent && typeof snapshot.tl_state === 'object' && !('state' in snapshot.tl_state)) {
      return 'bg-cyan-500';
    }
    const st = snapshot.tl_state as { state?: string };
    const state = st?.state || '';
    if (state.includes('G') || state.includes('g')) return 'bg-emerald-500';
    if (state.includes('y')) return 'bg-amber-400';
    return 'bg-red-500';
  }, [snapshot?.tl_state, isMultiAgent]);

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

          <label className="text-xs text-slate-400">Model (Trained Models)</label>
          <div className="mt-2 space-y-2 max-h-[160px] overflow-y-auto pr-1 custom-scrollbar">
            {trainedModels.length === 0 ? (
              <div className="text-sm text-slate-400">No trained models found.</div>
            ) : (
              trainedModels.map((model) => (
                <label
                  key={model.model_id}
                  className={`flex items-center justify-between px-3 py-2 rounded-xl border transition-colors cursor-pointer ${
                    selectedModel === model.model_path
                      ? 'border-cyan-400/60 bg-cyan-400/10'
                      : 'border-white/10 hover:border-white/20'
                  }`}
                >
                  <div className="flex items-center gap-3">
                    <input
                      type="radio"
                      name="model"
                      value={model.model_path}
                      checked={selectedModel === model.model_path}
                      onChange={() => handleModelSelect(model)}
                      className="accent-cyan-400"
                    />
                    <div>
                      <div className="text-sm text-slate-200">{model.model_id}</div>
                      <div className="text-[10px] text-slate-500 uppercase tracking-tight">{model.algorithm} • {model.network_id}</div>
                    </div>
                  </div>
                </label>
              ))
            )}
          </div>

          <div className="mt-4">
            <div className="flex items-center gap-2 mb-2">
              <Map size={14} className="text-cyan-400" />
              <label className="text-xs text-slate-400">Target Network</label>
            </div>
            <select
              value={selectedNetwork}
              onChange={(e) => setSelectedNetwork(e.target.value)}
              className="w-full bg-black/30 border border-white/10 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-cyan-400/60"
            >
              <option value="">Dynamic Grid (Default)</option>
              {networks.map((net) => (
                <option key={net} value={net}>
                  {net}
                </option>
              ))}
            </select>
            <p className="mt-1.5 text-[10px] text-slate-500 italic">
              {selectedNetwork ? `Using saved network layout: ${selectedNetwork}` : 'Map will be generated as a dynamic grid.'}
            </p>
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

          {status?.running && (
            <button
              onClick={() => navigate('/simulation/view')}
              className="mt-3 w-full flex items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold bg-violet-500/30 hover:bg-violet-500/40 border border-violet-500/40 transition-colors"
            >
              <Eye size={14} />
              View Simulation
            </button>
          )}

          <div className="mt-6 grid grid-cols-2 gap-3 text-xs text-slate-400">
            <div className="bg-white/5 border border-white/10 rounded-lg p-3">
              <div className="text-[10px] uppercase tracking-widest text-slate-500">Mode</div>
              <div className="text-sm text-slate-200 mt-1">
                {isMultiAgent ? (
                  <span className="inline-flex items-center gap-1.5">
                    <span className="w-2 h-2 rounded-full bg-violet-500" />
                    Multi-Agent
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1.5">
                    <span className="w-2 h-2 rounded-full bg-cyan-500" />
                    Single-Agent
                  </span>
                )}
              </div>
            </div>
            <div className="bg-white/5 border border-white/10 rounded-lg p-3">
              <div className="text-[10px] uppercase tracking-widest text-slate-500">Last Action</div>
              <div className="text-sm text-slate-200 mt-1">
                {Array.isArray(status?.last_action)
                  ? status.last_action.map((a, i) => `TL${i}:${a}`).join(', ')
                  : status?.last_action ?? '—'}
              </div>
            </div>
            {isMultiAgent && (
              <>
                <div className="bg-white/5 border border-white/10 rounded-lg p-3">
                  <div className="text-[10px] uppercase tracking-widest text-slate-500">AI-Controlled</div>
                  <div className="text-sm text-emerald-300 mt-1">
                    {status?.controlled_tl_ids?.length ?? snapshot?.controlled_tl_ids?.length ?? 0} intersections
                  </div>
                </div>
                <div className="bg-white/5 border border-white/10 rounded-lg p-3">
                  <div className="text-[10px] uppercase tracking-widest text-slate-500">Fixed-Time</div>
                  <div className="text-sm text-amber-300 mt-1">
                    {status?.fixed_tl_ids?.length ?? snapshot?.fixed_tl_ids?.length ?? 0} intersections
                  </div>
                </div>
              </>
            )}
            {!isMultiAgent && (
              <div className="bg-white/5 border border-white/10 rounded-lg p-3">
                <div className="text-[10px] uppercase tracking-widest text-slate-500">TL ID</div>
                <div className="text-sm text-slate-200 mt-1">{status?.tl_id || '—'}</div>
              </div>
            )}
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
              {isMultiAgent && snapshot?.tl_state && typeof snapshot.tl_state === 'object' && !('phase' in snapshot.tl_state) ? (
                <div className="space-y-2 max-h-[120px] overflow-y-auto pr-1">
                  {Object.entries(snapshot.tl_state as Record<string, { tl_id: string; phase: number; state: string; program: string }>).map(([id, st]) => {
                    const isControlled = snapshot.controlled_tl_ids?.includes(id);
                    const stState = st.state || '';
                    const color = stState.includes('G') || stState.includes('g') ? 'bg-emerald-500'
                      : stState.includes('y') ? 'bg-amber-400' : 'bg-red-500';
                    return (
                      <div key={id} className="flex items-center gap-2 text-xs">
                        <div className={`w-2 h-2 rounded-full ${color}`} />
                        <span className="text-slate-300 font-mono text-[10px]">{id.slice(0, 12)}</span>
                        <span className="text-slate-500">P{st.phase}</span>
                        {isControlled && <span className="text-[9px] px-1.5 py-0.5 rounded bg-violet-500/30 text-violet-300">AI</span>}
                        {!isControlled && <span className="text-[9px] px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-300">Fixed</span>}
                      </div>
                    );
                  })}
                </div>
              ) : (
                <>
                  <div className="flex items-center gap-3">
                    <div className={`w-3 h-3 rounded-full ${phaseColor}`} />
                    <div className="text-sm text-slate-200">{phaseLabel}</div>
                  </div>
                  <div className="mt-2 text-xs text-slate-500">Program: {(snapshot?.tl_state as { program?: string })?.program || '—'}</div>
                  <div className="mt-2 text-xs text-slate-500">State: {(snapshot?.tl_state as { state?: string })?.state || '—'}</div>
                </>
              )}
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
