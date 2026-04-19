import { Marker, Popup } from 'react-leaflet';
import { useMapStore } from '../../store/mapStore';
import { grayIcon, greenIcon, amberIcon, purpleIcon } from './markerIcons';

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
          // return null;
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
                {intersection.clustered_tl_ids && intersection.clustered_tl_ids.length > 1 && (
                  <p className="text-xs text-gray-500 mt-0.5">
                    Merged TLs: {intersection.clustered_tl_ids.join(', ')}
                  </p>
                )}
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
