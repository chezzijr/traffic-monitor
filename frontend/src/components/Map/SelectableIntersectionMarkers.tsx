import { Marker, Popup } from 'react-leaflet';
import L from 'leaflet';
import { useMapStore } from '../../store/mapStore';
import { grayIcon, greenIcon, amberIcon, purpleIcon } from './markerIcons';
import type { Intersection } from '../../types';
import type { ApproachMeta, TlLinkMetadataMap } from '../../services/digitalTwinDeployService';

interface SelectableIntersectionMarkersProps {
  deployedJunctionIds?: string[];
  /** Live SUMO TL state per controlled junction from DT snapshot — same
   *  data the /simulation/view canvas uses. Renders inline bulbs around
   *  the purple marker so the user can verify the simulation is running
   *  without opening the debug view. */
  tlStates?: Record<string, { state: string; phase: number }>;
  /** Per-TL approach metadata from SUMO net topology — 1 entry per
   *  physical incoming road, with compass angle + which state-string
   *  indices belong to it. When present, bulbs render at correct
   *  geographic positions; otherwise we fall back to length-heuristics. */
  tlMetadata?: TlLinkMetadataMap;
  onIntersectionClick?: (intersection: Intersection) => void;
}

// SUMO state char → bulb color (matches CameraModal's DeployStateLights).
const SUMO_CHAR_COLOR: Record<string, string> = {
  G: '#22c55e', g: '#22c55e',
  y: '#eab308', Y: '#eab308',
  r: '#ef4444', R: '#ef4444',
  o: '#9ca3af', u: '#9ca3af',
};

/** Normalize a SUMO state char to a small alphabet so per-link variants
 *  (G vs g for protected/permissive, R vs r) collapse to the same color. */
function normalizeSumoChar(c: string): 'green' | 'yellow' | 'red' | 'off' {
  if (c === 'G' || c === 'g') return 'green';
  if (c === 'y' || c === 'Y') return 'yellow';
  if (c === 'r' || c === 'R') return 'red';
  return 'off';
}

const NORMALIZED_COLOR: Record<string, string> = {
  green: '#22c55e',
  yellow: '#eab308',
  red: '#ef4444',
  off: '#9ca3af',
};

/** Detect intersection arity from SUMO state length. SUMO orders links
 *  by incoming edge then lane, so the state length is always a multiple
 *  of (arity × lanes-per-approach). Picking arity by divisibility gives
 *  a stable count that does NOT flicker during yellow transitions —
 *  unlike run-length encoding, which adds a transient group when one
 *  arm flips to yellow. */
function detectArity(stateLength: number): number {
  if (stateLength <= 0) return 0;
  if (stateLength === 1) return 1;
  // Prefer even arities — most urban intersections are 4-way or 2-way.
  // Odd-length states (e.g., 9 = 5+4 unbalanced lanes) are 2-way.
  if (stateLength >= 4 && stateLength % 4 === 0) return 4;
  // 3-way only when length is a small multiple of 3 (3, 6) AND not a
  // better 2/4 fit. Avoids misclassifying unbalanced 2-way as 3-way.
  if (stateLength === 3 || (stateLength === 6 && stateLength % 4 !== 0)) return 3;
  return 2;
}

/** Majority color for one approach chunk. The previous "any green" rule
 *  hid real transitions — a chunk that straddles two approaches with
 *  1 green and 4 red would always render green, making the middle bulb
 *  look "stuck". Counting actual votes per color reflects the true state. */
function dominantApproachColor(chunk: string): string {
  let g = 0, y = 0, r = 0;
  for (const c of chunk) {
    const k = normalizeSumoChar(c);
    if (k === 'green') g++;
    else if (k === 'yellow') y++;
    else if (k === 'red') r++;
  }
  // Yellow always wins when present (transition is the important signal).
  if (y > 0 && y >= Math.max(g, r)) return 'yellow';
  if (g > r) return 'green';
  if (r > g) return 'red';
  if (g === r && g > 0) return 'yellow'; // tie → conservative yellow
  return 'off';
}

/** Split the SUMO state into exactly `arity` equal chunks → one bulb
 *  per approach. Bulb count is stable across phase transitions. */
function approachesFromState(stateStr: string): string[] {
  if (!stateStr) return [];
  const arity = detectArity(stateStr.length);
  const chunkSize = Math.floor(stateStr.length / arity);
  if (chunkSize === 0) return [];
  const result: string[] = [];
  for (let i = 0; i < arity; i++) {
    const start = i * chunkSize;
    // Last chunk absorbs any remainder so we never lose chars.
    const end = i === arity - 1 ? stateStr.length : start + chunkSize;
    result.push(dominantApproachColor(stateStr.slice(start, end)));
  }
  return result;
}

