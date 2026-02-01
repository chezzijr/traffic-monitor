import { Marker, Popup } from 'react-leaflet';
import L from 'leaflet';
import type { TrafficSignal } from '../../types';

const trafficSignalIcon = L.divIcon({
    className: 'traffic-signal-marker',
    html: '<div class="w-4 h-4 bg-orange-500 rounded-full border-2 border-white shadow-md"></div>',
    iconSize: [16, 16],
    iconAnchor: [8, 8],
});

interface TrafficSignalMarkerProps {
    signal: TrafficSignal;
}

export function TrafficSignalMarker({ signal }: TrafficSignalMarkerProps) {
    return (
        <Marker position={[signal.lat, signal.lon]} icon={trafficSignalIcon}>
            <Popup>
                <div className="text-sm">
                    <p className="font-semibold">OSM Traffic Signal</p>
                    <p>ID: {signal.osm_id}</p>
                    <p className="text-xs text-gray-500">
                        {signal.lat.toFixed(6)}, {signal.lon.toFixed(6)}
                    </p>
                </div>
            </Popup>
        </Marker>
    );
}
