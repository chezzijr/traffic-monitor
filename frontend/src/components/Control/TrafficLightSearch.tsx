import { useState, useEffect } from 'react';
import toast from 'react-hot-toast';
import { MapPin, MapPinPlus } from 'lucide-react';
import { mapService } from '../../services';
import { useMapStore } from '../../store/mapStore';

const DEFAULT_LAT = 10.770487;
const DEFAULT_LNG = 106.658213;
const DEFAULT_RADIUS = 700;

export function TrafficLightSearch() {
    const [lat, setLat] = useState(String(DEFAULT_LAT));
    const [lng, setLng] = useState(String(DEFAULT_LNG));
    const [radius, setRadius] = useState(String(DEFAULT_RADIUS));
    const [isLoading, setIsLoading] = useState(false);
    const { setTrafficLights, isSelectingLocation, setIsSelectingLocation, selectedLocation } =
        useMapStore();

    // Update lat/lng when location is selected on map
    useEffect(() => {
        if (selectedLocation) {
            setLat(selectedLocation.lat.toFixed(6));
            setLng(selectedLocation.lng.toFixed(6));
        }
    }, [selectedLocation]);

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
            const lights = await mapService.getTrafficLights({
                lat: latNum,
                lng: lngNum,
                radius: Math.max(1, Math.floor(radiusNum)),
            });
            setTrafficLights(lights);
            toast.success(`Found ${lights.length} traffic lights`);
        } catch (err) {
            const message = err instanceof Error ? err.message : 'Failed to fetch traffic lights';
            toast.error(message);
        } finally {
            setIsLoading(false);
        }
    };

    return (
        <div className="bg-white rounded-lg shadow p-4">
            <div className="flex items-center gap-2 mb-3">
                <MapPin size={18} />
                <h3 className="text-lg font-semibold">Traffic Lights</h3>
            </div>

            <div className="space-y-3">
                <div className="flex gap-2">
                    <button
                        onClick={() => setIsSelectingLocation(!isSelectingLocation)}
                        className={`flex-1 flex items-center justify-center gap-2 px-3 py-2 rounded font-medium transition-colors ${isSelectingLocation
                            ? 'bg-blue-500 text-white'
                            : 'bg-gray-100 hover:bg-gray-200'
                            }`}
                    >
                        <MapPinPlus size={16} />
                        {isSelectingLocation ? 'Click on Map' : 'Pick Location'}
                    </button>
                    {selectedLocation && (
                        <button
                            onClick={() => {
                                useMapStore.getState().setSelectedLocation(null);
                                setIsSelectingLocation(false);
                            }}
                            className="flex-1 px-3 py-2 rounded bg-gray-100 hover:bg-gray-200 font-medium transition-colors text-sm"
                        >
                            Clear
                        </button>
                    )}
                </div>

                {selectedLocation && (
                    <div className="text-xs bg-blue-50 p-2 rounded border border-blue-200">
                        <p className="text-blue-900">
                            Selected: {selectedLocation.lat.toFixed(6)}, {selectedLocation.lng.toFixed(6)}
                        </p>
                    </div>
                )}

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
                    {isLoading ? 'Loading...' : 'Fetch Traffic Lights'}
                </button>
            </div>
        </div>
    );
}