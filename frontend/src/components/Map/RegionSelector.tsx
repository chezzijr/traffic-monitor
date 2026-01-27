import { useState } from 'react';
import { useMapEvents, Rectangle } from 'react-leaflet';
import { LatLng, LatLngBounds } from 'leaflet';
import { useMapStore } from '../../store/mapStore';
import type { BoundingBox } from '../../types';

function latLngBoundsToBbox(bounds: LatLngBounds): BoundingBox {
  return {
    south: bounds.getSouth(),
    west: bounds.getWest(),
    north: bounds.getNorth(),
    east: bounds.getEast(),
  };
}

export function RegionSelector() {
  const { selectionMode, setSelectedRegion, setSelectionMode, selectedRegion } = useMapStore();
  const [startPoint, setStartPoint] = useState<LatLng | null>(null);
  const [currentBounds, setCurrentBounds] = useState<LatLngBounds | null>(null);

  // Handle map events for drawing
  useMapEvents({
    mousedown(e) {
      if (selectionMode) {
        setStartPoint(e.latlng);
        setCurrentBounds(null);
      }
    },
    mousemove(e) {
      if (selectionMode && startPoint) {
        const bounds = new LatLngBounds(startPoint, e.latlng);
        setCurrentBounds(bounds);
      }
    },
    mouseup(e) {
      if (selectionMode && startPoint) {
        const bounds = new LatLngBounds(startPoint, e.latlng);
        setSelectedRegion(latLngBoundsToBbox(bounds));
        setStartPoint(null);
        setCurrentBounds(null);
        setSelectionMode(false);
      }
    },
  });

  // Convert selectedRegion back to bounds for display
  const displayBounds = currentBounds || (selectedRegion ? new LatLngBounds(
    [selectedRegion.south, selectedRegion.west],
    [selectedRegion.north, selectedRegion.east]
  ) : null);

  if (!displayBounds) return null;

  return (
    <Rectangle
      bounds={displayBounds}
      pathOptions={{
        color: currentBounds ? '#3b82f6' : '#22c55e',
        weight: 2,
        fillOpacity: 0.1,
        dashArray: currentBounds ? '5, 5' : undefined,
      }}
    />
  );
}
