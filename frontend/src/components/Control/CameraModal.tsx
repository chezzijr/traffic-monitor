import { useCallback, useEffect, useRef, useState, useMemo } from 'react';
import { X, Loader, Zap } from 'lucide-react';
import toast from 'react-hot-toast';
import { cameraService, trafficLightSimService, waitingCountService, digitalTwinLightService } from '../../services';
import { digitalTwinDeployService } from '../../services/digitalTwinDeployService';
import type { ApproachMeta } from '../../services/digitalTwinDeployService';
import { useModelStore } from '../../store/modelStore';
import type {
    Intersection,
    IntersectionFrames,
    TrafficLightSimState,
    WaitingCountResponse,
} from '../../types';

// Approach-level color map. SUMO state has 1 char per controlled link
// (lane), so a 4-way with 4 lanes per arm emits 16 chars. We compress by
// run-length so the bulb count reflects intersection arity, not lane count.
const APPROACH_COLOR_MODAL: Record<string, string> = {
    green: '#22c55e',
    yellow: '#eab308',
    red: '#ef4444',
    off: '#9ca3af',
};

function normalizeSumoCharModal(c: string): string {
    if (c === 'G' || c === 'g') return 'green';
    if (c === 'y' || c === 'Y') return 'yellow';
    if (c === 'r' || c === 'R') return 'red';
    return 'off';
}

function detectArityModal(len: number): number {
    if (len <= 0) return 0;
    if (len === 1) return 1;
    if (len >= 4 && len % 4 === 0) return 4;
    if (len === 3 || (len === 6 && len % 4 !== 0)) return 3;
    return 2;
}

