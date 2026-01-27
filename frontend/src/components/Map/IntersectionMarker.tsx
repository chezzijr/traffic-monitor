import { Marker, Popup } from 'react-leaflet';
import L from 'leaflet';
import type { Intersection } from '../../types';

// Custom marker icon for regular intersections (blue)
const regularIntersectionIcon = L.divIcon({
  className: 'intersection-marker',
  html: '<div class="w-4 h-4 bg-blue-500 rounded-full border-2 border-white shadow-md"></div>',
  iconSize: [16, 16],
  iconAnchor: [8, 8],
});

// Custom marker icon for traffic light intersections (green with TL symbol)
const trafficLightIcon = L.divIcon({
  className: 'intersection-marker traffic-light',
  html: `<div class="w-5 h-5 bg-green-500 rounded-full border-2 border-white shadow-md flex items-center justify-center">
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="white" class="w-3 h-3" style="width: 12px; height: 12px;">
      <rect x="9" y="2" width="6" height="20" rx="1" />
      <circle cx="12" cy="6" r="2" />
      <circle cx="12" cy="12" r="2" />
      <circle cx="12" cy="18" r="2" />
    </svg>
  </div>`,
  iconSize: [20, 20],
  iconAnchor: [10, 10],
});

interface IntersectionMarkerProps {
  intersection: Intersection;
  onClick?: (intersection: Intersection) => void;
}

export function IntersectionMarker({ intersection, onClick }: IntersectionMarkerProps) {
  const icon = intersection.has_traffic_light ? trafficLightIcon : regularIntersectionIcon;

  return (
    <Marker
      position={[intersection.lat, intersection.lon]}
      icon={icon}
      eventHandlers={{
        click: () => onClick?.(intersection),
      }}
    >
      <Popup>
        <div className="text-sm">
          <p className="font-semibold">{intersection.name || `Intersection ${intersection.id}`}</p>
          <p>Roads: {intersection.num_roads}</p>
          {intersection.has_traffic_light && (
            <p className="text-green-600 font-medium">Traffic Light</p>
          )}
          {intersection.sumo_tl_id && (
            <p className="text-xs text-gray-600">SUMO TL ID: {intersection.sumo_tl_id}</p>
          )}
          <p className="text-xs text-gray-500">
            {intersection.lat.toFixed(6)}, {intersection.lon.toFixed(6)}
          </p>
        </div>
      </Popup>
    </Marker>
  );
}
