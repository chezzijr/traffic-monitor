import { useEffect, useMemo, memo } from 'react';
import { useMap } from 'react-leaflet';
import { useMapStore } from '../../store/mapStore';

const FLY_TO_ZOOM = 17;

/**
 * MapController - Programmatic map control component
 *
 * Lives inside MapContainer to access the map instance via useMap().
 * Watches selectedTrafficLightId and flies to the selected intersection or SUMO junction.
 * Renders nothing (returns null).
 */
export const MapController = memo(function MapController() {
  const map = useMap();
  const selectedTrafficLightId = useMapStore((state) => state.selectedTrafficLightId);
  const intersections = useMapStore((state) => state.intersections);
  const sumoJunctions = useMapStore((state) => state.sumoJunctions);

  // Memoize the selected location lookup - search both intersections and SUMO junctions
  const selectedLocation = useMemo(() => {
    if (!selectedTrafficLightId) {
      return null;
    }

    // First, try to find in intersections (by sumo_tl_id)
    const intersection = intersections.find((i) => i.sumo_tl_id === selectedTrafficLightId);
    if (intersection) {
      return { lat: intersection.lat, lon: intersection.lon };
    }

    // Then, try to find in SUMO junctions (by tl_id)
    const junction = sumoJunctions.find((j) => j.tl_id === selectedTrafficLightId);
    if (junction) {
      return { lat: junction.lat, lon: junction.lon };
    }

    return null;
  }, [selectedTrafficLightId, intersections, sumoJunctions]);

  // Only trigger flyTo when selectedTrafficLightId changes
  useEffect(() => {
    if (!selectedLocation) {
      return;
    }

    map.flyTo([selectedLocation.lat, selectedLocation.lon], FLY_TO_ZOOM);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedTrafficLightId, map]);

  return null;
});