function dominantApproachColorModal(chunk: string): string {
    let g = 0, y = 0, r = 0;
    for (const c of chunk) {
        const k = normalizeSumoCharModal(c);
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

function compressStateToApproachesModal(stateStr: string): string[] {
    if (!stateStr) return [];
    const arity = detectArityModal(stateStr.length);
    const chunkSize = Math.floor(stateStr.length / arity);
    if (chunkSize === 0) return [];
    const result: string[] = [];
    for (let i = 0; i < arity; i++) {
        const start = i * chunkSize;
        const end = i === arity - 1 ? stateStr.length : start + chunkSize;
        result.push(dominantApproachColorModal(stateStr.slice(start, end)));
    }
    return result;
}

/** Render one bulb per intersection approach. When SUMO net metadata is
 *  available, bulbs are positioned at their actual compass angles and
 *  count matches physical roads (1-way → 1, 2-way → 2, etc.). Without
 *  metadata, falls back to length-heuristic chunking. */
function DeployStateLights({ stateStr, phase, aiAction, step, metadata }: {
    stateStr: string;
    phase: number;
    aiAction: number | number[] | null | undefined;
    step: number;
    metadata?: { approaches: ApproachMeta[] };
}) {
    type Bulb = { color: string; angleDeg: number; label: string };
    let bulbs: Bulb[];
    if (metadata && metadata.approaches.length > 0) {
        bulbs = metadata.approaches.map((a, i) => {
            const chunk = a.link_indices.map((k) => stateStr[k] ?? '').join('');
            return {
                color: dominantApproachColorModal(chunk),
                angleDeg: a.angle_deg,
                label: `Approach ${i + 1} (${Math.round(a.angle_deg)}°)`,
            };
        });
    } else {
        const groups = compressStateToApproachesModal(stateStr);
        bulbs = groups.map((g, i) => ({
            color: g,
            angleDeg: (360 * i) / Math.max(groups.length, 1),
            label: `Approach ${i + 1}`,
        }));
    }
    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div className="flex items-center gap-2 text-xs text-gray-600">
                <span>Phase <span className="font-mono font-semibold text-gray-900">{phase}</span></span>
                <span>•</span>
                <span>Step <span className="font-mono font-semibold text-gray-900">{step}</span></span>
                {aiAction !== null && aiAction !== undefined && (
                    <>
                        <span>•</span>
                        <span>AI action <span className="font-mono font-semibold text-purple-700">{Array.isArray(aiAction) ? aiAction.join(',') : aiAction}</span></span>
                    </>
                )}
            </div>
            {/* Compass-style layout: bulbs positioned at their true SUMO
                approach angles (when metadata available). The center is
                the junction; each bulb sits on a circle at its angle. */}
            <div style={{ position: 'relative', width: 140, height: 140, margin: '8px auto' }}>
                <div style={{
                    position: 'absolute', left: '50%', top: '50%',
                    transform: 'translate(-50%, -50%)',
                    width: 40, height: 40, borderRadius: '50%',
                    border: '2px dashed #d1d5db',
                }} />
                {bulbs.length === 0 ? (
                    <span style={{
                        position: 'absolute', left: '50%', top: '50%',
                        transform: 'translate(-50%, -50%)',
                        fontSize: 11, color: '#9ca3af', fontStyle: 'italic',
                    }}>no signal state yet</span>
                ) : bulbs.map((b, i) => {
                    const rad = (b.angleDeg - 90) * (Math.PI / 180);
                    const radius = 50;
                    const x = 70 + Math.cos(rad) * radius;
                    const y = 70 + Math.sin(rad) * radius;
                    return (
                        <div
                            key={i}
                            title={`${b.label}: ${b.color}`}
                            style={{
                                position: 'absolute',
                                left: x - 14, top: y - 14,
                                width: 28, height: 28, borderRadius: '50%',
                                background: APPROACH_COLOR_MODAL[b.color] ?? '#9ca3af',
                                boxShadow: `0 0 8px ${APPROACH_COLOR_MODAL[b.color] ?? '#9ca3af'}`,
                                border: '2px solid white',
                            }}
                        />
                    );
                })}
                {/* Compass cardinals for orientation reference */}
                {['N', 'E', 'S', 'W'].map((c, i) => {
                    const rad = ((i * 90) - 90) * (Math.PI / 180);
                    const x = 70 + Math.cos(rad) * 65;
                    const y = 70 + Math.sin(rad) * 65;
                    return (
                        <span key={c} style={{
                            position: 'absolute', left: x - 6, top: y - 8,
                            fontSize: 10, color: '#9ca3af', fontWeight: 600,
                        }}>{c}</span>
                    );
                })}
            </div>
            <div className="text-[10px] text-gray-400 font-mono break-all">
                {metadata ? `${bulbs.length} approach${bulbs.length === 1 ? '' : 'es'} (SUMO topology)` : `heuristic split: ${bulbs.length}`}
                {' • '}raw state: {stateStr || '(empty)'}
            </div>
        </div>
    );
}

const formatDurationSince = (date: Date | null): string => {
    if (!date) return 'N/A';

    const diffMs = Date.now() - date.getTime();
    if (diffMs < 0) return '00:00:00';

    const totalSeconds = Math.floor(diffMs / 1000);
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;

    const pad = (n: number) => String(n).padStart(2, '0');
    return `${pad(hours)}:${pad(minutes)}:${pad(seconds)}`;
};

interface CameraModalProps {
    intersection: Intersection | null;
    isOpen: boolean;
    onClose: () => void;
}

/** Check if the intersection is Trần Hưng Đạo × Trần Bình Trọng by coordinates. */
const THD_TBT_LAT = 10.755388;
const THD_TBT_LON = 106.681386;
const COORD_TOLERANCE = 0.002; // ~200m

const isTHDTBTIntersection = (inter: Intersection | null): boolean => {
    if (!inter) return false;
    return (
        Math.abs(inter.lat - THD_TBT_LAT) < COORD_TOLERANCE &&
        Math.abs(inter.lon - THD_TBT_LON) < COORD_TOLERANCE
    );
};

/* ── Horizontal traffic light (3 bulbs in a row) ── */
const COLOUR_HEX: Record<string, string> = {
    red: '#ef4444',
    yellow: '#eab308',
    green: '#22c55e',
};

function DirectionLightRow({ activeColour, remaining, direction }: { activeColour: string; remaining: number; direction: string }) {
    const bulbs = ['red', 'yellow', 'green'] as const;
    return (
        <div style={{
            display: 'flex', alignItems: 'flex-start', justifyContent: 'center',
            gap: 6, marginTop: 6,
        }}>
            {/* Column: capsule + direction label centered underneath */}
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                <div style={{
                    display: 'flex', alignItems: 'center', gap: 4,
                    background: '#1f2937', borderRadius: 10, padding: '4px 8px',
                }}>
                    {bulbs.map((c) => (
                        <div
                            key={c}
                            style={{
                                width: 12, height: 12, borderRadius: '50%',
                                background: activeColour === c ? COLOUR_HEX[c] : '#4b5563',
                                boxShadow: activeColour === c ? `0 0 6px ${COLOUR_HEX[c]}` : 'none',
                                transition: 'all 0.4s ease',
                            }}
                        />
                    ))}
                </div>
                <span style={{ fontSize: 13, color: '#374151', marginTop: 3 }}>
                    {direction}
                </span>
            </div>
            {/* Countdown next to capsule */}
            <span style={{
                fontSize: 12, fontWeight: 600,
                color: COLOUR_HEX[activeColour] ?? '#6b7280',
                marginTop: 2,
            }}>
                {remaining === -1 ? '-' : `${remaining}s`}
            </span>
        </div>
    );
}

const DIRECTIONS = ['north', 'south', 'east', 'west'] as const;

export function CameraModal({ intersection, isOpen, onClose }: CameraModalProps) {
    const [frames, setFrames] = useState<IntersectionFrames | null>(null);
    const [lastUpdatedAt, setLastUpdatedAt] = useState<Date | null>(null);
    const [, setTick] = useState(0);

    // Real data from backend
    const [lightState, setLightState] = useState<TrafficLightSimState | null>(null);
    const [waitingCount, setWaitingCount] = useState<WaitingCountResponse | null>(null);
    const [isWaitingLoading, setIsWaitingLoading] = useState(false);
    const [showAnnotated, setShowAnnotated] = useState(false);
    const lightIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
    const keepaliveIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

    const trafficLight = intersection?.trafficLight;
    const validFrames = frames?.frames?.filter(f => f.image) ?? [];
    const showNumber = validFrames?.length >= 2;
    const hasAnnotated = validFrames.some(f => f.image_annotated);

    // Detect if this is the Trần Hưng Đạo × Trần Bình Trọng intersection
    const useDT = useMemo(() => isTHDTBTIntersection(intersection), [intersection]);

    // ── Deploy mode: pull deployment metadata + live DT toggle state ──
    // When this modal is opened from a purple (deployed) marker, surface the
    // model_id, deploy_id and let the user toggle the AI agent.
    const deployments = useModelStore((s) => s.deployments);
    const matchingDeployment = useMemo(() => {
        if (!intersection?.sumo_tl_id) return null;
        const tlId = intersection.sumo_tl_id;
        return (
            deployments.find((d) => d.tl_id === tlId) ??
            deployments.find((d) => (d.tl_ids ?? []).includes(tlId)) ??
            null
        );
    }, [intersection?.sumo_tl_id, deployments]);
    const isDeployedMode = matchingDeployment !== null;
    const [agentEnabled, setAgentEnabled] = useState(true);
    const [agentToggling, setAgentToggling] = useState(false);

    // Per-TL DT live state for the deploy banner — replaces the hardcoded
    // N/S/E/W simulation-API lookup which doesn't apply to real intersections.
    type DeployTlSnap = {
        state: string;     // SUMO state string, variable length per TL
        phase: number;
        program?: string;
    };
    const [deployTlSnap, setDeployTlSnap] = useState<DeployTlSnap | null>(null);
    const [deployTlMeta, setDeployTlMeta] = useState<{ approaches: ApproachMeta[] } | undefined>(undefined);
    const [deployStep, setDeployStep] = useState<number>(0);
    const [deployAiAction, setDeployAiAction] = useState<number | number[] | null | undefined>(null);
    const [deployHealth, setDeployHealth] = useState<string>('idle');

    useEffect(() => {
        if (!isOpen || !isDeployedMode) return;
        digitalTwinDeployService.getStatus()
            .then((s) => setAgentEnabled(s.agent_enabled ?? true))
            .catch(() => { /* DT may be offline; banner still shows */ });
    }, [isOpen, isDeployedMode]);

    // Poll DT snapshot every second while the deploy modal is open so the
    // per-link bulbs reflect the actual SUMO controlled state, not the
    // four-direction guess from `trafficLightSimService`.
    useEffect(() => {
        if (!isOpen || !isDeployedMode || !intersection?.sumo_tl_id) return;
        const tlId = intersection.sumo_tl_id;
        let cancelled = false;

        const fetchSnap = async () => {
            try {
                const snap = await digitalTwinDeployService.getSnapshot();
                if (cancelled) return;
                setDeployStep(snap.step ?? 0);
                setDeployHealth(
                    (snap as { health?: string }).health ?? 'ok',
                );
                // ai_action — for multi-agent it's an array indexed by the
                // controlled_tl_ids order; for single-agent it's a scalar.
                const action = snap.ai_action;
                if (Array.isArray(action) && Array.isArray(snap.controlled_tl_ids)) {
                    const idx = snap.controlled_tl_ids.indexOf(tlId);
                    setDeployAiAction(idx >= 0 ? action[idx] : null);
                } else {
                    setDeployAiAction(action ?? null);
                }
                // tl_state shape differs between single (flat) and multi (record).
                const ts = snap.tl_state as Record<string, { state: string; phase: number; program?: string }> | { tl_id?: string; state: string; phase: number; program?: string } | undefined;
                if (!ts) {
                    setDeployTlSnap(null);
                    return;
                }
                let perTl: { state: string; phase: number; program?: string } | undefined;
                if ('tl_id' in ts && typeof ts.tl_id === 'string') {
                    perTl = ts.tl_id === tlId ? ts as { state: string; phase: number; program?: string } : undefined;
                } else {
                    perTl = (ts as Record<string, { state: string; phase: number; program?: string }>)[tlId];
                }
                setDeployTlSnap(perTl ? { state: perTl.state, phase: perTl.phase, program: perTl.program } : null);
                const meta = (snap as { tl_link_metadata?: Record<string, { approaches: ApproachMeta[] }> }).tl_link_metadata;
                setDeployTlMeta(meta?.[tlId]);
            } catch {
                /* DT may be transiently offline */
            }
        };

        fetchSnap();
        const id = window.setInterval(fetchSnap, 1000);
        return () => {
            cancelled = true;
            window.clearInterval(id);
        };
    }, [isOpen, isDeployedMode, intersection?.sumo_tl_id]);

    const handleToggleAgent = useCallback(async () => {
        setAgentToggling(true);
        try {
            const result = await digitalTwinDeployService.toggleAgent(!agentEnabled);
            setAgentEnabled(result.agent_enabled);
            toast.success(`AI control ${result.agent_enabled ? 'enabled' : 'disabled'}`);
        } catch {
            toast.error('Failed to toggle AI control');
        } finally {
            setAgentToggling(false);
        }
    }, [agentEnabled]);

    // Combined fetch: load frames + waiting count together, update atomically
    const loadFramesAndCount = useCallback(async () => {
        if (!intersection) return;

        const fallbackLat = useDT ? intersection.lat : undefined;
        const fallbackLon = useDT ? intersection.lon : undefined;
        const lat = trafficLight?.lat ?? fallbackLat;
        const lon = trafficLight?.lon ?? fallbackLon;
        const hasCoords = typeof lat === 'number' && typeof lon === 'number';
        const idCamera = intersection.id || `osm_${intersection.osm_id}`;

        setIsWaitingLoading(true);

        const [framesResult, countResult] = await Promise.allSettled([
            hasCoords
                ? cameraService.getIntersection({ lat, lon })
                : Promise.reject('no coords'),
            waitingCountService.getWaitingCount(idCamera),
        ]);

        // Update both states together so they appear in sync
        if (framesResult.status === 'fulfilled') {
            setFrames(framesResult.value);
            setLastUpdatedAt(new Date());
        } else if (framesResult.reason !== 'no coords') {
            const msg = framesResult.reason instanceof Error ? framesResult.reason.message : 'Cannot load frames';
            toast.error(msg);
        }

        if (countResult.status === 'fulfilled') {
            setWaitingCount(countResult.value);
        } else {
            console.warn('Could not load waiting count:', countResult.reason);
        }

        setIsWaitingLoading(false);
    }, [intersection, trafficLight?.lat, trafficLight?.lon, useDT]);

    // Load data when modal opens
    useEffect(() => {
        if (!isOpen || !intersection) {
            setFrames(null);
            setLastUpdatedAt(null);
            setLightState(null);
            setWaitingCount(null);
            return;
        }

        if (!isOpen || (!trafficLight?.osm_id && !useDT)) {
            console.warn("Intersection OSM ID is missing.");
            return;
        }

        loadFramesAndCount();
    }, [isOpen, intersection, trafficLight?.osm_id, useDT, loadFramesAndCount]);

    // Start / stop the YOLO video stream when the modal opens/closes (THD×TBT only)
    useEffect(() => {
        if (!useDT) return;

        if (isOpen && intersection) {
            // Start stream immediately
            digitalTwinLightService.startStream().catch(() => {});

            // Send keepalive every 30s so server doesn't auto-stop at 60s
            keepaliveIntervalRef.current = setInterval(() => {
                digitalTwinLightService.startStream().catch(() => {});
            }, 30_000);

            return () => {
                if (keepaliveIntervalRef.current) clearInterval(keepaliveIntervalRef.current);
                // Stop stream when modal closes
                digitalTwinLightService.stopStream().catch(() => {});
            };
        } else {
            // Modal closed — stop stream
            if (keepaliveIntervalRef.current) clearInterval(keepaliveIntervalRef.current);
            digitalTwinLightService.stopStream().catch(() => {});
        }
    }, [isOpen, intersection, useDT]);

    // Single polling loop: fetch both frames + waiting count every 3–5 seconds
    useEffect(() => {
        if (!isOpen || !intersection) return;

        let timeoutId: number;

        const scheduleNext = () => {
            const delay = 3000 + Math.random() * 2000;
            timeoutId = window.setTimeout(async () => {
                await loadFramesAndCount();
                scheduleNext();
            }, delay);
        };

        scheduleNext();

        return () => {
            window.clearTimeout(timeoutId);
        };
    }, [isOpen, intersection, loadFramesAndCount]);

    // Poll traffic light state every second.
    // For Trần Hưng Đạo × Trần Bình Trọng, use the digital twin API;
    // for all other intersections, use the simulation API.
    useEffect(() => {
        if (!isOpen || !intersection) {
            setLightState(null);
            return;
        }

        let cancelled = false;
        const intId = intersection.id || `osm_${intersection.osm_id}`;

        const fetchLight = async () => {
            try {
                if (useDT) {
                    try {
                        // Digital twin API → adapt to TrafficLightSimState
                        const dt = await digitalTwinLightService.getLightState();
                        if (!cancelled) {
                            setLightState({
                                intersection_id: intId,
                                directions: {
                                    north: { state: dt.north.state, remaining: dt.north.duration },
                                    south: { state: dt.south.state, remaining: dt.south.duration },
                                    east:  { state: dt.east.state,  remaining: dt.east.duration },
                                    west:  { state: dt.west.state,  remaining: dt.west.duration },
                                },
                                cycle_duration: -1,
                            });
                        }
                    } catch {
                        // Fallback when digital twin service is down.
                        const data = await trafficLightSimService.getState(intId);
                        if (!cancelled) setLightState(data);
                    }
                } else {
                    const data = await trafficLightSimService.getState(intId);
                    if (!cancelled) setLightState(data);
                }
            } catch {
                // silently ignore – the light overlay is non-critical
            }
        };

        fetchLight();
        lightIntervalRef.current = setInterval(fetchLight, 1000);

        return () => {
            cancelled = true;
            if (lightIntervalRef.current) clearInterval(lightIntervalRef.current);
        };
    }, [isOpen, intersection, useDT]);

    // Tick every second to update "Last update" display
    useEffect(() => {
        const id = window.setInterval(() => {
            setTick(tick => tick + 1);
        }, 1000);

        return () => window.clearInterval(id);
    }, []);

    // Handle ESC key to close modal
    useEffect(() => {
        if (!isOpen) return;

        const handleEsc = (e: KeyboardEvent) => {
            if (e.key === 'Escape') {
                onClose();
            }
        };

        document.addEventListener('keydown', handleEsc);
        return () => document.removeEventListener('keydown', handleEsc);
    }, [isOpen, onClose]);

    if (!isOpen || !intersection) {
        return null;
    }

    // Handle click on backdrop to close modal
    const handleBackdropClick = (e: React.MouseEvent<HTMLDivElement>) => {
        if (e.target === e.currentTarget) {
            onClose();
        }
    };

    /** Look up the light colour for a given direction name. */
    const getLightForDirection = (direction: string) => {
        if (!lightState) return null;
        const key = direction.toLowerCase();
        return lightState.directions[key] ?? null;
    };

    return (
        <div
            className="fixed inset-0 bg-gray-800/50 flex items-center justify-center z-[9999]"
            onClick={handleBackdropClick}
        >
            <div
                className="bg-white rounded-lg shadow-xl max-w-5xl w-full mx-4 max-h-[90vh] overflow-y-auto"
                onClick={(e) => e.stopPropagation()}
            >
                {/* Header */}
                <div className="flex items-center justify-between p-4 border-b sticky top-0 bg-white z-10 rounded-t-lg">
                    <div>
                        <h2>
                            {frames?.roads && frames.roads.length >= 2
                                ? `${frames.roads[0]} × ${frames.roads[1]}`
                                : `OSM Traffic Light ${trafficLight?.osm_id}`}
                        </h2>
                        <p className="text-sm text-gray-500">
                            Camera Feed
                            {lastUpdatedAt && (
                                <span className="ml-2 text-xs text-gray-400">
                                    Last update: {formatDurationSince(lastUpdatedAt)}
                                </span>
                            )}
                        </p>
                    </div>
                    <button
                        onClick={onClose}
                        className="p-1 hover:bg-gray-100 rounded transition-colors"
                    >
                        <X size={24} />
                    </button>
                </div>

                {/* Deploy-mode banner — visible only when this junction has an
                    active AI deploy (purple marker). Shows model + deploy_id
                    + AI on/off toggle + per-link SUMO state derived from the
                    DT snapshot (variable length — 1 bulb per controlled link,
                    so 1-way roads show 1, 2-way show 2, 4-way show 4+). */}
                {isDeployedMode && matchingDeployment && (
                    <div className="mx-4 mt-4 rounded-lg border border-purple-200 bg-purple-50 p-3 space-y-3">
                        <div className="flex items-center justify-between gap-3">
                            <div className="flex items-start gap-2 min-w-0">
                                <Zap size={16} className="text-purple-600 flex-shrink-0 mt-0.5" />
                                <div className="min-w-0">
                                    <p className="text-xs font-semibold text-purple-900">
                                        AI Model Deployed
                                        {matchingDeployment.is_multi_agent && ' (multi-agent)'}
                                        {deployHealth === 'error' && <span className="ml-2 text-red-600">⚠ {deployHealth}</span>}
                                    </p>
                                    <p className="text-[11px] font-mono text-purple-700 truncate">
                                        {matchingDeployment.model_id}
                                    </p>
                                    <p className="text-[10px] text-purple-600 mt-0.5">
                                        deploy_id: {matchingDeployment.deploy_id?.slice(0, 12) ?? 'n/a'}
                                        {' • '}
                                        network: {matchingDeployment.network_id?.slice(0, 12)}
                                    </p>
                                </div>
                            </div>
                            <button
                                onClick={handleToggleAgent}
                                disabled={agentToggling}
                                className={`flex items-center gap-1 text-xs px-3 py-1.5 rounded transition-colors disabled:opacity-50 ${
                                    agentEnabled
                                        ? 'bg-green-600 text-white hover:bg-green-700'
                                        : 'bg-gray-300 text-gray-700 hover:bg-gray-400'
                                }`}
                                title={agentEnabled ? 'AI on — click to disable' : 'AI off — click to enable'}
                            >
                                <Zap size={12} />
                                {agentEnabled ? 'AI On' : 'AI Off'}
                            </button>
                        </div>

                        {/* Per-link bulbs from DT snapshot — replaces the
                            hardcoded N/S/E/W simulation-API render. */}
                        <div className="rounded-md bg-white border border-purple-100 p-3">
                            {deployTlSnap ? (
                                <DeployStateLights
                                    stateStr={deployTlSnap.state}
                                    phase={deployTlSnap.phase}
                                    aiAction={deployAiAction}
                                    step={deployStep}
                                    metadata={deployTlMeta}
                                />
                            ) : (
                                <p className="text-xs text-gray-500 italic">
                                    Waiting for DT snapshot… (step {deployStep})
                                </p>
                            )}
                        </div>
                    </div>
                )}

                {/* Main content: Camera feed (left) + Traffic light (right) */}
                <div className="flex flex-col md:flex-row gap-4 p-4">
                    {/* Left: Camera feed */}
                    <div className="flex-1 min-w-0">
                        {/* Toggle: original vs annotated */}
                        {hasAnnotated && (
                            <label className="flex items-center gap-2 mb-2 cursor-pointer select-none text-sm text-gray-600">
                                <input
                                    type="checkbox"
                                    checked={showAnnotated}
                                    onChange={(e) => setShowAnnotated(e.target.checked)}
                                    className="w-4 h-4 accent-blue-600 rounded"
                                />
                                Hiển thị bounding box
                            </label>
                        )}

                        {frames && validFrames.length > 0 ? (
                            <div className={`grid gap-4 ${validFrames.length === 1 ? "grid-cols-1" : "grid-cols-2"}`}>
                                {validFrames.map((f, index) => {
                                    const directionName = DIRECTIONS[index] ?? `cam_${index}`;
                                    const dirLight = getLightForDirection(directionName);
                                    const imgSrc = showAnnotated && f.image_annotated
                                        ? f.image_annotated
                                        : f.image;
                                    return (
                                        <div key={f.number ?? index}>
                                            <img
                                                src={`data:image/jpeg;base64,${imgSrc}`}
                                                className="w-full rounded"
                                                alt={`Camera feed ${directionName}`}
                                            />
                                            {dirLight ? (
                                                <DirectionLightRow
                                                    activeColour={dirLight.state}
                                                    remaining={dirLight.remaining}
                                                    direction={directionName}
                                                />
                                            ) : (
                                                <p className="text-center text-sm text-gray-600 mt-1">
                                                    {showNumber ? `Camera ${index + 1}` : 'Camera'}
                                                </p>
                                            )}
                                        </div>
                                    );
                                })}
                            </div>
                        ) : (
                            <div className="flex items-center justify-center py-16 bg-gray-50 rounded-lg">
                                <p className="text-sm text-gray-500 italic">
                                    {frames ? 'No camera' : 'Loading camera feed...'}
                                </p>
                            </div>
                        )}
                    </div>

                    {/* Right: Traffic light diagram + direction cards.
                        Hidden in deploy mode — the DT snapshot bulbs in the
                        banner above are the authoritative source there. */}
                    {lightState && !isDeployedMode && (
                        <div className="md:w-[280px] flex-shrink-0 space-y-3">
                            <h3 className="font-semibold text-base">Traffic Light Status</h3>

                            {/* 4-direction diagram */}
                            <div className="relative mx-auto w-40 h-40 bg-gray-100 rounded-full flex items-center justify-center">
                                <div className="w-4 h-4 bg-green-500 rounded-full border-2 border-white shadow-md" />
                                {DIRECTIONS.map((dir) => {
                                    const dirLight = lightState.directions[dir];
                                    if (!dirLight) return null;

                                    const baseClass =
                                        dir === 'north'
                                            ? 'top-0 left-1/2 -translate-x-1/2'
                                            : dir === 'south'
                                                ? 'bottom-0 left-1/2 -translate-x-1/2'
                                                : dir === 'east'
                                                    ? 'right-0 top-1/2 -translate-y-1/2'
                                                    : 'left-0 top-1/2 -translate-y-1/2';

                                    const isRed = dirLight.state === 'red';
                                    const isYellow = dirLight.state === 'yellow';
                                    const isGreen = dirLight.state === 'green';

                                    return (
                                        <div
                                            key={dir}
                                            className={`absolute ${baseClass} flex flex-col items-center gap-1`}
                                        >
                                            <div className="w-6 h-10 rounded-md bg-gray-800 flex flex-col justify-between p-0.5">
                                                <span
                                                    className={`w-3 h-3 rounded-full mx-auto ${isRed ? 'bg-red-500' : 'bg-red-500 opacity-30'}`}
                                                />
                                                <span
                                                    className={`w-3 h-3 rounded-full mx-auto ${isYellow ? 'bg-yellow-400' : 'bg-yellow-400 opacity-30'}`}
                                                />
                                                <span
                                                    className={`w-3 h-3 rounded-full mx-auto ${isGreen ? 'bg-green-500' : 'bg-green-500 opacity-30'}`}
                                                />
                                            </div>
                                            <span className="text-[10px] text-gray-600">
                                                {dirLight.remaining === -1 ? '-' : `${Math.round(dirLight.remaining)}s`}
                                            </span>
                                        </div>
                                    );
                                })}
                            </div>

                            {/* Per-direction detail cards — compass layout */}
                            <div className="text-sm text-gray-700 space-y-2">
                                {/* North — top center */}
                                {(() => { const d = lightState.directions['north']; const w = waitingCount?.north ?? null; return d ? (
                                    <div className="mx-auto w-[120px] border rounded px-3 py-1.5 text-center">
                                        <div className="font-medium">North</div>
                                        <div>Đèn: <span className={d.state === 'green' ? 'text-green-600 font-semibold' : d.state === 'yellow' ? 'text-yellow-500 font-semibold' : 'text-red-600 font-semibold'}>{d.state.toUpperCase()}</span></div>
                                        <div>Còn lại: {d.remaining === -1 ? '-' : `${Math.max(0, Math.round(d.remaining))}s`}</div>
                                        <div>Số xe chờ: {w !== null ? w : '—'}</div>
                                    </div>
                                ) : null; })()}

                                {/* West + East — middle row */}
                                <div className="flex justify-between gap-2">
                                    {(() => { const d = lightState.directions['west']; const w = waitingCount?.west ?? null; return d ? (
                                        <div className="w-[120px] border rounded px-3 py-1.5 text-center">
                                            <div className="font-medium">West</div>
                                            <div>Đèn: <span className={d.state === 'green' ? 'text-green-600 font-semibold' : d.state === 'yellow' ? 'text-yellow-500 font-semibold' : 'text-red-600 font-semibold'}>{d.state.toUpperCase()}</span></div>
                                            <div>Còn lại: {d.remaining === -1 ? '-' : `${Math.max(0, Math.round(d.remaining))}s`}</div>
                                            <div>Số xe chờ: {w !== null ? w : '—'}</div>
                                        </div>
                                    ) : null; })()}
                                    {(() => { const d = lightState.directions['east']; const w = waitingCount?.east ?? null; return d ? (
                                        <div className="w-[120px] border rounded px-3 py-1.5 text-center">
                                            <div className="font-medium">East</div>
                                            <div>Đèn: <span className={d.state === 'green' ? 'text-green-600 font-semibold' : d.state === 'yellow' ? 'text-yellow-500 font-semibold' : 'text-red-600 font-semibold'}>{d.state.toUpperCase()}</span></div>
                                            <div>Còn lại: {d.remaining === -1 ? '-' : `${Math.max(0, Math.round(d.remaining))}s`}</div>
                                            <div>Số xe chờ: {w !== null ? w : '—'}</div>
                                        </div>
                                    ) : null; })()}
                                </div>

                                {/* South — bottom center */}
                                {(() => { const d = lightState.directions['south']; const w = waitingCount?.south ?? null; return d ? (
                                    <div className="mx-auto w-[120px] border rounded px-3 py-1.5 text-center">
                                        <div className="font-medium">South</div>
                                        <div>Đèn: <span className={d.state === 'green' ? 'text-green-600 font-semibold' : d.state === 'yellow' ? 'text-yellow-500 font-semibold' : 'text-red-600 font-semibold'}>{d.state.toUpperCase()}</span></div>
                                        <div>Còn lại: {d.remaining === -1 ? '-' : `${Math.max(0, Math.round(d.remaining))}s`}</div>
                                        <div>Số xe chờ: {w !== null ? w : '—'}</div>
                                    </div>
                                ) : null; })()}
                            </div>
                        </div>
                    )}
                </div>

                {/* Bottom sections */}
                <div className="px-6 pb-6 space-y-6">
                    {/* Waiting Count Section (shown only without traffic light state) */}
                    {!lightState && waitingCount && (
                        <div className="space-y-3 border-t pt-6">
                            <h3 className="font-semibold mb-2 text-base">Waiting Vehicle Count</h3>
                            {/* Compass layout */}
                            <div className="text-sm text-gray-700 space-y-2">
                                {/* North — top center */}
                                <div className="mx-auto w-fit border rounded px-4 py-2 text-center">
                                    <span className="font-medium">North</span>
                                    <span className="ml-2 text-lg font-bold text-blue-600">{waitingCount.north}</span>
                                </div>
                                {/* West + East — middle row */}
                                <div className="flex justify-between gap-2">
                                    <div className="border rounded px-4 py-2 text-center flex-1">
                                        <span className="font-medium">West</span>
                                        <span className="ml-2 text-lg font-bold text-blue-600">{waitingCount.west}</span>
                                    </div>
                                    <div className="border rounded px-4 py-2 text-center flex-1">
                                        <span className="font-medium">East</span>
                                        <span className="ml-2 text-lg font-bold text-blue-600">{waitingCount.east}</span>
                                    </div>
                                </div>
                                {/* South — bottom center */}
                                <div className="mx-auto w-fit border rounded px-4 py-2 text-center">
                                    <span className="font-medium">South</span>
                                    <span className="ml-2 text-lg font-bold text-blue-600">{waitingCount.south}</span>
                                </div>
                            </div>
                            <div className="text-center text-sm font-semibold text-gray-600 mt-2">
                                Total waiting: <span className="text-blue-600 text-lg">{waitingCount.total}</span>
                            </div>
                        </div>
                    )}

                    {/* Waiting count loading indicator */}
                    {isWaitingLoading && !waitingCount && (
                        <div className="flex items-center gap-2 text-sm text-gray-500 border-t pt-4">
                            <Loader className="animate-spin" size={16} />
                            Loading waiting vehicle count...
                        </div>
                    )}

                    {/* Intersection Info */}
                    <div className="space-y-2 border-t pt-6">
                        <h3 className="font-semibold mb-2 text-base">Intersection Details</h3>
                        <div className="grid grid-cols-2 gap-2 text-sm text-gray-600">
                            <div>
                                Thông tin:
                                {intersection.has_traffic_light ? (
                                    <span className="text-green-600 font-medium"> Có đèn giao thông</span>
                                ) : (
                                    <span className="text-red-600 font-medium"> Không có đèn giao thông</span>
                                )}
                            </div>
                            <div className="col-span-2">
                                Coordinates: {intersection.lat.toFixed(6)}, {intersection.lon.toFixed(6)}
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}