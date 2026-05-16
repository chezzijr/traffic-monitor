import L from 'leaflet';
import type { ApproachMeta } from '../../services/digitalTwinDeployService';

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

/** Build a Leaflet divIcon mirroring the /simulation/view canvas:
 *  purple core with "AI" badge, N colored bulbs distributed around the
 *  perimeter (1 per approach). When `isSelected`, an amber ring marks a
 *  deployed junction that is also selected for training. */
export function buildDeployedIcon(stateStr: string, metadata?: { approaches: ApproachMeta[] }, isSelected = false): L.DivIcon {
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

  // Amber ring when this deployed junction is also selected for training —
  // marks the deploy/training overlap (both states show in the popup too).
  const ringHtml = isSelected
    ? `<div style="position:absolute;left:${center - coreSize / 2 - 5}px;top:${center - coreSize / 2 - 5}px;width:${coreSize + 10}px;height:${coreSize + 10}px;border-radius:50%;border:2px solid #f59e0b;box-shadow:0 0 5px #f59e0b"></div>`
    : '';

  const html = `
    <div style="position:relative;width:${containerSize}px;height:${containerSize}px;pointer-events:auto">
      ${bulbsHtml}
      ${ringHtml}
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
