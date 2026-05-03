import { useMemo } from 'react';
import type { SumoVehicle, TLState } from '../../services/evaluationService';

interface Props {
  vehicles: SumoVehicle[];
  tlState?: TLState;
  label: string;
  metrics?: {
    num_vehicles: number;
    total_waiting_time: number;
    avg_speed: number;
    arrived: number;
  };
}

const SIZE = 400;
const CENTER = SIZE / 2;
const SUMO_EDGE_LENGTH = 15;
const SCALE = (CENTER - 40) / SUMO_EDGE_LENGTH;

const ROAD_WIDTH = 40;
const ROAD_HALF = ROAD_WIDTH / 2;
const VEHICLE_R = 4;

/**
 * Parse the TL state string into per-direction colors.
 * SUMO state string has characters like G, g, r, y for each controlled link.
 * For a 4-arm intersection the first quarter controls one axis, etc.
 */
function parseTlColors(state?: string): { ns: string; ew: string } {
  if (!state) return { ns: '#6b7280', ew: '#6b7280' };

  const n = state.length;
  const half = Math.floor(n / 2);
  const first = state.slice(0, half);
  const second = state.slice(half);

  const toColor = (s: string) => {
    if (s.includes('G') || s.includes('g')) return '#22c55e';
    if (s.includes('y')) return '#eab308';
    return '#ef4444';
  };

  return { ns: toColor(first), ew: toColor(second) };
}

/**
 * Map a SUMO vehicle's (x, y) position to SVG coordinates.

 * SUMO (0,0) is now forced to be the center.
 */
function toSvg(x: number, y: number): { sx: number; sy: number } {
  const sx = CENTER + (x * SCALE);
  const sy = CENTER - (y * SCALE); // SUMO Y increases upwards, SVG Y increases downwards
  return { sx, sy };
}


export function IntersectionDiagram({ vehicles, tlState, label, metrics }: Props) {
  const colors = useMemo(() => parseTlColors(tlState?.state), [tlState?.state]);

  const vehicleDots = useMemo(() => {
    return vehicles.map((v) => {
      const { sx, sy } = toSvg(v.x, v.y);
      const isWaiting = v.speed < 0.5;
      return { id: v.id, sx, sy, isWaiting };
    });
  }, [vehicles]);

  return (
    <div className="flex flex-col items-center">
      {/* Label */}
      <h3 className="text-sm font-semibold text-gray-300 mb-2 uppercase tracking-wider">
        {label}
      </h3>

      <svg
        viewBox={`0 0 ${SIZE} ${SIZE}`}
        className="w-full max-w-[400px] aspect-square rounded-xl"
        style={{ background: '#1a1a2e' }}
      >
        {/* Roads */}
        {/* North-South road */}
        <rect
          x={CENTER - ROAD_HALF}
          y={30}
          width={ROAD_WIDTH}
          height={SIZE - 60}
          fill="#374151"
          rx={2}
        />
        {/* East-West road */}
        <rect
          x={30}
          y={CENTER - ROAD_HALF}
          width={SIZE - 60}
          height={ROAD_WIDTH}
          fill="#374151"
          rx={2}
        />

        {/* Center intersection */}
        <rect
          x={CENTER - ROAD_HALF}
          y={CENTER - ROAD_HALF}
          width={ROAD_WIDTH}
          height={ROAD_WIDTH}
          fill="#4b5563"
        />

        {/* Lane dividers (dashed center lines) */}
        <line x1={CENTER} y1={30} x2={CENTER} y2={CENTER - ROAD_HALF}
          stroke="#6b7280" strokeWidth={1} strokeDasharray="4,4" />
        <line x1={CENTER} y1={CENTER + ROAD_HALF} x2={CENTER} y2={SIZE - 30}
          stroke="#6b7280" strokeWidth={1} strokeDasharray="4,4" />
        <line x1={30} y1={CENTER} x2={CENTER - ROAD_HALF} y2={CENTER}
          stroke="#6b7280" strokeWidth={1} strokeDasharray="4,4" />
        <line x1={CENTER + ROAD_HALF} y1={CENTER} x2={SIZE - 30} y2={CENTER}
          stroke="#6b7280" strokeWidth={1} strokeDasharray="4,4" />

        {/* Traffic lights */}
        {/* North (top) */}
        <circle cx={CENTER - 10} cy={CENTER - ROAD_HALF - 8} r={5} fill={colors.ns} opacity={0.9} />
        {/* South (bottom) */}
        <circle cx={CENTER + 10} cy={CENTER + ROAD_HALF + 8} r={5} fill={colors.ns} opacity={0.9} />
        {/* East (right) */}
        <circle cx={CENTER + ROAD_HALF + 8} cy={CENTER - 10} r={5} fill={colors.ew} opacity={0.9} />
        {/* West (left) */}
        <circle cx={CENTER - ROAD_HALF - 8} cy={CENTER + 10} r={5} fill={colors.ew} opacity={0.9} />

        {/* Direction labels */}
        <text x={CENTER} y={20} textAnchor="middle" fill="#9ca3af" fontSize={10} fontFamily="monospace">N</text>
        <text x={CENTER} y={SIZE - 10} textAnchor="middle" fill="#9ca3af" fontSize={10} fontFamily="monospace">S</text>
        <text x={SIZE - 15} y={CENTER + 4} textAnchor="middle" fill="#9ca3af" fontSize={10} fontFamily="monospace">E</text>
        <text x={15} y={CENTER + 4} textAnchor="middle" fill="#9ca3af" fontSize={10} fontFamily="monospace">W</text>

        {/* Vehicles */}
        {vehicleDots.map((v) => (
          <circle
            key={v.id}
            cx={v.sx}
            cy={v.sy}
            r={VEHICLE_R}
            fill={v.isWaiting ? '#ef4444' : '#22c55e'}
            opacity={0.85}
            style={{ transition: 'cx 0.15s, cy 0.15s' }}
          >
            <title>{v.id}</title>
          </circle>
        ))}
      </svg>

      {/* Metrics overlay */}
      {metrics && (
        <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-gray-400 font-mono w-full max-w-[400px]">
          <div>Vehicles: <span className="text-gray-200">{metrics.num_vehicles}</span></div>
          <div>Arrived: <span className="text-gray-200">{metrics.arrived}</span></div>
          <div>Wait: <span className="text-gray-200">{metrics.total_waiting_time.toFixed(1)}s</span></div>
          <div>Avg Speed: <span className="text-gray-200">{metrics.avg_speed.toFixed(1)} m/s</span></div>
        </div>
      )}
    </div>
  );
}
