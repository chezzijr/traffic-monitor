import { useEffect, useState } from 'react';
import { X, Play, Loader } from 'lucide-react';
import toast from 'react-hot-toast';
import { cameraService } from '../../services';
import type { CameraResponse, Intersection } from '../../types';

interface CameraModalProps {
    intersection: Intersection | null;
    isOpen: boolean;
    onClose: () => void;
}

export function CameraModal({ intersection, isOpen, onClose }: CameraModalProps) {
    const [cameraData, setCameraData] = useState<CameraResponse | null>(null);
    const [isLoading, setIsLoading] = useState(false);
    const [streamError, setStreamError] = useState<string | null>(null);

    // Load camera data when modal opens
    useEffect(() => {
        if (!isOpen || !intersection) {
            // Reset state when modal closes
            setCameraData(null);
            setStreamError(null);
            return;
        }

        const loadCameraData = async () => {
            setIsLoading(true);
            setStreamError(null);
            try {
                const data = await cameraService.getCameraData(intersection.id);
                setCameraData(data);
            } catch (err) {
                const message = err instanceof Error ? err.message : 'Failed to load camera data';
                setStreamError(message);
                toast.error(message);
            } finally {
                setIsLoading(false);
            }
        };

        loadCameraData();
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

    const snapshot = cameraData?.snapshot;
    const stream = cameraData?.stream;
    const hasStream = stream?.is_available && stream?.stream_url;

    const handleOpenStream = () => {
        if (!hasStream) {
            toast.error('Live stream is not available for this intersection');
            return;
        }

        // Open stream in new window/tab
        const streamUrl = stream.stream_url;
        if (streamUrl) {
            window.open(streamUrl, '_blank', 'width=800,height=600');
        }
    };

    const handleDownloadSnapshot = () => {
        if (!snapshot) return;

        const link = document.createElement('a');
        link.href = cameraService.getImageDataUrl(snapshot);
        link.download = `snapshot_${intersection.id}_${Date.now()}`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    };

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
                        <h2 className="text-xl font-bold">{intersection.name || `Intersection ${intersection.id}`}</h2>
                        <p className="text-sm text-gray-500">Camera Feed & Live Stream</p>
                    </div>
                    <button
                        onClick={onClose}
                        className="p-1 hover:bg-gray-100 rounded transition-colors"
                    >
                        <X size={24} />
                    </button>
                </div>

                {/* Content */}
                <div className="p-6 space-y-6">
                    {isLoading ? (
                        <div className="flex justify-center items-center py-12">
                            <Loader className="animate-spin" size={32} />
                        </div>
                    ) : (
                        <>
                            {/* Snapshot Section */}
                            <div className="space-y-3">
                                <h3 className="font-semibold text-lg">Latest Snapshot</h3>
                                {snapshot ? (
                                    <div className="space-y-3">
                                        <div className="aspect-video bg-gray-100 rounded-lg overflow-hidden flex items-center justify-center">
                                            {cameraService.isImage(snapshot) ? (
                                                <img
                                                    src={cameraService.getImageDataUrl(snapshot)}
                                                    alt="Snapshot"
                                                    className="w-full h-full object-cover"
                                                />
                                            ) : (
                                                <video
                                                    src={cameraService.getImageDataUrl(snapshot)}
                                                    controls
                                                    className="w-full h-full"
                                                />
                                            )}
                                        </div>
                                        <div className="flex items-center justify-between text-sm">
                                            <div className="text-gray-600">
                                                <p>Timestamp: {new Date(snapshot.timestamp).toLocaleString()}</p>
                                                <p>Step: {snapshot.step}</p>
                                            </div>
                                            <button
                                                onClick={handleDownloadSnapshot}
                                                className="px-3 py-1 bg-blue-500 text-white rounded hover:bg-blue-600 transition-colors text-sm"
                                            >
                                                Download
                                            </button>
                                        </div>
                                    </div>
                                ) : (
                                    <div className="aspect-video bg-gray-100 rounded-lg flex items-center justify-center text-gray-500">
                                        No snapshot available
                                    </div>
                                )}
                            </div>

                            {/* Live Stream Section */}
                            <div className="space-y-3 border-t pt-6">
                                <h3 className="font-semibold text-lg">Live Stream</h3>
                                <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
                                    {streamError && (
                                        <div className="text-red-600 mb-3">{streamError}</div>
                                    )}
                                    <div className="flex items-center justify-between">
                                        <div>
                                            {hasStream ? (
                                                <div className="space-y-1">
                                                    <p className="text-sm font-medium text-gray-700">Stream Available</p>
                                                    <p className="text-xs text-gray-500">{stream.stream_url}</p>
                                                </div>
                                            ) : (
                                                <div>
                                                    <p className="text-sm text-gray-600">
                                                        {stream ? 'No stream configured' : 'Loading...'}
                                                    </p>
                                                </div>
                                            )}
                                        </div>
                                        <button
                                            onClick={handleOpenStream}
                                            disabled={!hasStream || isLoading}
                                            className={`flex items-center gap-2 px-4 py-2 rounded transition-colors ${hasStream
                                                ? 'bg-green-500 text-white hover:bg-green-600'
                                                : 'bg-gray-300 text-gray-500 cursor-not-allowed'
                                                }`}
                                        >
                                            <Play size={18} />
                                            Live
                                        </button>
                                    </div>
                                </div>
                            </div>

                            {/* Recent Snapshots */}
                            {cameraData?.available_snapshots && cameraData.available_snapshots.length > 1 && (
                                <div className="space-y-3 border-t pt-6">
                                    <h3 className="font-semibold text-lg">Recent Snapshots</h3>
                                    <div className="grid grid-cols-3 gap-3">
                                        {cameraData.available_snapshots.map((snap) => (
                                            <div
                                                key={snap.id}
                                                className="relative aspect-video bg-gray-100 rounded-lg overflow-hidden cursor-pointer hover:opacity-80 transition-opacity group"
                                            >
                                                {cameraService.isImage(snap) ? (
                                                    <img
                                                        src={cameraService.getImageDataUrl(snap)}
                                                        alt="Snapshot"
                                                        className="w-full h-full object-cover"
                                                    />
                                                ) : (
                                                    <div className="w-full h-full bg-gray-200 flex items-center justify-center">
                                                        <span className="text-xs text-gray-500">Video</span>
                                                    </div>
                                                )}
                                                <div className="absolute inset-0 bg-black bg-opacity-0 group-hover:bg-opacity-50 transition-all flex items-center justify-center text-white text-xs opacity-0 group-hover:opacity-100">
                                                    {new Date(snap.timestamp).toLocaleTimeString()}
                                                </div>
                                            </div>
                                        ))}
                                    </div>
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
                </div>
            </div>
        </div>
    );
}
