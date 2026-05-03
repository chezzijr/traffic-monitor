import { useCallback, useEffect, useRef, useState, useMemo } from 'react';
import { X, Loader } from 'lucide-react';
import toast from 'react-hot-toast';
import { cameraService, trafficLightSimService, waitingCountService, digitalTwinLightService } from '../../services';
import type {
    Intersection,
    IntersectionFrames,
    TrafficLightSimState,
    WaitingCountResponse,
} from '../../types';

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

                    {/* Right: Traffic light diagram + direction cards */}
                    {lightState && (
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