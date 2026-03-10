import { useEffect, useState, useRef } from 'react';
import { trafficLightSimService } from '../../services';
import type { TrafficLightSimState } from '../../types';

interface TrafficLightPanelProps {
  intersectionId: string;
}

const COLOUR_MAP: Record<string, string> = {
  green: '#22c55e',
  yellow: '#eab308',
  red: '#ef4444',
};

const LABEL_MAP: Record<string, string> = {
  green: 'Green',
  yellow: 'Yellow',
  red: 'Red',
};

const BG_MAP: Record<string, string> = {
  green: 'rgba(34,197,94,0.10)',
  yellow: 'rgba(234,179,8,0.10)',
  red: 'rgba(239,68,68,0.10)',
};

/** A single traffic-light bulb (circle). */
function Bulb({ colour, active }: { colour: string; active: boolean }) {
  return (
    <div
      style={{
        width: 18,
        height: 18,
        borderRadius: '50%',
        background: active ? COLOUR_MAP[colour] : '#d1d5db',
        boxShadow: active ? `0 0 8px ${COLOUR_MAP[colour]}` : 'none',
        transition: 'all 0.4s ease',
      }}
    />
  );
}

/** Visual traffic light (3 bulbs stacked vertically). */
function LightColumn({ activeColour }: { activeColour: string }) {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: 4,
        background: '#1f2937',
        padding: '6px 5px',
        borderRadius: 8,
      }}
    >
      <Bulb colour="red" active={activeColour === 'red'} />
      <Bulb colour="yellow" active={activeColour === 'yellow'} />
      <Bulb colour="green" active={activeColour === 'green'} />
    </div>
  );
}

/** One row for a direction group (e.g. "North / South"). */
function DirectionRow({
  label,
  colour,
  remaining,
}: {
  label: string;
  colour: string;
  remaining: number;
}) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        padding: '8px 12px',
        borderRadius: 8,
        background: BG_MAP[colour] ?? 'transparent',
        transition: 'background 0.4s ease',
      }}
    >
      <LightColumn activeColour={colour} />
      <div style={{ flex: 1 }}>
        <div style={{ fontWeight: 600, fontSize: 13, color: '#111827' }}>
          {label}
        </div>
        <div style={{ fontSize: 12, color: '#6b7280', marginTop: 2 }}>
          {LABEL_MAP[colour] ?? colour} — <strong>{remaining}s</strong> remaining
        </div>
      </div>
    </div>
  );
}

export function TrafficLightPanel({ intersectionId }: TrafficLightPanelProps) {
  const [state, setState] = useState<TrafficLightSimState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    let cancelled = false;

    const fetchState = async () => {
      try {
        const data = await trafficLightSimService.getState(intersectionId);
        if (!cancelled) {
          setState(data);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load');
        }
      }
    };

    // Fetch immediately, then poll every second.
    fetchState();
    intervalRef.current = setInterval(fetchState, 1000);

    return () => {
      cancelled = true;
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [intersectionId]);

  if (error) {
    return (
      <div style={{ color: '#ef4444', fontSize: 13, padding: 8 }}>
        ⚠ {error}
      </div>
    );
  }

  if (!state) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: 8, fontSize: 13, color: '#6b7280' }}>
        <div
          style={{
            width: 16,
            height: 16,
            border: '2px solid #3b82f6',
            borderTopColor: 'transparent',
            borderRadius: '50%',
            animation: 'spin 0.8s linear infinite',
          }}
        />
        Loading traffic lights…
      </div>
    );
  }

  const ns = state.directions['north'];
  const we = state.directions['east'];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <h3
        style={{
          fontSize: 14,
          fontWeight: 600,
          margin: 0,
          display: 'flex',
          alignItems: 'center',
          gap: 6,
        }}
      >
        <span style={{ fontSize: 16 }}>🚦</span> Traffic Light Status
      </h3>

      {ns && (
        <DirectionRow
          label="North / South"
          colour={ns.state}
          remaining={ns.remaining}
        />
      )}
      {we && (
        <DirectionRow
          label="West / East"
          colour={we.state}
          remaining={we.remaining}
        />
      )}

      <div style={{ fontSize: 11, color: '#9ca3af', textAlign: 'right' }}>
        Cycle: {state.cycle_duration}s
      </div>
    </div>
  );
}
