import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowLeft, Cpu, Activity, Car, Gauge, Zap, Clock } from 'lucide-react';
import {
  digitalTwinDeployService,
  type DeploySnapshot,
  type DeployStatus,
} from '../services/digitalTwinDeployService';

// ── Types ──────────────────────────────────────────────────────────────

interface Junction {
  id: string;
  x: number;
  y: number;
}

interface LaneShape {
  id: string;
  shape: Array<{ x: number; y: number }>;
}

interface EdgeInfo {
  id: string;
  lanes: LaneShape[];
}

interface NetworkGeometry {
  junctions: Junction[];
  edges: EdgeInfo[];
}

interface Vehicle {
  id: string;
  x: number;
  y: number;
  speed: number;
  waiting_time: number;
}

interface TLState {
  tl_id: string;
  phase: number;
  state: string;
  program: string;
}

// ── Canvas drawing ─────────────────────────────────────────────────────

function computeTransform(
  geometry: NetworkGeometry,
  canvasW: number,
  canvasH: number,
) {
  if (!geometry.junctions.length) {
    return { scale: 1, offsetX: 0, offsetY: 0, flipY: true };
  }

  let minX = Infinity,
    maxX = -Infinity,
    minY = Infinity,
    maxY = -Infinity;

  for (const j of geometry.junctions) {
    minX = Math.min(minX, j.x);
    maxX = Math.max(maxX, j.x);
    minY = Math.min(minY, j.y);
    maxY = Math.max(maxY, j.y);
  }

  // Also consider edge shapes for bounds
  for (const e of geometry.edges) {
    for (const lane of e.lanes) {
      for (const p of lane.shape) {
        minX = Math.min(minX, p.x);
        maxX = Math.max(maxX, p.x);
        minY = Math.min(minY, p.y);
        maxY = Math.max(maxY, p.y);
      }
    }
  }

  const padding = 60;
  const dataW = maxX - minX || 1;
  const dataH = maxY - minY || 1;
  const scale = Math.min(
    (canvasW - padding * 2) / dataW,
    (canvasH - padding * 2) / dataH,
  );
  const offsetX = padding + ((canvasW - padding * 2) - dataW * scale) / 2 - minX * scale;
  const offsetY = padding + ((canvasH - padding * 2) - dataH * scale) / 2 - minY * scale;

  return { scale, offsetX, offsetY, flipY: true };
}

function toCanvas(
  x: number,
  y: number,
  transform: ReturnType<typeof computeTransform>,
  canvasH: number,
) {
  const cx = x * transform.scale + transform.offsetX;
  // SUMO Y-axis is inverted relative to canvas (SUMO: up=+Y, canvas: down=+Y)
  const cy = transform.flipY
    ? canvasH - (y * transform.scale + transform.offsetY)
    : y * transform.scale + transform.offsetY;
  return { cx, cy };
}

/**
 * Parse a SUMO TL state string to derive per-direction colors.
 * State chars: G/g = green, y = yellow, r = red.
 * For a standard 4-arm intersection the state is typically split into
 * groups of links per direction. We simplify by splitting the state
 * into 4 quadrants (N/S/E/W-ish) if the link count allows it.
 */
