import { Marker, Popup } from 'react-leaflet';
import { purpleIcon } from './markerIcons';
import { buildDeployedIcon } from './deployedMarkerIcon';
import type { Intersection } from '../../types';
import type { TlLinkMetadataMap } from '../../services/digitalTwinDeployService';

interface DeployJunction {
  id: string;
  lat: number;
  lon: number;
  tl_id?: string | null;
}

interface DeployedNetworkMarkersProps {
  /** Junctions of the deployed network (its own coordinates). */
  junctions: DeployJunction[];
  /** TL ids that currently have a model deployed. */
  deployedJunctionIds: string[];
  tlStates?: Record<string, { state: string; phase: number }>;
  tlMetadata?: TlLinkMetadataMap;
  onIntersectionClick?: (intersection: Intersection) => void;
}

/**
 * Always-on purple AI markers for the *deployed* network's controlled
 * junctions. Rendered independently of `mapStore`, so a running deployment
 * stays visible on the map even while the user trains a different network.
 * App.tsx only mounts this when the deploy network differs from the network
 * currently loaded on the map (same-network deploys are drawn by
 * SelectableIntersectionMarkers, which avoids double markers).
 */
export function DeployedNetworkMarkers({
  junctions,
  deployedJunctionIds,
  tlStates = {},
  tlMetadata = {},
  onIntersectionClick,
}: DeployedNetworkMarkersProps) {
  const deployedSet = new Set(deployedJunctionIds);

  return (
    <>
      {junctions
        .filter((j) => !!j.tl_id && deployedSet.has(j.tl_id))
        .map((j) => {
          const tlId = j.tl_id as string;
          const liveState = tlStates[tlId];
          const meta = tlMetadata[tlId];
          const icon = liveState ? buildDeployedIcon(liveState.state, meta) : purpleIcon;
          return (
            <Marker
              key={`deploy-${j.id}`}
              position={[j.lat, j.lon]}
              icon={icon}
              eventHandlers={{
                click: () =>
                  onIntersectionClick?.({
                    id: tlId,
                    osm_id: 0,
                    lat: j.lat,
                    lon: j.lon,
                    name: `Junction ${tlId}`,
                    has_traffic_light: true,
                    sumo_tl_id: tlId,
                  } as Intersection),
              }}
            >
              <Popup>
                <div className="text-sm">
                  <p className="font-semibold">Junction {tlId}</p>
                  <p className="text-xs text-purple-600 font-medium mt-1">
                    AI Model Deployed (other network) — click to view
                  </p>
                </div>
              </Popup>
            </Marker>
          );
        })}
    </>
  );
}
