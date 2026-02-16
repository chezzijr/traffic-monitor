import { memo } from 'react';
import { useMapStore } from '../../store/mapStore';
import { SumoJunctionMarker } from './SumoJunctionMarker';

export const SumoJunctionMarkers = memo(function SumoJunctionMarkers() {
  const sumoJunctions = useMapStore((state) => state.sumoJunctions);

  // Filter to only signalized junctions (those with a traffic light ID)
  const signalizedJunctions = sumoJunctions.filter(
    (junction) => junction.tl_id !== null
  );

  return (
    <>
      {signalizedJunctions.map((junction) => (
        <SumoJunctionMarker key={junction.id} junction={junction} />
      ))}
    </>
  );
});
