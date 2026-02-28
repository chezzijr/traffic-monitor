import { Marker, Popup } from 'react-leaflet';
import L from 'leaflet';
import { useMapStore } from '../../store/mapStore';

const grayIcon = L.divIcon({
  className: 'selectable-intersection-marker',
  html: '<div style="width:8px;height:8px;background:#9ca3af;border-radius:50%;border:1px solid white;"></div>',
  iconSize: [8, 8],
  iconAnchor: [4, 4],
});

const greenIcon = L.divIcon({
  className: 'selectable-intersection-marker',
  html: '<div style="width:18px;height:18px;background:#22c55e;border-radius:50%;border:2px solid white;box-shadow:0 1px 3px rgba(0,0,0,0.3);cursor:pointer;"></div>',
  iconSize: [18, 18],
  iconAnchor: [9, 9],
});

const amberIcon = L.divIcon({
  className: 'selectable-intersection-marker',
  html: '<div style="width:20px;height:20px;background:#f59e0b;border-radius:50%;border:2px solid white;box-shadow:0 0 8px rgba(245,158,11,0.6);cursor:pointer;animation:pulse 2s infinite;"></div>',
  iconSize: [20, 20],
  iconAnchor: [10, 10],
});

const purpleIcon = L.divIcon({
  className: 'selectable-intersection-marker',
  html: '<div style="width:20px;height:20px;background:#a855f7;border-radius:50%;border:2px solid white;box-shadow:0 0 8px rgba(168,85,247,0.6);cursor:pointer;"></div>',
  iconSize: [20, 20],
  iconAnchor: [10, 10],
});

interface SelectableIntersectionMarkersProps {
  deployedJunctionIds?: string[];
}

export function SelectableIntersectionMarkers({ deployedJunctionIds = [] }: SelectableIntersectionMarkersProps) {
  const intersections = useMapStore((s) => s.intersections);
  const selectedJunctionIds = useMapStore((s) => s.selectedJunctionIds);
  const toggleJunctionSelection = useMapStore((s) => s.toggleJunctionSelection);

  return (
    <>
      {intersections.map((intersection) => {
        const sumoTlId = intersection.sumo_tl_id;
        const hasTL = intersection.has_traffic_light && sumoTlId;

        if (!hasTL) {
          return (
            <Marker
              key={intersection.id}
              position={[intersection.lat, intersection.lon]}
              icon={grayIcon}
            />
          );
        }

        const isDeployed = deployedJunctionIds.includes(sumoTlId);
        const isSelected = selectedJunctionIds.includes(sumoTlId);
        const icon = isDeployed ? purpleIcon : isSelected ? amberIcon : greenIcon;

        return (
          <Marker
            key={intersection.id}
            position={[intersection.lat, intersection.lon]}
            icon={icon}
            eventHandlers={{
              click: () => toggleJunctionSelection(sumoTlId),
            }}
          >
            <Popup>
              <div className="text-sm">
                <p className="font-semibold">
                  {intersection.name || `Junction ${sumoTlId}`}
                </p>
                <p className="text-xs text-gray-600">SUMO TL: {sumoTlId}</p>
                <p className="text-xs text-gray-500">
                  {intersection.lat.toFixed(6)}, {intersection.lon.toFixed(6)}
                </p>
                {isSelected && (
                  <p className="text-xs text-amber-600 font-medium mt-1">Selected for training</p>
                )}
                {isDeployed && (
                  <p className="text-xs text-purple-600 font-medium mt-1">AI Model Deployed</p>
                )}
              </div>
            </Popup>
          </Marker>
        );
      })}
    </>
  );
}
