import { useEffect, useMemo, memo } from 'react';
import { useMap } from 'react-leaflet';
import { useMapStore } from '../../store/mapStore';

const FLY_TO_ZOOM = 17;

/**
 * MapController - Programmatic map control component
 *
 * Lives inside MapContainer to access the map instance via useMap().
 * Watches selectedTrafficLightId and flies to the selected intersection.
 * Renders nothing (returns null).
 */
export const MapController = memo(function MapController() {
  const map = useMap();
  const selectedTrafficLightId = useMapStore((state) => state.selectedTrafficLightId);
  const intersections = useMapStore((state) => state.intersections);

  // Memoize the selected intersection lookup to avoid recalculation on every render
  const selectedIntersection = useMemo(() => {
    if (!selectedTrafficLightId) {
      return null;
    }
    return intersections.find((i) => i.sumo_tl_id === selectedTrafficLightId) ?? null;
  }, [selectedTrafficLightId, intersections]);

  // Only trigger flyTo when selectedTrafficLightId changes, not when intersections array changes
  useEffect(() => {
    if (!selectedIntersection) {
      return;
    }

    map.flyTo([selectedIntersection.lat, selectedIntersection.lon], FLY_TO_ZOOM);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedTrafficLightId, map]);

  return null;
});
