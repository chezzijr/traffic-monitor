import { Rectangle, Tooltip } from 'react-leaflet';
import type { LatLngBoundsExpression } from 'leaflet';
import { useNetworkStore } from '../../store/networkStore';
import { useMapStore } from '../../store/mapStore';
import type { BoundingBox } from '../../types';

function bboxToBounds(bbox: BoundingBox): LatLngBoundsExpression {
  return [
    [bbox.south, bbox.west],
    [bbox.north, bbox.east],
  ];
}

export function NetworkBoundary() {
  const { networks, activeNetworkId } = useNetworkStore();
  const { selectedRegion } = useMapStore();

  const activeNetwork = activeNetworkId
    ? networks.find((n) => n.network_id === activeNetworkId)
    : undefined;

  const bbox = activeNetwork?.bbox ?? selectedRegion;

  if (!bbox) return null;

  const bounds = bboxToBounds(bbox);

  return (
    <Rectangle
      bounds={bounds}
      pathOptions={{
        color: '#3B82F6',
        weight: 2,
        dashArray: '8 4',
        fillOpacity: 0.05,
      }}
      interactive={!!activeNetwork}
    >
      {activeNetwork && (
        <Tooltip sticky>
          <div className="text-xs">
            <div className="font-semibold">
              Network: {activeNetwork.network_id.slice(0, 8)}
            </div>
            <div>Junctions: {activeNetwork.junctions.length}</div>
            <div>Roads: {activeNetwork.road_count}</div>
          </div>
        </Tooltip>
      )}
    </Rectangle>
  );
}
