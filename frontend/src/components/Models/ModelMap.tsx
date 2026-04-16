import { useEffect, useState } from 'react';
import { MapContainer, TileLayer, Marker, useMap } from 'react-leaflet';
import { grayIcon, amberIcon } from '../Map/markerIcons';
import type { NetworkMetadata } from '../../types';
import { api } from '../../services/api';

interface ModelMapProps {
  networkId: string;
  trainedJunctionIds: string[];
}

function ResizeHandler() {
  const map = useMap();
  useEffect(() => {
    const timer = setTimeout(() => map.invalidateSize(), 200);
    return () => clearTimeout(timer);
  }, [map]);
  return null;
}

export function ModelMap({ networkId, trainedJunctionIds }: ModelMapProps) {
  const [metadata, setMetadata] = useState<NetworkMetadata | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    api
      .get<NetworkMetadata>('/networks/' + networkId, { signal: controller.signal })
      .then((res) => setMetadata(res.data))
      .catch(() => {
        if (!controller.signal.aborted) setError(true);
      });
    return () => controller.abort();
  }, [networkId]);

  if (error) {
    return (
      <div className="h-36 rounded bg-gray-100 flex items-center justify-center text-xs text-gray-400">
        Map unavailable
      </div>
    );
  }

  if (!metadata) {
    return (
      <div className="h-36 rounded bg-gray-100 flex items-center justify-center text-xs text-gray-400">
        Loading map...
      </div>
    );
  }

  if (metadata.junctions.length === 0) {
    return (
      <div className="h-36 rounded bg-gray-100 flex items-center justify-center text-xs text-gray-400">
        No junction data
      </div>
    );
  }

  const { south, west, north, east } = metadata.bbox;
  const center: [number, number] = [(south + north) / 2, (west + east) / 2];
  const bounds: [[number, number], [number, number]] = [
    [south, west],
    [north, east],
  ];

  return (
    <div>
      <div className="h-48 rounded overflow-hidden leaflet-mini-map">
        <MapContainer
          center={center}
          bounds={bounds}
          zoomControl={true}
          dragging={true}
          scrollWheelZoom={true}
          attributionControl={false}
          style={{ height: '100%', width: '100%' }}
        >
          <TileLayer url="https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png" />
          <ResizeHandler />
          {metadata.junctions.map((junction) => {
            if (!junction.tl_id) return null;
            const icon = trainedJunctionIds.includes(junction.tl_id)
              ? amberIcon
              : grayIcon;
            return (
              <Marker
                key={junction.id}
                position={[junction.lat, junction.lon]}
                icon={icon}
              />
            );
          })}
        </MapContainer>
      </div>
      <div className="flex items-center gap-3 mt-1 px-1">
        <span className="flex items-center gap-1 text-[10px] text-gray-500">
          <span className="inline-block w-2 h-2 rounded-full bg-amber-500"></span>
          Trained
        </span>
        <span className="flex items-center gap-1 text-[10px] text-gray-500">
          <span className="inline-block w-2 h-2 rounded-full bg-gray-400"></span>
          Other
        </span>
      </div>
    </div>
  );
}
