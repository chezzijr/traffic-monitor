import { memo } from 'react';
import { Marker, Popup } from 'react-leaflet';
import L from 'leaflet';
import type { Intersection } from '../../types';
import { useMapStore } from '../../store/mapStore';

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

// Highlighted traffic light icon (larger with yellow/orange border, for selected state)
const highlightedTrafficLightIcon = L.divIcon({
  className: 'intersection-marker traffic-light highlighted',
  html: `<div class="w-6 h-6 bg-green-500 rounded-full border-3 border-yellow-400 shadow-lg flex items-center justify-center" style="box-shadow: 0 0 8px 2px rgba(251, 191, 36, 0.6); animation: pulse 1.5s ease-in-out infinite;">
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="white" class="w-4 h-4" style="width: 14px; height: 14px;">
      <rect x="9" y="2" width="6" height="20" rx="1" />
      <circle cx="12" cy="6" r="2" />
      <circle cx="12" cy="12" r="2" />
      <circle cx="12" cy="18" r="2" />
    </svg>
  </div>
  <style>
    @keyframes pulse {
      0%, 100% { transform: scale(1); }
      50% { transform: scale(1.1); }
    }
  </style>`,
  iconSize: [24, 24],
  iconAnchor: [12, 12],
});

interface IntersectionMarkerProps {
  intersection: Intersection;
  onClick?: (intersection: Intersection) => void;
}

export const IntersectionMarker = memo(
  function IntersectionMarker({ intersection, onClick }: IntersectionMarkerProps) {
    const selectedTrafficLightId = useMapStore((state) => state.selectedTrafficLightId);
    const manualOverrides = useMapStore((state) => state.manualOverrides);
    const setSelectedTrafficLightId = useMapStore((state) => state.setSelectedTrafficLightId);
    const toggleTrafficLight = useMapStore((state) => state.toggleTrafficLight);

    const isTrafficLight = intersection.has_traffic_light;
    // Only consider selected if BOTH have truthy values and they match
    const isSelected = isTrafficLight && !!intersection.sumo_tl_id && intersection.sumo_tl_id === selectedTrafficLightId;
    const isManualOverride = manualOverrides.has(intersection.id);

    // Determine which icon to use
    const getIcon = () => {
      if (!isTrafficLight) {
        return regularIntersectionIcon;
      }
      return isSelected ? highlightedTrafficLightIcon : trafficLightIcon;
    };

    const handleClick = () => {
      if (isTrafficLight && intersection.sumo_tl_id) {
        // Traffic light clicked: set as selected for training
        setSelectedTrafficLightId(intersection.sumo_tl_id);
      }
      // Also call the external onClick handler if provided
      onClick?.(intersection);
    };

    const handleMarkAsTrafficLight = (e: React.MouseEvent) => {
      e.stopPropagation();
      toggleTrafficLight(intersection.id);
    };

    const handleRemoveTrafficLight = (e: React.MouseEvent) => {
      e.stopPropagation();
      // Clear selection if this traffic light was selected
      if (isSelected) {
        setSelectedTrafficLightId(null);
      }
      toggleTrafficLight(intersection.id);
    };

    return (
      <Marker
        position={[intersection.lat, intersection.lon]}
        icon={getIcon()}
        eventHandlers={{
          click: handleClick,
        }}
      >
        <Popup>
          <div className="text-sm min-w-[180px]">
            <p className="font-semibold">{intersection.name || `Intersection ${intersection.id}`}</p>
            <p>Roads: {intersection.num_roads}</p>

            {isTrafficLight && (
              <p className="text-green-600 font-medium">
                Traffic Light
                {isSelected && (
                  <span className="ml-2 inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium bg-yellow-100 text-yellow-800">
                    Selected
                  </span>
                )}
              </p>
            )}

            {intersection.sumo_tl_id && (
              <p className="text-xs text-gray-600">SUMO TL ID: {intersection.sumo_tl_id}</p>
            )}

            <p className="text-xs text-gray-500 mb-2">
              {intersection.lat.toFixed(6)}, {intersection.lon.toFixed(6)}
            </p>

            {/* Action buttons */}
            <div className="mt-2 pt-2 border-t border-gray-200">
              {!isTrafficLight ? (
                <button
                  onClick={handleMarkAsTrafficLight}
                  className="w-full px-3 py-1.5 text-xs font-medium text-white bg-green-600 rounded hover:bg-green-700 transition-colors"
                >
                  Mark as Traffic Light
                </button>
              ) : (
                <>
                  {isManualOverride && (
                    <button
                      onClick={handleRemoveTrafficLight}
                      className="w-full px-3 py-1.5 text-xs font-medium text-white bg-red-600 rounded hover:bg-red-700 transition-colors"
                    >
                      Remove Traffic Light
                    </button>
                  )}
                  {!isSelected && intersection.sumo_tl_id && (
                    <button
                      onClick={() => setSelectedTrafficLightId(intersection.sumo_tl_id!)}
                      className="w-full px-3 py-1.5 text-xs font-medium text-white bg-yellow-500 rounded hover:bg-yellow-600 transition-colors mt-1"
                    >
                      Select for Training
                    </button>
                  )}
                  {isSelected && (
                    <button
                      onClick={() => setSelectedTrafficLightId(null)}
                      className="w-full px-3 py-1.5 text-xs font-medium text-gray-700 bg-gray-200 rounded hover:bg-gray-300 transition-colors mt-1"
                    >
                      Deselect
                    </button>
                  )}
                </>
              )}
            </div>
          </div>
        </Popup>
      </Marker>
    );
  },
  (prev, next) =>
    prev.intersection.id === next.intersection.id &&
    prev.intersection.has_traffic_light === next.intersection.has_traffic_light
);
