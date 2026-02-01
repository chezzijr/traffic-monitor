import { useState } from 'react';
import toast from 'react-hot-toast';
import { MapPin } from 'lucide-react';
import { mapService } from '../../services';
import { useMapStore } from '../../store/mapStore';

const DEFAULT_LAT = 10.8231;
const DEFAULT_LNG = 106.6297;
const DEFAULT_RADIUS = 500;

export function TrafficSignalSearch() {
    const [lat, setLat] = useState(String(DEFAULT_LAT));
    const [lng, setLng] = useState(String(DEFAULT_LNG));
    const [radius, setRadius] = useState(String(DEFAULT_RADIUS));
    const [isLoading, setIsLoading] = useState(false);
    const setTrafficSignals = useMapStore((state) => state.setTrafficSignals);

    const handleSearch = async () => {
        const latNum = Number(lat);
        const lngNum = Number(lng);
        const radiusNum = Number(radius);

        if (Number.isNaN(latNum) || Number.isNaN(lngNum) || Number.isNaN(radiusNum)) {
            toast.error('Please enter valid numbers for lat, lon, and radius');
            return;
        }

        setIsLoading(true);
        try {
            const signals = await mapService.getTrafficSignals({
                lat: latNum,
                lng: lngNum,
                radius: Math.max(1, Math.floor(radiusNum)),
            });
            setTrafficSignals(signals);
            toast.success(`Found ${signals.length} traffic signals`);
        } catch (err) {
            const message = err instanceof Error ? err.message : 'Failed to fetch traffic signals';
            toast.error(message);
        } finally {
            setIsLoading(false);
        }
    };

    return (
        <div className="bg-white rounded-lg shadow p-4">
            <div className="flex items-center gap-2 mb-3">
                <MapPin size={18} />
                <h3 className="text-lg font-semibold">Traffic Signals</h3>
            </div>

            <div className="space-y-3">
                <div>
                    <label className="block text-xs font-medium text-gray-600 mb-1">Lat</label>
                    <input
                        value={lat}
                        onChange={(e) => setLat(e.target.value)}
                        type="number"
                        step="0.000001"
                        className="w-full px-3 py-2 border rounded text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                    />
                </div>

                <div>
                    <label className="block text-xs font-medium text-gray-600 mb-1">Lon</label>
                    <input
                        value={lng}
                        onChange={(e) => setLng(e.target.value)}
                        type="number"
                        step="0.000001"
                        className="w-full px-3 py-2 border rounded text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                    />
                </div>

                <div>
                    <label className="block text-xs font-medium text-gray-600 mb-1">Radius (m)</label>
                    <input
                        value={radius}
                        onChange={(e) => setRadius(e.target.value)}
                        type="number"
                        min={1}
                        step={50}
                        className="w-full px-3 py-2 border rounded text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                    />
                </div>

                <button
                    onClick={handleSearch}
                    disabled={isLoading}
                    className="w-full px-4 py-2 bg-orange-500 text-white rounded font-medium hover:bg-orange-600 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                    {isLoading ? 'Loading...' : 'Fetch Traffic Signals'}
                </button>
            </div>
        </div>
    );
}
