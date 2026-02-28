import { Marker, Popup } from 'react-leaflet';
import L from 'leaflet';
import type { TrafficLight } from '../../types';

const trafficLightIcon = L.divIcon({
    className: 'traffic-light-marker',
    html: '<div class="w-4 h-4 bg-green-500 rounded-full border-2 border-white shadow-md"></div>',
    iconSize: [16, 16],
    iconAnchor: [8, 8],
});

interface TrafficLightMarkerProps {
    light: TrafficLight;
    onClick?: (light: TrafficLight) => void;
}

export function TrafficLightMarker({ light, onClick }: TrafficLightMarkerProps) {
    return (
        <Marker
            position={[light.lat, light.lon]}
            icon={trafficLightIcon}
            eventHandlers={{
                click: () => onClick?.(light),
            }}
        >
            {/* <Popup>
                <div className="text-sm">
                    <p className="font-semibold">OSM Traffic Light</p>
                    <p>ID: {light.osm_id}</p>
                    <p className="text-xs text-gray-500">
                        {light.lat.toFixed(6)}, {light.lon.toFixed(6)}
                    </p>
                </div>
            </Popup> */}
        </Marker>
    );
}
