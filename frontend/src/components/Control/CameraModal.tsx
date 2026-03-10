import { useEffect, useState } from 'react';
import { X, Loader, Camera, TrafficCone } from 'lucide-react';
import toast from 'react-hot-toast';
import { cameraService } from '../../services';
import { TrafficLightPanel } from './TrafficLightPanel';
import type { Intersection, IntersectionFrames } from '../../types';

type TabKey = 'camera' | 'traffic_light';

interface CameraModalProps {
    intersection: Intersection | null;
    isOpen: boolean;
    onClose: () => void;
}

export function CameraModal({ intersection, isOpen, onClose }: CameraModalProps) {
    const [frames, setFrames] = useState<IntersectionFrames | null>(null);
    const [isLoading, setIsLoading] = useState(false);
    const [activeTab, setActiveTab] = useState<TabKey>('camera');
    const trafficLight = intersection?.trafficLight;

    // Reset tab when modal reopens
    useEffect(() => {
        if (isOpen) setActiveTab('camera');
    }, [isOpen, intersection]);

    // Load camera data when modal opens
    useEffect(() => {
        if (!isOpen || !intersection) {
            setFrames(null);
            return;
        }

        if (!isOpen || !trafficLight?.osm_id) {
            console.warn("Intersection OSM ID is missing.");
            return;
        }

        const load = async () => {
            setIsLoading(true);

            try {
                const data = await cameraService.getIntersection({ lat: trafficLight.lat, lon: trafficLight.lon });
                setFrames(data);
            } catch (err) {
                const msg = err instanceof Error ? err.message : "Cannot load frames";
                toast.error(msg);
            } finally {
                setIsLoading(false);
            }
        };

        load();
    }, [isOpen, intersection]);


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

    const tabs: { key: TabKey; label: string; icon: React.ReactNode }[] = [
        { key: 'camera', label: 'Camera', icon: <Camera size={16} /> },
        { key: 'traffic_light', label: 'Traffic Light', icon: <TrafficCone size={16} /> },
    ];

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
                <div className="sticky top-0 bg-white z-10 rounded-t-lg">
                    <div className="flex items-center justify-between p-4 pb-0">
                        <div>
                            <h2>
                                {frames?.roads && frames.roads.length >= 2
                                    ? `${frames.roads[0]} × ${frames.roads[1]}`
                                    : `OSM Traffic Light ${trafficLight?.osm_id}`}
                            </h2>
                        </div>
                        <button
                            onClick={onClose}
                            className="p-1 hover:bg-gray-100 rounded transition-colors"
                        >
                            <X size={24} />
                        </button>
                    </div>

                    {/* Tabs */}
                    <div className="flex border-b mt-2">
                        {tabs.map((tab) => (
                            <button
                                key={tab.key}
                                onClick={() => setActiveTab(tab.key)}
                                className={`flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium transition-colors relative
                                    ${activeTab === tab.key
                                        ? 'text-blue-600'
                                        : 'text-gray-500 hover:text-gray-700'
                                    }`}
                            >
                                {tab.icon}
                                {tab.label}
                                {activeTab === tab.key && (
                                    <span className="absolute bottom-0 left-0 right-0 h-0.5 bg-blue-600 rounded-t" />
                                )}
                            </button>
                        ))}
                    </div>
                </div>

                {/* Tab Content */}
                <div className="p-6 space-y-6">
                    {activeTab === 'camera' && (
                        <>
                            {isLoading ? (
                                <div className="flex justify-center items-center py-12">
                                    <Loader className="animate-spin" size={32} />
                                </div>
                            ) : (
                                <>
                                    {/* Camera Frames */}
                                    {frames && (
                                        <div className="grid grid-cols-2 gap-4">
                                            {frames.frames.map(f => (
                                                <div key={f.direction}>
                                                    {f.image ? (
                                                        <img
                                                            src={`data:image/jpeg;base64,${f.image}`}
                                                            className="w-full rounded"
                                                        />
                                                    ) : (
                                                        <div className="bg-gray-200 h-40 flex items-center justify-center rounded">
                                                            No image
                                                        </div>
                                                    )}
                                                    <p className="text-center text-sm mt-1">{f.direction}</p>
                                                </div>
                                            ))}
                                        </div>
                                    )}

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
                        </>
                    )}

                    {activeTab === 'traffic_light' && (
                        <TrafficLightPanel
                            intersectionId={intersection.id || `osm_${intersection.osm_id}`}
                        />
                    )}
                </div>
            </div>
        </div>
    );
}