/** Build a Leaflet divIcon mirroring the /simulation/view canvas:
 *  purple core with "AI" badge, N colored bulbs distributed evenly around
 *  the perimeter (1 per SUMO link). Variable count — 1-way → 1 dot,
 *  2-way → 2, 4-way → 4-16. */
/** Build per-approach bulbs from SUMO metadata (real geography). Each
 *  approach is positioned at its true compass angle; color is the
 *  majority across the approach's controlled links. */
function bulbsFromMetadata(stateStr: string, approaches: ApproachMeta[]): Array<{ color: string; angleDeg: number }> {
  return approaches.map((a) => {
    // Filter out-of-range link indices — a stale metadata cache (e.g.,
    // AI-toggle swapped SUMO program to a shorter fixed-time logic) would
    // otherwise produce all-off bulbs across the board.
    const chunk = a.link_indices
      .filter((i) => i >= 0 && i < stateStr.length)
      .map((i) => stateStr[i])
      .join('');
    return { color: dominantApproachColor(chunk), angleDeg: a.angle_deg };
  });
}

function buildDeployedIcon(stateStr: string, metadata?: { approaches: ApproachMeta[] }): L.DivIcon {
  // Prefer SUMO net-topology metadata when available (correct count + true
  // compass positions); fall back to length heuristic only when missing OR
  // when the cached link indices reference positions past the current
  // state length (happens after an AI-toggle swaps SUMO programs).
  const maxLinkIdx = metadata
    ? metadata.approaches.reduce((m, a) => Math.max(m, ...a.link_indices), -1)
    : -1;
  const metadataInRange = !!metadata && metadata.approaches.length > 0 && maxLinkIdx < stateStr.length;
  let bulbs: Array<{ color: string; angleDeg: number }>;
  if (metadataInRange && metadata) {
    bulbs = bulbsFromMetadata(stateStr, metadata.approaches);
  } else {
    const groups = approachesFromState(stateStr);
    const n = groups.length;
    bulbs = groups.map((g, i) => ({
      color: g,
      angleDeg: ((i / Math.max(n, 1)) * 360) % 360, // start at north (0°), clockwise
    }));
  }
  const n = bulbs.length;

  const containerSize = 40;          // total icon footprint (anchored at center)
  const coreSize = 18;               // purple "AI" core
  const orbitRadius = 13;            // distance from center to bulb centers
  const bulbSize = 7;
  const center = containerSize / 2;

  const bulbsHtml = bulbs.map((b) => {
    const color = NORMALIZED_COLOR[b.color] ?? '#9ca3af';
    // Compass (0=N, 90=E, clockwise) → canvas math: rotate so 0° points up.
    const angle = (b.angleDeg - 90) * (Math.PI / 180);
    const x = center + Math.cos(angle) * orbitRadius - bulbSize / 2;
    const y = center + Math.sin(angle) * orbitRadius - bulbSize / 2;
    return `<span style="position:absolute;left:${x}px;top:${y}px;width:${bulbSize}px;height:${bulbSize}px;border-radius:50%;background:${color};box-shadow:0 0 3px ${color};border:1px solid rgba(0,0,0,0.3)"></span>`;
  }).join('');
  // Silence unused-var warning for the per-link map kept for the modal.
  void SUMO_CHAR_COLOR;
  void n;

  const html = `
    <div style="position:relative;width:${containerSize}px;height:${containerSize}px;pointer-events:auto">
      ${bulbsHtml}
      <div style="position:absolute;left:${center - coreSize / 2}px;top:${center - coreSize / 2}px;width:${coreSize}px;height:${coreSize}px;border-radius:50%;background:#a855f7;border:2px solid white;box-shadow:0 0 6px rgba(168,85,247,0.65);display:flex;align-items:center;justify-content:center;color:white;font-size:8px;font-weight:700;font-family:'Space Grotesk',sans-serif;letter-spacing:0.5px">AI</div>
    </div>
  `;

  return L.divIcon({
    html,
    className: '',
    iconSize: [containerSize, containerSize],
    iconAnchor: [center, center],
  });
}

// Special clickable intersection: Tran Binh Trong x Tran Hung Dao.
const THD_TBT_LAT = 10.755388;
const THD_TBT_LON = 106.681386;
const COORD_TOLERANCE = 0.002;

const isTHDTBTIntersection = (intersection: Intersection): boolean =>
  Math.abs(intersection.lat - THD_TBT_LAT) < COORD_TOLERANCE &&
  Math.abs(intersection.lon - THD_TBT_LON) < COORD_TOLERANCE;

