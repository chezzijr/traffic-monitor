import { useMapStore } from '../../store/mapStore';
import { IntersectionMarker } from './IntersectionMarker';

export function IntersectionMarkers() {
  const intersections = useMapStore((state) => state.intersections);

  return (
    <>
      {intersections.map((intersection) => (
        <IntersectionMarker key={intersection.id} intersection={intersection} />
      ))}
    </>
  );
}
