import { useCallback, useEffect, useState } from 'react';
import { X, Loader } from 'lucide-react';
import toast from 'react-hot-toast';
import { cameraService } from '../../services';
import type {
    Intersection,
    IntersectionFrames,
    MockDirectionSnapshot,
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
                {remaining}s
            </span>
        </div>
    );
}

export function CameraModal({ intersection, isOpen, onClose }: CameraModalProps) {
    const [frames, setFrames] = useState<IntersectionFrames | null>(null);
    const [isLoading, setIsLoading] = useState(false);
    const [lastUpdatedAt, setLastUpdatedAt] = useState<Date | null>(null);
    const [, setTick] = useState(0);
    const [mockDirections, setMockDirections] = useState<MockDirectionSnapshot[]>([]);
    const trafficLight = intersection?.trafficLight;
    const validFrames = frames?.frames?.filter(f => f.image) ?? [];
    const showNumber = validFrames?.length >= 2;

    const loadFrames = useCallback(async () => {
        if (!trafficLight?.lat || !trafficLight?.lon) return;

        setIsLoading(true);

        try {
            const data = await cameraService.getIntersection({
                lat: trafficLight.lat,
                lon: trafficLight.lon
            });
            setFrames(data);
            setLastUpdatedAt(new Date());
        } catch (err) {
            const msg = err instanceof Error ? err.message : 'Cannot load frames';
            toast.error(msg);
        } finally {
            setIsLoading(false);
        }
    }, [trafficLight?.lat, trafficLight?.lon]);


    // Load camera data when modal opens
    useEffect(() => {
        if (!isOpen || !intersection) {
            setFrames(null);
            setLastUpdatedAt(null);
            setMockDirections([]);
            return;
        }

        if (!isOpen || !trafficLight?.osm_id) {
            console.warn("Intersection OSM ID is missing.");
            return;
        }

        loadFrames();
    }, [isOpen, intersection, trafficLight?.osm_id, loadFrames]);

    // Polling for new frames every 8–12 seconds
    useEffect(() => {
        if (!isOpen || !trafficLight?.osm_id) return;

        let timeoutId: number;

        const scheduleNext = () => {
            const delay = 8000 + Math.random() * 4000;
            timeoutId = window.setTimeout(async () => {
                await loadFrames();
                scheduleNext();
            }, delay);
        };

        scheduleNext();

        return () => {
            window.clearTimeout(timeoutId);
        };
    }, [isOpen, trafficLight?.osm_id, loadFrames]);

    // Generate mock traffic light snapshot data when modal opens
    useEffect(() => {
        if (!isOpen || !intersection) {
            setMockDirections([]);
            return;
        }

        const roadNames =
            frames?.roads && frames.roads.length >= 2
                ? frames.roads
                : ['Đường A', 'Đường B', 'Đường C', 'Đường D'];

        const now = Date.now();
        const baseRemaining = (now / 1000) % 30;

        const data: MockDirectionSnapshot[] = [
            {
                id: 'north',
                roadName: roadNames[0],
                color: 'red',
                remaining: 30 - baseRemaining,
                queue: 5,
            },
            {
                id: 'south',
                roadName: roadNames[0],
                color: 'green',
                remaining: 10,
                queue: 2,
            },
            {
                id: 'east',
                roadName: roadNames[1] ?? 'Đường B',
                color: 'red',
                remaining: 15,
                queue: 7,
            },
            {
                id: 'west',
                roadName: roadNames[1] ?? 'Đường B',
                color: 'red',
                remaining: 15,
                queue: 10,
            },
        ];

        setMockDirections(data);
    }, [isOpen, intersection, frames]);

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

    return (
        <div
            className="fixed inset-0 bg-gray-800/50 flex items-center justify-center z-[9999]"
            onClick={handleBackdropClick}
        >
            <div
                className="bg-white rounded-lg shadow-xl max-w-2xl w-full mx-4 max-h-[90vh] overflow-y-auto"
                onClick={(e) => e.stopPropagation()}
            >
                {/* Header */}
                <div className="flex items-center justify-between p-4 border-b sticky top-0 bg-white">
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

                {/* Content */}
                {frames && (
                    validFrames.length > 0 ? (
                        <div
                            className={`grid gap-4 mt-4 ${validFrames.length === 1 ? "grid-cols-1" : "grid-cols-2"
                                }`}
                        >
                            {validFrames.map((f, index) => (
                                <div key={f.number}>
                                    <img
                                        src={`data:image/jpeg;base64,${f.image}`}
                                        className="w-full rounded"
                                    />
                                    <p className="text-center text-sm text-gray-600 mt-1">
                                        {showNumber ? `Camera ${index + 1}` : "Camera"}
                                    </p>
                                </div>
                            ))}
                        </div>
                    ) : (
                        // Không có ảnh camera
                        <div className="mt-4 flex items-center justify-center py-8">
                            <p className="text-sm text-gray-500 italic">No camera</p>
                        </div>
                    )
                )}

                <div className="p-6 space-y-6">
                    {isLoading ? (
                        <div className="flex justify-center items-center py-12">
                            <Loader className="animate-spin" size={32} />
                        </div>
                    ) : (
                        <>
                            {/* Mock traffic light snapshot (frontend-only) */}
                            {mockDirections.length > 0 && (
                                <div className="space-y-3 border-t pt-6 text-sm">
                                    <h3 className="font-semibold mb-2">Traffic Light Snapshot (demo)</h3>

                                    {/* Simple 4-direction diagram around intersection */}
                                    <div className="relative mx-auto my-4 w-40 h-40 bg-gray-100 rounded-full flex items-center justify-center">
                                        <div className="w-4 h-4 bg-green-500 rounded-full border-2 border-white shadow-md" />
                                        {mockDirections.map((dir) => {
                                            const baseClass =
                                                dir.id === 'north'
                                                    ? 'top-0 left-1/2 -translate-x-1/2'
                                                    : dir.id === 'south'
                                                        ? 'bottom-0 left-1/2 -translate-x-1/2'
                                                        : dir.id === 'east'
                                                            ? 'right-0 top-1/2 -translate-y-1/2'
                                                            : 'left-0 top-1/2 -translate-y-1/2';

                                            const isRed = dir.color === 'red';
                                            const isYellow = dir.color === 'yellow';
                                            const isGreen = dir.color === 'green';

                                            return (
                                                <div
                                                    key={dir.id}
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
                                                        {dir.queue} xe
                                                    </span>
                                                </div>
                                            );
                                        })}
                                    </div>

                                    {/* Detailed per-direction info */}
                                    <div className="grid grid-cols-2 gap-3 text-xs text-gray-700">
                                        {mockDirections.map((dir) => (
                                            <div
                                                key={dir.id}
                                                className="border rounded px-2 py-1 flex flex-col gap-0.5"
                                            >
                                                <div className="font-medium truncate">
                                                    {dir.roadName}
                                                </div>
                                                <div>
                                                    Đèn:{' '}
                                                    <span
                                                        className={
                                                            dir.color === 'green'
                                                                ? 'text-green-600 font-semibold'
                                                                : dir.color === 'yellow'
                                                                    ? 'text-yellow-500 font-semibold'
                                                                    : 'text-red-600 font-semibold'
                                                        }
                                                    >
                                                        {dir.color.toUpperCase()}
                                                    </span>
                                                </div>
                                                <div>
                                                    Còn lại:{' '}
                                                    {Math.max(0, Math.round(dir.remaining))}
                                                    s
                                                </div>
                                                <div>Số xe chờ: {dir.queue}</div>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            )}

                            {/* Intersection Info */}
                            <div className="space-y-2 border-t pt-6 text-sm">
                                <h3 className="font-semibold mb-2">Intersection Details</h3>
                                <div className="grid grid-cols-2 gap-2 text-gray-600">
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


                        </>
                    )}
                </div>
            </div>
        </div>
    );
}