import { Marker, Popup } from 'react-leaflet';
import { useMapStore } from '../../store/mapStore';
import { grayIcon, greenIcon, amberIcon, purpleIcon } from './markerIcons';
import type { Intersection } from '../../types';

interface SelectableIntersectionMarkersProps {
  deployedJunctionIds?: string[];
  onIntersectionClick?: (intersection: Intersection) => void;
}

// Special clickable intersection: Tran Binh Trong x Tran Hung Dao.
const THD_TBT_LAT = 10.755388;
const THD_TBT_LON = 106.681386;
const COORD_TOLERANCE = 0.002;

const isTHDTBTIntersection = (intersection: Intersection): boolean =>
  Math.abs(intersection.lat - THD_TBT_LAT) < COORD_TOLERANCE &&
  Math.abs(intersection.lon - THD_TBT_LON) < COORD_TOLERANCE;

export function SelectableIntersectionMarkers({ deployedJunctionIds = [], onIntersectionClick }: SelectableIntersectionMarkersProps) {
  const intersections = useMapStore((s) => s.intersections);
  const sumoTrafficLights = useMapStore((s) => s.sumoTrafficLights);
  const selectedRegion = useMapStore((s) => s.selectedRegion);
  const selectedJunctionIds = useMapStore((s) => s.selectedJunctionIds);
  const toggleJunctionSelection = useMapStore((s) => s.toggleJunctionSelection);

  // SUMO TLs without OSM matches still get rendered from their boundary-
  // reverse-projected lat/lon — scoped to the user's bbox so tlLogics leaked
  // by netconvert's buffer don't clutter the map.
  const osmMatchedTlIds = new Set(
    intersections.map((i) => i.sumo_tl_id).filter(Boolean) as string[],
  );
  const unmatchedSumoTls = sumoTrafficLights.filter(
    (tl) =>
      tl.lat != null &&
      tl.lon != null &&
      !osmMatchedTlIds.has(tl.id) &&
      (!selectedRegion ||
        (tl.lat >= selectedRegion.south &&
          tl.lat <= selectedRegion.north &&
          tl.lon >= selectedRegion.west &&
          tl.lon <= selectedRegion.east)),
  );

  return (
    <>
      {intersections.map((intersection) => {
        const sumoTlId = intersection.sumo_tl_id;
        const hasTL = intersection.has_traffic_light && sumoTlId;

        if (!hasTL) {
          const isSpecialIntersection = isTHDTBTIntersection(intersection);

          return (
            <Marker
              key={intersection.id}
              position={[intersection.lat, intersection.lon]}
              icon={grayIcon}
              eventHandlers={
                isSpecialIntersection
                  ? {
                      click: () => onIntersectionClick?.(intersection),
                    }
                  : undefined
              }
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
              click: () => {
                toggleJunctionSelection(sumoTlId);
                onIntersectionClick?.(intersection);
              },
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
      {unmatchedSumoTls.map((tl) => {
        const isDeployed = deployedJunctionIds.includes(tl.id);
        const isSelected = selectedJunctionIds.includes(tl.id);
        const icon = isDeployed ? purpleIcon : isSelected ? amberIcon : greenIcon;
        return (
          <Marker
            key={`sumo-${tl.id}`}
            position={[tl.lat as number, tl.lon as number]}
            icon={icon}
            eventHandlers={{
              click: () => toggleJunctionSelection(tl.id),
            }}
          >
            <Popup>
              <div className="text-sm">
                <p className="font-semibold">Junction {tl.id}</p>
                <p className="text-xs text-gray-600">SUMO TL: {tl.id}</p>
                <p className="text-xs text-gray-400 italic">No OSM match</p>
                {isSelected && (
                  <p className="text-xs text-amber-600 font-medium mt-1">Selected for training</p>
                )}
              </div>
            </Popup>
          </Marker>
        );
      })}
    </>
  );
}
