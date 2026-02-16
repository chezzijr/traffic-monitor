import { memo } from 'react';
import { Marker, Popup } from 'react-leaflet';
import L from 'leaflet';
import type { SumoJunction } from '../../types';
import { useMapStore } from '../../store/mapStore';

// Regular SUMO junction marker icon (orange with "J" label)
const regularJunctionIcon = L.divIcon({
  className: 'sumo-junction-marker',
  html: `<div style="
    width: 20px;
    height: 20px;
    background-color: #f97316;
    border-radius: 50%;
    border: 2px solid white;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.3);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 11px;
    font-weight: bold;
    color: white;
    font-family: system-ui, -apple-system, sans-serif;
  ">J</div>`,
  iconSize: [20, 20],
  iconAnchor: [10, 10],
});

// Highlighted SUMO junction marker icon (larger with yellow border, glow, and pulse)
const highlightedJunctionIcon = L.divIcon({
  className: 'sumo-junction-marker highlighted',
  html: `<div style="
    width: 28px;
    height: 28px;
    background-color: #f97316;
    border-radius: 50%;
    border: 3px solid #facc15;
    box-shadow: 0 0 12px 4px rgba(251, 191, 36, 0.6);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 14px;
    font-weight: bold;
    color: white;
    font-family: system-ui, -apple-system, sans-serif;
    animation: sumo-junction-pulse 1.5s ease-in-out infinite;
  ">J</div>
  <style>
    @keyframes sumo-junction-pulse {
      0%, 100% { transform: scale(1); }
      50% { transform: scale(1.1); }
    }
  </style>`,
  iconSize: [28, 28],
  iconAnchor: [14, 14],
});

interface SumoJunctionMarkerProps {
  junction: SumoJunction;
}

export const SumoJunctionMarker = memo(
  function SumoJunctionMarker({ junction }: SumoJunctionMarkerProps) {
    const selectedTrafficLightId = useMapStore((state) => state.selectedTrafficLightId);
    const setSelectedTrafficLightId = useMapStore((state) => state.setSelectedTrafficLightId);

    // Only consider selected if junction has tl_id and it matches selectedTrafficLightId
    const isSelected = !!junction.tl_id && junction.tl_id === selectedTrafficLightId;

    const getIcon = () => {
      return isSelected ? highlightedJunctionIcon : regularJunctionIcon;
    };

    const handleClick = () => {
      if (junction.tl_id) {
        setSelectedTrafficLightId(junction.tl_id);
      }
    };

    const handleSelectForTraining = (e: React.MouseEvent) => {
      e.stopPropagation();
      if (junction.tl_id) {
        setSelectedTrafficLightId(junction.tl_id);
      }
    };

    const handleDeselect = (e: React.MouseEvent) => {
      e.stopPropagation();
      setSelectedTrafficLightId(null);
    };

    return (
      <Marker
        position={[junction.lat, junction.lon]}
        icon={getIcon()}
        eventHandlers={{
          click: handleClick,
        }}
      >
        <Popup>
          <div className="text-sm min-w-[200px]">
            <p className="font-semibold text-orange-600">
              SUMO Junction
              {isSelected && (
                <span className="ml-2 inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium bg-yellow-100 text-yellow-800">
                  Selected
                </span>
              )}
            </p>

            <div className="mt-2 space-y-1">
              {junction.tl_id && (
                <p className="text-xs">
                  <span className="text-gray-500">TL ID:</span>{' '}
                  <span className="font-medium">{junction.tl_id}</span>
                </p>
              )}
              <p className="text-xs">
                <span className="text-gray-500">Junction ID:</span>{' '}
                <span className="font-medium">{junction.id}</span>
              </p>
              {junction.name && (
                <p className="text-xs">
                  <span className="text-gray-500">Name:</span>{' '}
                  <span className="font-medium">{junction.name}</span>
                </p>
              )}
              <p className="text-xs">
                <span className="text-gray-500">Type:</span>{' '}
                <span className="font-medium">{junction.junction_type}</span>
              </p>
              <p className="text-xs">
                <span className="text-gray-500">Incoming Lanes:</span>{' '}
                <span className="font-medium">{junction.incoming_lanes}</span>
              </p>
            </div>

            <p className="text-xs text-gray-500 mt-2">
              {junction.lat.toFixed(6)}, {junction.lon.toFixed(6)}
            </p>

            {/* Action buttons */}
            {junction.tl_id && (
              <div className="mt-2 pt-2 border-t border-gray-200">
                {!isSelected ? (
                  <button
                    onClick={handleSelectForTraining}
                    className="w-full px-3 py-1.5 text-xs font-medium text-white bg-yellow-500 rounded hover:bg-yellow-600 transition-colors"
                  >
                    Select for Training
                  </button>
                ) : (
                  <button
                    onClick={handleDeselect}
                    className="w-full px-3 py-1.5 text-xs font-medium text-gray-700 bg-gray-200 rounded hover:bg-gray-300 transition-colors"
                  >
                    Deselect
                  </button>
                )}
              </div>
            )}
          </div>
        </Popup>
      </Marker>
    );
  },
  (prev, next) =>
    prev.junction.id === next.junction.id &&
    prev.junction.tl_id === next.junction.tl_id
);
