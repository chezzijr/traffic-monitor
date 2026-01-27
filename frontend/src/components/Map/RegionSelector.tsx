import { useState, useEffect } from 'react';
import { useMapEvents, Rectangle, useMap } from 'react-leaflet';
import { LatLng, LatLngBounds } from 'leaflet';
import { useMapStore } from '../../store/mapStore';
import type { BoundingBox } from '../../types';

const MIN_SELECTION_SIZE_PX = 10;

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
  const map = useMap();

  // Disable map dragging during selection mode and set crosshair cursor
  useEffect(() => {
    if (selectionMode) {
      map.dragging.disable();
      map.getContainer().style.cursor = 'crosshair';
    } else {
      map.dragging.enable();
      map.getContainer().style.cursor = '';
    }
    return () => {
      map.dragging.enable();
      map.getContainer().style.cursor = '';
    };
  }, [selectionMode, map]);

  // Handle Escape key to cancel selection
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && selectionMode) {
        setStartPoint(null);
        setCurrentBounds(null);
        setSelectionMode(false);
      }
    };

    if (selectionMode) {
      window.addEventListener('keydown', handleKeyDown);
    }
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [selectionMode, setSelectionMode]);

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

        // Validate minimum selection size (10px in both dimensions)
        const startPixel = map.latLngToContainerPoint(startPoint);
        const endPixel = map.latLngToContainerPoint(e.latlng);
        const width = Math.abs(endPixel.x - startPixel.x);
        const height = Math.abs(endPixel.y - startPixel.y);

        if (width >= MIN_SELECTION_SIZE_PX && height >= MIN_SELECTION_SIZE_PX) {
          setSelectedRegion(latLngBoundsToBbox(bounds));
          setSelectionMode(false);
        }

        setStartPoint(null);
        setCurrentBounds(null);
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