export function SelectableIntersectionMarkers({ deployedJunctionIds = [], tlStates = {}, tlMetadata = {}, onIntersectionClick }: SelectableIntersectionMarkersProps) {
  const intersections = useMapStore((s) => s.intersections);
  const sumoTrafficLights = useMapStore((s) => s.sumoTrafficLights);
  const selectedRegion = useMapStore((s) => s.selectedRegion);
  const selectedJunctionIds = useMapStore((s) => s.selectedJunctionIds);
  const toggleJunctionSelection = useMapStore((s) => s.toggleJunctionSelection);

  // SUMO TLs without OSM matches still get rendered from their boundary-
  // reverse-projected lat/lon — scoped to the user's bbox so tlLogics leaked
  // by netconvert's buffer don't clutter the map.
  const osmMatchedTlIds = new Set(
    intersections.map((i) => i.sumo_tl_id).filter(Boolean) as string[],
  );
  const unmatchedSumoTls = sumoTrafficLights.filter(
    (tl) =>
      tl.lat != null &&
      tl.lon != null &&
      !osmMatchedTlIds.has(tl.id) &&
      (!selectedRegion ||
        (tl.lat >= selectedRegion.south &&
          tl.lat <= selectedRegion.north &&
          tl.lon >= selectedRegion.west &&
          tl.lon <= selectedRegion.east)),
  );

  return (
    <>
      {intersections.map((intersection) => {
        const sumoTlId = intersection.sumo_tl_id;
        const hasTL = intersection.has_traffic_light && sumoTlId;

        if (!hasTL) {
          const isSpecialIntersection = isTHDTBTIntersection(intersection);

          return (
            <Marker
              key={intersection.id}
              position={[intersection.lat, intersection.lon]}
              icon={grayIcon}
              eventHandlers={
                isSpecialIntersection
                  ? {
                      click: () => onIntersectionClick?.(intersection),
                    }
                  : undefined
              }
            />
          );
        }

        const isDeployed = deployedJunctionIds.includes(sumoTlId);
        const isSelected = selectedJunctionIds.includes(sumoTlId);
        const liveState = isDeployed ? tlStates[sumoTlId] : undefined;
        const meta = isDeployed ? tlMetadata[sumoTlId] : undefined;
        const icon = isDeployed
          ? (liveState ? buildDeployedIcon(liveState.state, meta) : purpleIcon)
          : isSelected ? amberIcon : greenIcon;

        return (
          <Marker
            key={intersection.id}
            position={[intersection.lat, intersection.lon]}
            icon={icon}
            eventHandlers={{
              click: () => {
                // Deployed (purple): open live deploy modal, do NOT toggle training.
                // Non-deployed (green/amber): toggle training selection only.
                if (isDeployed) {
                  onIntersectionClick?.(intersection);
                } else {
                  toggleJunctionSelection(sumoTlId);
                }
              },
            }}
          >
            <Popup>
              <div className="text-sm">
                <p className="font-semibold">
                  {intersection.name || `Junction ${sumoTlId}`}
                </p>
                <p className="text-xs text-gray-600">SUMO TL: {sumoTlId}</p>
                <p className="text-xs text-gray-500">
                  {intersection.lat.toFixed(6)}, {intersection.lon.toFixed(6)}
                </p>
                {isSelected && (
                  <p className="text-xs text-amber-600 font-medium mt-1">Selected for training</p>
                )}
                {isDeployed && (
                  <p className="text-xs text-purple-600 font-medium mt-1">AI Model Deployed — click to view</p>
                )}
              </div>
            </Popup>
          </Marker>
        );
      })}
      {unmatchedSumoTls.map((tl) => {
        const isDeployed = deployedJunctionIds.includes(tl.id);
        const isSelected = selectedJunctionIds.includes(tl.id);
        const liveState = isDeployed ? tlStates[tl.id] : undefined;
        const meta = isDeployed ? tlMetadata[tl.id] : undefined;
        const icon = isDeployed
          ? (liveState ? buildDeployedIcon(liveState.state, meta) : purpleIcon)
          : isSelected ? amberIcon : greenIcon;
        return (
          <Marker
            key={`sumo-${tl.id}`}
            position={[tl.lat as number, tl.lon as number]}
            icon={icon}
            eventHandlers={{
              click: () => {
                // No OSM intersection to pass — for deployed unmatched TLs we
                // still synthesize a minimal Intersection for the modal so the
                // user can see live deploy state.
                if (isDeployed) {
                  onIntersectionClick?.({
                    id: tl.id,
                    osm_id: 0,
                    lat: tl.lat as number,
                    lon: tl.lon as number,
                    name: `Junction ${tl.id}`,
                    has_traffic_light: true,
                    sumo_tl_id: tl.id,
                  } as Intersection);
                } else {
                  toggleJunctionSelection(tl.id);
                }
              },
            }}
          >
            <Popup>
              <div className="text-sm">
                <p className="font-semibold">Junction {tl.id}</p>
                <p className="text-xs text-gray-600">SUMO TL: {tl.id}</p>
                <p className="text-xs text-gray-400 italic">No OSM match</p>
                {isSelected && (
                  <p className="text-xs text-amber-600 font-medium mt-1">Selected for training</p>
                )}
              </div>
            </Popup>
          </Marker>
        );
      })}
    </>
  );
}
