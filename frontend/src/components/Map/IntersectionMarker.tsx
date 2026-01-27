import { Marker, Popup } from 'react-leaflet';
import L from 'leaflet';
import type { Intersection } from '../../types';

// Custom marker icon for intersections
const intersectionIcon = L.divIcon({
  className: 'intersection-marker',
  html: '<div class="w-4 h-4 bg-blue-500 rounded-full border-2 border-white shadow-md"></div>',
  iconSize: [16, 16],
  iconAnchor: [8, 8],
});

interface IntersectionMarkerProps {
  intersection: Intersection;
  onClick?: (intersection: Intersection) => void;
}

export function IntersectionMarker({ intersection, onClick }: IntersectionMarkerProps) {
  return (
    <Marker
      position={[intersection.lat, intersection.lon]}
      icon={intersectionIcon}
      eventHandlers={{
        click: () => onClick?.(intersection),
      }}
    >
      <Popup>
        <div className="text-sm">
          <p className="font-semibold">{intersection.name || `Intersection ${intersection.id}`}</p>
          <p>Roads: {intersection.num_roads}</p>
          <p className="text-xs text-gray-500">
            {intersection.lat.toFixed(6)}, {intersection.lon.toFixed(6)}
          </p>
        </div>
      </Popup>
    </Marker>
  );
}
