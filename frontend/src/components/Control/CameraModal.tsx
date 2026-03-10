import { useCallback, useEffect, useState } from 'react';
import { X, Loader } from 'lucide-react';
import toast from 'react-hot-toast';
import { cameraService } from '../../services';
import type { Intersection, IntersectionFrames } from '../../types';

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

export function CameraModal({ intersection, isOpen, onClose }: CameraModalProps) {
    const [frames, setFrames] = useState<IntersectionFrames | null>(null);
    const [isLoading, setIsLoading] = useState(false);
    const [lastUpdatedAt, setLastUpdatedAt] = useState<Date | null>(null);
    const [, setTick] = useState(0);
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

                            {/* Intersection Info */}
                            <div className="space-y-2 border-t pt-6 text-sm">
                                <h3 className="font-semibold mb-2">Intersection Details</h3>
                                <div className="grid grid-cols-2 gap-2 text-gray-600">
                                    <div>Roads: {intersection.num_roads}</div>
                                    <div>
                                        {intersection.has_traffic_light ? (
                                            <span className="text-green-600 font-medium">Has Traffic Light</span>
                                        ) : (
                                            'No Traffic Light'
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