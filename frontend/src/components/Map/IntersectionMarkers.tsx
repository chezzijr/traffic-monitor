import { useMapStore } from '../../store/mapStore';
import { IntersectionMarker } from './IntersectionMarker';
import type { Intersection } from '../../types';

interface IntersectionMarkersProps {
  onMarkerClick?: (intersection: Intersection) => void;
}

export function IntersectionMarkers({ onMarkerClick }: IntersectionMarkersProps) {
  const intersections = useMapStore((state) => state.intersections);

  return (
    <>
      {intersections.map((intersection) => (
        <IntersectionMarker
          key={intersection.id}
          intersection={intersection}
          onClick={onMarkerClick}
        />
      ))}
    </>
  );
}
