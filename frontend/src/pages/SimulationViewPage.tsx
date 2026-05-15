import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { MapContainer, TileLayer, CircleMarker, Tooltip, useMap } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';
import { ArrowLeft, Cpu, Activity, Car, Gauge, Zap, Clock, BrainCircuit } from 'lucide-react';
import {
  digitalTwinDeployService,
  type DeploySnapshot,
  type DeployStatus,
} from '../services/digitalTwinDeployService';
import { api } from '../services/api';
import type { NetworkJunction, NetworkMetadata } from '../types';

// ── Types ──────────────────────────────────────────────────────────────

interface TLState {
  tl_id: string;
  phase: number;
  state: string;
  program: string;
}

// ── Helpers ────────────────────────────────────────────────────────────

function tlStateColor(stateStr: string): string {
  if (!stateStr) return '#64748b';
  if (stateStr.includes('G') || stateStr.includes('g')) return '#22c55e';
  if (stateStr.includes('y')) return '#eab308';
  return '#ef4444';
}

// Auto-fit map to junction bounds on first load
function MapAutoFit({ junctions }: { junctions: NetworkJunction[] }) {
  const map = useMap();
  const fitted = useRef(false);

/**
 * SUMO state has 1 char per controlled link (lane), so a 4-way with 4
 * lanes per approach emits a 16-char state. Run-length compressing the
 * normalized state collapses that to 1 entry per approach: 1-way → 1,
 * 2-way → 2, 4-way → 4 (matching what a driver actually sees).
 */
const APPROACH_COLOR: Record<string, string> = {
  green: '#22c55e',
  yellow: '#eab308',
  red: '#ef4444',
  off: '#9ca3af',
};
function normalizeSumoCharCanvas(c: string): string {
  if (c === 'G' || c === 'g') return 'green';
  if (c === 'y' || c === 'Y') return 'yellow';
  if (c === 'r' || c === 'R') return 'red';
  return 'off';
}

function detectArityCanvas(len: number): number {
  if (len <= 0) return 0;
  if (len === 1) return 1;
  if (len >= 4 && len % 4 === 0) return 4;
  if (len === 3 || (len === 6 && len % 4 !== 0)) return 3;
  return 2;
}

function dominantApproachColorCanvas(chunk: string): string {
  let g = 0, y = 0, r = 0;
  for (const c of chunk) {
    const k = normalizeSumoCharCanvas(c);
    if (k === 'green') g++;
    else if (k === 'yellow') y++;
    else if (k === 'red') r++;
  }
  if (y > 0 && y >= Math.max(g, r)) return 'yellow';
  if (g > r) return 'green';
  if (r > g) return 'red';
  if (g === r && g > 0) return 'yellow';
  return 'off';
}

function compressStateToApproachesCanvas(stateStr: string): string[] {
  if (!stateStr) return [];
  const arity = detectArityCanvas(stateStr.length);
  const chunkSize = Math.floor(stateStr.length / arity);
  if (chunkSize === 0) return [];
  const result: string[] = [];
  for (let i = 0; i < arity; i++) {
    const start = i * chunkSize;
    const end = i === arity - 1 ? stateStr.length : start + chunkSize;
    result.push(dominantApproachColorCanvas(stateStr.slice(start, end)));
  }
  return result;
}

function drawNetwork(
  ctx: CanvasRenderingContext2D,
  geometry: NetworkGeometry,
  transform: ReturnType<typeof computeTransform>,
  canvasH: number,
) {
  // Draw edges (lanes)
  ctx.lineWidth = 3;
  ctx.strokeStyle = '#475569';
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';

  for (const edge of geometry.edges) {
    for (const lane of edge.lanes) {
      if (lane.shape.length < 2) continue;
      ctx.beginPath();
      const start = toCanvas(lane.shape[0].x, lane.shape[0].y, transform, canvasH);
      ctx.moveTo(start.cx, start.cy);
      for (let i = 1; i < lane.shape.length; i++) {
        const p = toCanvas(lane.shape[i].x, lane.shape[i].y, transform, canvasH);
        ctx.lineTo(p.cx, p.cy);
      }
      ctx.stroke();
    }
  }

  // Draw wider road overlay for better appearance
  ctx.lineWidth = 6;
  ctx.strokeStyle = '#334155';
  ctx.globalCompositeOperation = 'destination-over';
  for (const edge of geometry.edges) {
    for (const lane of edge.lanes) {
      if (lane.shape.length < 2) continue;
      ctx.beginPath();
      const start = toCanvas(lane.shape[0].x, lane.shape[0].y, transform, canvasH);
      ctx.moveTo(start.cx, start.cy);
      for (let i = 1; i < lane.shape.length; i++) {
        const p = toCanvas(lane.shape[i].x, lane.shape[i].y, transform, canvasH);
        ctx.lineTo(p.cx, p.cy);
      }
      ctx.stroke();
    }
  }
  ctx.globalCompositeOperation = 'source-over';
}

function drawJunctions(
  ctx: CanvasRenderingContext2D,
  geometry: NetworkGeometry,
  transform: ReturnType<typeof computeTransform>,
  canvasH: number,
  controlledTlIds: string[],
  tlStates: Record<string, TLState>,
  agentEnabled: boolean,
) {
  const controlledSet = new Set(controlledTlIds);

  // Color scheme: purple when agent ON, light-red when agent OFF
  const ctrlGlow    = agentEnabled ? '#a78bfa' : '#fca5a5';
  const ctrlGlowBg  = agentEnabled ? 'rgba(167, 139, 250, 0.25)' : 'rgba(252, 165, 165, 0.20)';
  const ctrlFill    = agentEnabled ? '#1e1b4b' : '#1c0505';
  const ctrlBorder  = agentEnabled ? '#a78bfa' : '#f87171';
  const ctrlBadge   = agentEnabled ? '#c4b5fd' : '#fca5a5';

  for (const junc of geometry.junctions) {
    const { cx, cy } = toCanvas(junc.x, junc.y, transform, canvasH);
    const isControlled = controlledSet.has(junc.id);
    const isTL = junc.id in tlStates;

    // Junction circle
    const radius = isControlled ? 16 : isTL ? 13 : 8;

    if (isControlled) {
      // Controlled intersection glow ring
      ctx.save();
      ctx.shadowColor = ctrlGlow;
      ctx.shadowBlur = 18;
      ctx.beginPath();
      ctx.arc(cx, cy, radius + 3, 0, Math.PI * 2);
      ctx.fillStyle = ctrlGlowBg;
      ctx.fill();
      ctx.restore();
    }

    // Base junction fill
    ctx.beginPath();
    ctx.arc(cx, cy, radius, 0, Math.PI * 2);
    ctx.fillStyle = isControlled ? ctrlFill : '#1e293b';
    ctx.fill();
    ctx.strokeStyle = isControlled ? ctrlBorder : '#475569';
    ctx.lineWidth = isControlled ? 2.5 : 1.5;
    ctx.stroke();

    // Draw one bulb per approach (run-length compressed state — matches
    // intersection arity: 1-way → 1 bulb, 2-way → 2, 4-way → 4).
    if (isTL) {
      const st = tlStates[junc.id];
      const groups = compressStateToApproachesCanvas(st.state);
      if (groups.length > 0) {
        const indicatorR = 4;
        const offset = radius + 6;
        const n = groups.length;
        const startAngle = -Math.PI / 2;
        for (let i = 0; i < n; i++) {
          const angle = startAngle + (2 * Math.PI * i) / n;
          const bx = cx + Math.cos(angle) * offset;
          const by = cy + Math.sin(angle) * offset;
          ctx.beginPath();
          ctx.arc(bx, by, indicatorR, 0, Math.PI * 2);
          ctx.fillStyle = APPROACH_COLOR[groups[i]] ?? '#64748b';
          ctx.fill();
        }
      }
    }

    // AI/OFF badge
    if (isControlled) {
      ctx.font = 'bold 8px "Space Grotesk", sans-serif';
      ctx.fillStyle = ctrlBadge;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(agentEnabled ? 'AI' : 'OFF', cx, cy);
    }
  }
}

function drawVehicles(
  ctx: CanvasRenderingContext2D,
  vehicles: Vehicle[],
  transform: ReturnType<typeof computeTransform>,
  canvasH: number,
) {
  for (const v of vehicles) {
    const { cx, cy } = toCanvas(v.x, v.y, transform, canvasH);
    const isWaiting = v.speed < 0.5;
    const radius = 3.5;

    // Glow
    ctx.save();
    ctx.shadowColor = isWaiting ? '#f97316' : '#38bdf8';
    ctx.shadowBlur = 6;
    ctx.beginPath();
    ctx.arc(cx, cy, radius, 0, Math.PI * 2);
    ctx.fillStyle = isWaiting ? '#fb923c' : '#38bdf8';
    ctx.fill();
    ctx.restore();
  }
}

// ── Component ──────────────────────────────────────────────────────────

const HCMC_CENTER: [number, number] = [10.8231, 106.6297];

export function SimulationViewPage() {
  const navigate = useNavigate();

  const [snapshot, setSnapshot] = useState<DeploySnapshot | null>(null);
  const [status, setStatus] = useState<DeployStatus | null>(null);
  const [junctions, setJunctions] = useState<NetworkJunction[]>([]);
  const [togglingAgent, setTogglingAgent] = useState(false);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  // Track deploy_id so we can invalidate the geometry cache when DT swaps to
  // a different deploy (different model/network) — see Bug C.
  const lastDeployIdRef = useRef<string | null>(null);

  // Poll snapshot + status
  useEffect(() => {
    const poll = async () => {
      try {
        const [snap, stat] = await Promise.all([
          digitalTwinDeployService.getSnapshot(),
          digitalTwinDeployService.getStatus(),
        ]);

        // Invalidate geometry cache when DT swaps deploys (Bug C). Without
        // this, switching to a different model/network keeps drawing the
        // old network until a full page reload. Two transitions matter:
        //   1. id → id'  (active swap to a different deploy)
        //   2. id → null (stopped) so the next non-null id starts clean
        const snapDeployId = (snap as DeploySnapshot & { deploy_id?: string | null }).deploy_id ?? null;
        if (snapDeployId !== lastDeployIdRef.current) {
          // Any transition (incl. → null) wipes the cache so the next live
          // deploy redraws from scratch instead of layering on stale geometry.
          networkCacheRef.current = null;
          lastDeployIdRef.current = snapDeployId;
        }

        // Cache network geometry only when it is non-empty
        const geometry = snap.network_geometry;
        const hasGeometry =
          !!geometry &&
          Array.isArray(geometry.junctions) &&
          geometry.junctions.length > 0 &&
          Array.isArray(geometry.edges) &&
          geometry.edges.length > 0;
        if (hasGeometry) {
          if (!networkCacheRef.current || networkCacheRef.current.junctions.length === 0) {
            networkCacheRef.current = geometry;
          }
        }

        setSnapshot(snap);
        setStatus(stat);
      } catch {
        // ignore transient errors
      }
    };

    poll();
    pollRef.current = setInterval(poll, 300);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  // Fetch junction lat/lon from network metadata when network_id is known
  useEffect(() => {
    const networkId = status?.network_id;
    if (!networkId || networkId === loadedNetworkRef.current) return;
    loadedNetworkRef.current = networkId;
    api
      .get<NetworkMetadata>(`/networks/${networkId}`)
      .then((res) => setJunctions(res.data.junctions ?? []))
      .catch(() => {});
  }, [status?.network_id]);

  // TL states keyed by tl_id
  const tlStates = useMemo<Record<string, TLState>>(() => {
    if (!snapshot?.tl_state) return {};
    const st = snapshot.tl_state;
    if (typeof st === 'object' && !('tl_id' in st)) {
      return st as Record<string, TLState>;
    }
    const single = st as TLState;
    if (single.tl_id) return { [single.tl_id]: single };
    return {};
  }, [snapshot?.tl_state]);

  const controlledTlIds = useMemo(
    () => snapshot?.controlled_tl_ids ?? status?.controlled_tl_ids ?? [],
    [snapshot?.controlled_tl_ids, status?.controlled_tl_ids],
  );

  const vehicles = useMemo(
    () => (snapshot?.vehicles ?? []).filter((v) => v.lat != null && v.lng != null),
    [snapshot?.vehicles],
  );

  const isMultiAgent = status?.is_multi_agent ?? snapshot?.is_multi_agent;
  const agentEnabled = status?.agent_enabled ?? snapshot?.agent_enabled ?? true;
  const waitingVehicles = (snapshot?.vehicles ?? []).filter((v) => v.speed < 0.5).length;

  const handleToggleAgent = async () => {
    setTogglingAgent(true);
    try {
      await digitalTwinDeployService.toggleAgent(!agentEnabled);
    } finally {
      setTogglingAgent(false);
    }
  };

  return (
    <div
      className="min-h-screen text-white flex flex-col"
      style={{
        fontFamily: '"Space Grotesk", "IBM Plex Sans", sans-serif',
        background: 'radial-gradient(1200px circle at 10% 0%, #1f2937 0%, #0b0f1a 45%, #070b12 100%)',
      }}
    >
      {/* Header */}
      <header className="border-b border-white/10 bg-black/40 backdrop-blur shrink-0">
        <div className="max-w-[1600px] mx-auto px-6 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <button
              onClick={() => navigate('/digital-twin/deploy')}
              className="p-2 rounded-lg hover:bg-white/10 transition-colors"
            >
              <ArrowLeft size={18} />
            </button>
            <div className="flex items-center gap-2">
              <Cpu size={18} className="text-cyan-400" />
              <h1 className="text-lg font-semibold tracking-wide">Simulation Viewer</h1>
            </div>
          </div>

          <div className="flex items-center gap-4 text-xs text-slate-300">
            <div className="flex items-center gap-2">
              <span
                className="w-2 h-2 rounded-full"
                style={{ background: status?.running ? '#22c55e' : '#64748b' }}
              />
              {status?.running ? 'Running' : 'Idle'}
            </div>
            <div className="px-2.5 py-1 rounded-full bg-white/5 border border-white/10">
              Step {status?.step ?? 0}
            </div>
            {isMultiAgent && (
              <div className="px-2.5 py-1 rounded-full bg-violet-500/20 border border-violet-500/30 text-violet-300">
                Multi-Agent
              </div>
            )}
          </div>
        </div>
      </header>

      {/* Main */}
      <div className="flex-1 flex overflow-hidden">
        {/* Map */}
        <div className="flex-1 relative">
          <MapContainer
            center={HCMC_CENTER}
            zoom={14}
            style={{ height: '100%', width: '100%', background: '#0f172a' }}
            zoomControl={true}
          >
            <TileLayer
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>'
              url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
            />

            <MapAutoFit junctions={junctions} />

            {/* Junction markers */}
            {junctions.map((j) => {
              const tlState = j.tl_id ? tlStates[j.tl_id] : undefined;
              const isControlled = j.tl_id ? controlledTlIds.includes(j.tl_id) : false;
              const isTL = !!tlState;

              const fillColor = isControlled
                ? agentEnabled ? '#a78bfa' : '#f87171'
                : tlState
                  ? tlStateColor(tlState.state)
                  : '#475569';

              const strokeColor = isControlled
                ? agentEnabled ? '#c4b5fd' : '#fca5a5'
                : '#ffffff33';

              const radius = isControlled ? 10 : isTL ? 7 : 4;

              return (
                <CircleMarker
                  key={j.id}
                  center={[j.lat, j.lon]}
                  radius={radius}
                  pathOptions={{
                    fillColor,
                    color: strokeColor,
                    fillOpacity: 0.9,
                    weight: isControlled ? 2 : 1,
                  }}
                >
                  <Tooltip direction="top" offset={[0, -6]} opacity={0.9}>
                    <span className="text-xs font-mono">
                      {j.tl_id ?? j.id}
                      {isControlled && (agentEnabled ? ' · AI' : ' · AI OFF')}
                      {tlState && ` · P${tlState.phase}`}
                    </span>
                  </Tooltip>
                </CircleMarker>
              );
            })}

            {/* Vehicle markers */}
            {vehicles.map((v) => (
              <CircleMarker
                key={v.id}
                center={[v.lat as number, v.lng as number]}
                radius={3}
                pathOptions={{
                  fillColor: v.speed < 0.5 ? '#fb923c' : '#38bdf8',
                  color: 'transparent',
                  fillOpacity: 0.85,
                }}
              />
            ))}
          </MapContainer>

          {/* Legend */}
          <div className="absolute bottom-4 left-4 z-[1000] bg-black/70 backdrop-blur border border-white/10 rounded-xl px-4 py-3 text-xs text-slate-300 space-y-1.5">
            <div className="text-[10px] uppercase tracking-widest text-slate-500 font-semibold mb-1">Legend</div>
            <div className="flex items-center gap-2"><span className="w-3 h-3 rounded-full bg-[#38bdf8]" /> Moving vehicle</div>
            <div className="flex items-center gap-2"><span className="w-3 h-3 rounded-full bg-[#fb923c]" /> Waiting vehicle</div>
            <div className="flex items-center gap-2"><span className="w-3 h-3 rounded-full bg-[#a78bfa]" /> AI-controlled TL</div>
            <div className="flex items-center gap-2"><span className="w-3 h-3 rounded-full bg-[#22c55e]" /> Green phase</div>
            <div className="flex items-center gap-2"><span className="w-3 h-3 rounded-full bg-[#ef4444]" /> Red phase</div>
          </div>
        </div>

        {/* Sidebar */}
        <aside className="w-[300px] border-l border-white/10 bg-black/30 backdrop-blur overflow-y-auto shrink-0">
          <div className="p-4 space-y-4">
            <div className="space-y-3">
              <div className="text-[10px] uppercase tracking-widest text-slate-500 font-semibold flex items-center gap-1.5">
                <Activity size={12} className="text-cyan-400" />
                Simulation Metrics
              </div>

              <div className="grid grid-cols-2 gap-2">
                <MetricCard icon={<Car size={14} />} label="Vehicles" value={snapshot?.metrics?.num_vehicles ?? 0} color="text-cyan-400" />
                <MetricCard icon={<Clock size={14} />} label="Waiting" value={waitingVehicles} color="text-orange-400" />
                <MetricCard icon={<Gauge size={14} />} label="Avg Speed" value={`${snapshot?.metrics?.avg_speed ?? 0} m/s`} color="text-emerald-400" />
                <MetricCard icon={<Zap size={14} />} label="Arrived" value={snapshot?.metrics?.arrived ?? 0} color="text-violet-400" />
              </div>

              <div className="bg-white/5 border border-white/10 rounded-lg p-3">
                <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-1">Total Wait Time</div>
                <div className="text-lg font-semibold text-amber-300">{snapshot?.metrics?.total_waiting_time ?? 0}s</div>
              </div>
            </div>

            {/* Agent toggle */}
            {status?.running && (
              <div className="space-y-2">
                <div className="text-[10px] uppercase tracking-widest text-slate-500 font-semibold flex items-center gap-1.5">
                  <BrainCircuit size={12} className={agentEnabled ? 'text-violet-400' : 'text-red-400'} />
                  AI Agent Control
                </div>
                <button
                  onClick={handleToggleAgent}
                  disabled={togglingAgent}
                  className={`w-full flex items-center justify-between px-3 py-2.5 rounded-xl border text-xs font-semibold transition-all disabled:opacity-40 ${
                    agentEnabled
                      ? 'bg-violet-500/15 border-violet-500/40 text-violet-300 hover:bg-violet-500/25'
                      : 'bg-red-500/15 border-red-400/40 text-red-300 hover:bg-red-500/25'
                  }`}
                >
                  <span className="flex items-center gap-2">
                    <span className={`w-2 h-2 rounded-full ${agentEnabled ? 'bg-violet-400' : 'bg-red-400'}`} />
                    {togglingAgent ? 'Updating…' : agentEnabled ? 'Agent Enabled' : 'Agent Disabled'}
                  </span>
                  <span className={`text-[10px] px-2 py-0.5 rounded-full border ${
                    agentEnabled
                      ? 'bg-violet-500/20 border-violet-500/30 text-violet-400'
                      : 'bg-red-500/20 border-red-400/30 text-red-400'
                  }`}>
                    {agentEnabled ? 'Click to disable' : 'Click to enable'}
                  </span>
                </button>
              </div>
            )}

            {/* Traffic light list */}
            <div className="space-y-2">
              <div className="text-[10px] uppercase tracking-widest text-slate-500 font-semibold">Traffic Light States</div>
              <div className="space-y-1.5 max-h-[300px] overflow-y-auto pr-1">
                {Object.entries(tlStates).map(([id, st]) => {
                  const isAI = controlledTlIds.includes(id);
                  const color = tlStateColor(st.state);
                  return (
                    <div
                      key={id}
                      className={`flex items-center gap-2 text-xs px-3 py-2 rounded-lg border ${
                        isAI && agentEnabled
                          ? 'border-violet-500/40 bg-violet-500/10'
                          : isAI
                            ? 'border-red-400/40 bg-red-500/10'
                            : 'border-white/10 bg-white/5'
                      }`}
                    >
                      <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ background: color }} />
                      <span className="text-slate-300 font-mono text-[10px] truncate flex-1">{id}</span>
                      <span className="text-slate-500 text-[10px]">P{st.phase}</span>
                      {isAI && agentEnabled
                        ? <span className="text-[9px] px-1.5 py-0.5 rounded bg-violet-500/30 text-violet-300">AI</span>
                        : isAI
                          ? <span className="text-[9px] px-1.5 py-0.5 rounded bg-red-500/20 text-red-300">OFF</span>
                          : <span className="text-[9px] px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-300">Fixed</span>
                      }
                    </div>
                  );
                })}
                {Object.keys(tlStates).length === 0 && (
                  <div className="text-xs text-slate-500 text-center py-3">No traffic light data yet</div>
                )}
              </div>
            </div>

            {/* Last AI action */}
            <div className="bg-white/5 border border-white/10 rounded-lg p-3">
              <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-1">Last AI Action</div>
              <div className="text-sm font-mono text-slate-200">
                {snapshot?.ai_action != null
                  ? Array.isArray(snapshot.ai_action)
                    ? snapshot.ai_action.map((a, i) => `TL${i}:${a}`).join(', ')
                    : `Action ${snapshot.ai_action}`
                  : '—'}
              </div>
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}

function MetricCard({
  icon, label, value, color,
}: {
  icon: React.ReactNode;
  label: string;
  value: string | number;
  color: string;
}) {
  return (
    <div className="bg-white/5 border border-white/10 rounded-lg p-3">
      <div className={`flex items-center gap-1.5 text-[10px] uppercase tracking-widest mb-1 ${color}`}>
        {icon}
        <span className="text-slate-500">{label}</span>
      </div>
      <div className="text-sm font-semibold text-slate-200">{value}</div>
    </div>
  );
}