function parseTLDirectionColors(stateStr: string): {
  ns: string;
  ew: string;
} {
  if (!stateStr) return { ns: '#64748b', ew: '#64748b' };

  const half = Math.floor(stateStr.length / 2);
  const firstHalf = stateStr.slice(0, half);
  const secondHalf = stateStr.slice(half);

  const colorFor = (s: string): string => {
    if (s.includes('G') || s.includes('g')) return '#22c55e';
    if (s.includes('y')) return '#eab308';
    return '#ef4444';
  };

  return { ns: colorFor(firstHalf), ew: colorFor(secondHalf) };
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
) {
  const controlledSet = new Set(controlledTlIds);

  for (const junc of geometry.junctions) {
    const { cx, cy } = toCanvas(junc.x, junc.y, transform, canvasH);
    const isControlled = controlledSet.has(junc.id);
    const isTL = junc.id in tlStates;

    // Junction circle
    const radius = isControlled ? 16 : isTL ? 13 : 8;

    if (isControlled) {
      // AI-controlled glow
      ctx.save();
      ctx.shadowColor = '#a78bfa';
      ctx.shadowBlur = 18;
      ctx.beginPath();
      ctx.arc(cx, cy, radius + 3, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(167, 139, 250, 0.25)';
      ctx.fill();
      ctx.restore();
    }

    // Base junction fill
    ctx.beginPath();
    ctx.arc(cx, cy, radius, 0, Math.PI * 2);
    ctx.fillStyle = isControlled ? '#1e1b4b' : isTL ? '#1e293b' : '#1e293b';
    ctx.fill();
    ctx.strokeStyle = isControlled ? '#a78bfa' : '#475569';
    ctx.lineWidth = isControlled ? 2.5 : 1.5;
    ctx.stroke();

    // Draw TL state indicators (directional lights)
    if (isTL) {
      const st = tlStates[junc.id];
      const { ns, ew } = parseTLDirectionColors(st.state);
      const indicatorR = 4;
      const offset = radius + 6;

      // N/S indicators (vertical)
      ctx.beginPath();
      ctx.arc(cx, cy - offset, indicatorR, 0, Math.PI * 2);
      ctx.fillStyle = ns;
      ctx.fill();

      ctx.beginPath();
      ctx.arc(cx, cy + offset, indicatorR, 0, Math.PI * 2);
      ctx.fillStyle = ns;
      ctx.fill();

      // E/W indicators (horizontal)
      ctx.beginPath();
      ctx.arc(cx + offset, cy, indicatorR, 0, Math.PI * 2);
      ctx.fillStyle = ew;
      ctx.fill();

      ctx.beginPath();
      ctx.arc(cx - offset, cy, indicatorR, 0, Math.PI * 2);
      ctx.fillStyle = ew;
      ctx.fill();
    }

    // AI badge
    if (isControlled) {
      ctx.font = 'bold 8px "Space Grotesk", sans-serif';
      ctx.fillStyle = '#c4b5fd';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText('AI', cx, cy);
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

export function SimulationViewPage() {
  const navigate = useNavigate();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const networkCacheRef = useRef<NetworkGeometry | null>(null);

  const [snapshot, setSnapshot] = useState<DeploySnapshot | null>(null);
  const [status, setStatus] = useState<DeployStatus | null>(null);
  const [canvasSize, setCanvasSize] = useState({ w: 800, h: 600 });

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Resize observer for responsive canvas
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect;
        setCanvasSize({ w: Math.floor(width), h: Math.floor(height) });
      }
    });
    observer.observe(container);
    return () => observer.disconnect();
  }, []);

  // Poll snapshot and status
  useEffect(() => {
    const poll = async () => {
      try {
        const [snap, stat] = await Promise.all([
          digitalTwinDeployService.getSnapshot(),
          digitalTwinDeployService.getStatus(),
        ]);

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

  // Extract TL states as a map
  const tlStates = useMemo<Record<string, TLState>>(() => {
    if (!snapshot?.tl_state) return {};
    const st = snapshot.tl_state;
    // Multi-agent: tl_state is already Record<string, TLState>
    if (typeof st === 'object' && !('tl_id' in st)) {
      return st as Record<string, TLState>;
    }
    // Single-agent: tl_state has tl_id at top level
    const single = st as TLState;
    if (single.tl_id) {
      return { [single.tl_id]: single };
    }
    return {};
  }, [snapshot?.tl_state]);

  const controlledTlIds = useMemo(
    () => snapshot?.controlled_tl_ids || status?.controlled_tl_ids || [],
    [snapshot?.controlled_tl_ids, status?.controlled_tl_ids],
  );

  const vehicles = useMemo<Vehicle[]>(
    () =>
      (snapshot?.vehicles || []).map((v) => ({
        id: v.id,
        x: v.x,
        y: v.y,
        speed: v.speed,
        waiting_time: v.waiting_time,
      })),
    [snapshot?.vehicles],
  );

  // Draw canvas
  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const { w, h } = canvasSize;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    canvas.style.width = `${w}px`;
    canvas.style.height = `${h}px`;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    // Background
    ctx.fillStyle = '#0f172a';
    ctx.fillRect(0, 0, w, h);

    // Subtle grid
    ctx.strokeStyle = 'rgba(51, 65, 85, 0.3)';
    ctx.lineWidth = 0.5;
    const gridSpacing = 40;
    for (let x = 0; x < w; x += gridSpacing) {
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, h);
      ctx.stroke();
    }
    for (let y = 0; y < h; y += gridSpacing) {
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(w, y);
      ctx.stroke();
    }

    const geometry = networkCacheRef.current;
    if (!geometry || geometry.junctions.length === 0) {
      // No network data yet
      ctx.font = '14px "Space Grotesk", sans-serif';
      ctx.fillStyle = '#94a3b8';
      ctx.textAlign = 'center';
      ctx.fillText('Waiting for simulation data…', w / 2, h / 2);
      return;
    }

    const transform = computeTransform(geometry, w, h);

    drawNetwork(ctx, geometry, transform, h);
    drawJunctions(ctx, geometry, transform, h, controlledTlIds, tlStates);
    drawVehicles(ctx, vehicles, transform, h);
  }, [canvasSize, controlledTlIds, tlStates, vehicles]);

  useEffect(() => {
    const raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [draw]);

  const isMultiAgent = status?.is_multi_agent || snapshot?.is_multi_agent;
  const waitingVehicles = vehicles.filter((v) => v.speed < 0.5).length;

  return (
    <div
      className="min-h-screen text-white flex flex-col"
      style={{
        fontFamily: '"Space Grotesk", "IBM Plex Sans", sans-serif',
        background:
          'radial-gradient(1200px circle at 10% 0%, #1f2937 0%, #0b0f1a 45%, #070b12 100%)',
      }}
    >
      {/* ── Header ───────────────────────────────────────────────── */}
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
              <h1 className="text-lg font-semibold tracking-wide">
                Simulation Viewer
              </h1>
            </div>
          </div>

          <div className="flex items-center gap-4 text-xs text-slate-300">
            <div className="flex items-center gap-2">
              <span
                className="w-2 h-2 rounded-full"
                style={{
                  background: status?.running ? '#22c55e' : '#64748b',
                }}
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

      {/* ── Main ─────────────────────────────────────────────────── */}
      <div className="flex-1 flex overflow-hidden">
        {/* Canvas area */}
        <div ref={containerRef} className="flex-1 relative">
          <canvas ref={canvasRef} className="absolute inset-0" />

          {/* Legend overlay */}
          <div className="absolute bottom-4 left-4 bg-black/60 backdrop-blur border border-white/10 rounded-xl px-4 py-3 text-xs text-slate-300 space-y-2">
            <div className="text-[10px] uppercase tracking-widest text-slate-500 font-semibold mb-1">
              Legend
            </div>
            <div className="flex items-center gap-2">
              <span className="w-3 h-3 rounded-full bg-[#38bdf8]" />
              Moving vehicle
            </div>
            <div className="flex items-center gap-2">
              <span className="w-3 h-3 rounded-full bg-[#fb923c]" />
              Waiting vehicle
            </div>
            <div className="flex items-center gap-2">
              <span
                className="w-3 h-3 rounded-full border-2 border-violet-400"
                style={{ background: '#1e1b4b' }}
              />
              AI-controlled intersection
            </div>
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-[#22c55e]" />
              <span className="w-2 h-2 rounded-full bg-[#ef4444]" />
              Traffic light (green / red)
            </div>
          </div>
        </div>

        {/* ── Sidebar metrics ────────────────────────────────────── */}
        <aside className="w-[300px] border-l border-white/10 bg-black/30 backdrop-blur overflow-y-auto shrink-0">
          <div className="p-4 space-y-4">
            {/* Metrics cards */}
            <div className="space-y-3">
              <div className="text-[10px] uppercase tracking-widest text-slate-500 font-semibold flex items-center gap-1.5">
                <Activity size={12} className="text-cyan-400" />
                Simulation Metrics
              </div>

              <div className="grid grid-cols-2 gap-2">
                <MetricCard
                  icon={<Car size={14} />}
                  label="Vehicles"
                  value={snapshot?.metrics?.num_vehicles ?? 0}
                  color="text-cyan-400"
                />
                <MetricCard
                  icon={<Clock size={14} />}
                  label="Waiting"
                  value={waitingVehicles}
                  color="text-orange-400"
                />
                <MetricCard
                  icon={<Gauge size={14} />}
                  label="Avg Speed"
                  value={`${snapshot?.metrics?.avg_speed ?? 0} m/s`}
                  color="text-emerald-400"
                />
                <MetricCard
                  icon={<Zap size={14} />}
                  label="Arrived"
                  value={snapshot?.metrics?.arrived ?? 0}
                  color="text-violet-400"
                />
              </div>

              <div className="bg-white/5 border border-white/10 rounded-lg p-3">
                <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-1">
                  Total Wait Time
                </div>
                <div className="text-lg font-semibold text-amber-300">
                  {snapshot?.metrics?.total_waiting_time ?? 0}s
                </div>
              </div>
            </div>

            {/* Traffic lights */}
            <div className="space-y-2">
              <div className="text-[10px] uppercase tracking-widest text-slate-500 font-semibold">
                Traffic Light States
              </div>
              <div className="space-y-1.5 max-h-[300px] overflow-y-auto pr-1">
                {Object.entries(tlStates).map(([id, st]) => {
                  const isAI = controlledTlIds.includes(id);
                  const { ns, ew } = parseTLDirectionColors(st.state);
                  return (
                    <div
                      key={id}
                      className={`flex items-center gap-2 text-xs px-3 py-2 rounded-lg border ${
                        isAI
                          ? 'border-violet-500/40 bg-violet-500/10'
                          : 'border-white/10 bg-white/5'
                      }`}
                    >
                      <div className="flex gap-1">
                        <span
                          className="w-2.5 h-2.5 rounded-full"
                          style={{ background: ns }}
                          title="N/S"
                        />
                        <span
                          className="w-2.5 h-2.5 rounded-full"
                          style={{ background: ew }}
                          title="E/W"
                        />
                      </div>
                      <span className="text-slate-300 font-mono text-[10px] truncate flex-1">
                        {id}
                      </span>
                      <span className="text-slate-500 text-[10px]">
                        P{st.phase}
                      </span>
                      {isAI ? (
                        <span className="text-[9px] px-1.5 py-0.5 rounded bg-violet-500/30 text-violet-300">
                          AI
                        </span>
                      ) : (
                        <span className="text-[9px] px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-300">
                          Fixed
                        </span>
                      )}
                    </div>
                  );
                })}
                {Object.keys(tlStates).length === 0 && (
                  <div className="text-xs text-slate-500 text-center py-3">
                    No traffic light data yet
                  </div>
                )}
              </div>
            </div>

            {/* AI Action */}
            <div className="bg-white/5 border border-white/10 rounded-lg p-3">
              <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-1">
                Last AI Action
              </div>
              <div className="text-sm font-mono text-slate-200">
                {snapshot?.ai_action != null
                  ? Array.isArray(snapshot.ai_action)
                    ? snapshot.ai_action
                        .map((a, i) => `TL${i}:${a}`)
                        .join(', ')
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

// ── Helper components ──────────────────────────────────────────────────

function MetricCard({
  icon,
  label,
  value,
  color,
}: {
  icon: React.ReactNode;
  label: string;
  value: string | number;
  color: string;
}) {
  return (
    <div className="bg-white/5 border border-white/10 rounded-lg p-3">
      <div className={`flex items-center gap-1.5 text-[10px] uppercase tracking-widest text-slate-500 mb-1 ${color}`}>
        {icon}
        <span className="text-slate-500">{label}</span>
      </div>
      <div className="text-sm font-semibold text-slate-200">{value}</div>
    </div>
  );
}
