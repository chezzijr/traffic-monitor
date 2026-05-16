import { Marker, Popup } from 'react-leaflet';
import { useMapStore } from '../../store/mapStore';
import { grayIcon, greenIcon, amberIcon, purpleIcon } from './markerIcons';
import { buildDeployedIcon } from './deployedMarkerIcon';
import type { Intersection } from '../../types';
import type { TlLinkMetadataMap } from '../../services/digitalTwinDeployService';

interface SelectableIntersectionMarkersProps {
  deployedJunctionIds?: string[];
  /** Live SUMO TL state per controlled junction from DT snapshot — same
   *  data the /simulation/view canvas uses. Renders inline bulbs around
   *  the purple marker so the user can verify the simulation is running
   *  without opening the debug view. */
  tlStates?: Record<string, { state: string; phase: number }>;
  /** Per-TL approach metadata from SUMO net topology — 1 entry per
   *  physical incoming road, with compass angle + which state-string
   *  indices belong to it. When present, bulbs render at correct
   *  geographic positions; otherwise we fall back to length-heuristics. */
  tlMetadata?: TlLinkMetadataMap;
  /** Whether non-deployed TL markers are selectable for training. False in a
   *  deploy-only context — only the deployed (purple) junctions are drawn at
   *  all; the plain network junctions are hidden to keep the deploy view clean. */
  selectable?: boolean;
  onIntersectionClick?: (intersection: Intersection) => void;
}

// Special clickable intersection: Tran Binh Trong x Tran Hung Dao.
const THD_TBT_LAT = 10.755388;
const THD_TBT_LON = 106.681386;
const COORD_TOLERANCE = 0.002;

const isTHDTBTIntersection = (intersection: Intersection): boolean =>
  Math.abs(intersection.lat - THD_TBT_LAT) < COORD_TOLERANCE &&
  Math.abs(intersection.lon - THD_TBT_LON) < COORD_TOLERANCE;

export function SelectableIntersectionMarkers({ deployedJunctionIds = [], tlStates = {}, tlMetadata = {}, selectable = true, onIntersectionClick }: SelectableIntersectionMarkersProps) {
  const intersections = useMapStore((s) => s.intersections);
  const sumoTrafficLights = useMapStore((s) => s.sumoTrafficLights);
  const selectedRegion = useMapStore((s) => s.selectedRegion);
  const selectedJunctionIds = useMapStore((s) => s.selectedJunctionIds);
  const toggleJunctionSelection = useMapStore((s) => s.toggleJunctionSelection);

  // SUMO TLs without OSM matches still get rendered from their boundary-
  // reverse-projected lat/lon — scoped to the user's bbox so tlLogics leaked
  // by netconvert's buffer don't clutter the map.
  const osmMatchedTlIds = new Set(
    intersections.map((i) => i.sumo_tl_id).filter(Boolean) as string[],
  );
  const unmatchedSumoTls = sumoTrafficLights.filter(
    (tl) =>
      tl.lat != null &&
      tl.lon != null &&
      !osmMatchedTlIds.has(tl.id) &&
      (!selectedRegion ||
        (tl.lat >= selectedRegion.south &&
          tl.lat <= selectedRegion.north &&
          tl.lon >= selectedRegion.west &&
          tl.lon <= selectedRegion.east)),
  );

  return (
    <>
      {intersections.map((intersection) => {
        const sumoTlId = intersection.sumo_tl_id;
        const hasTL = intersection.has_traffic_light && sumoTlId;

        if (!hasTL) {
          // Deploy-only view (not selectable): hide plain network junctions —
          // only deployed junctions are relevant there.
          if (!selectable) return null;
          const isSpecialIntersection = isTHDTBTIntersection(intersection);

          return (
            <Marker
              key={intersection.id}
              position={[intersection.lat, intersection.lon]}
              icon={grayIcon}
              eventHandlers={
                isSpecialIntersection
                  ? {
                      click: () => onIntersectionClick?.(intersection),
                    }
                  : undefined
              }
            />
          );
        }

        const isDeployed = deployedJunctionIds.includes(sumoTlId);
        const isSelected = selectable && selectedJunctionIds.includes(sumoTlId);
        // Deploy-only view: render only the deployed (purple) junctions.
        if (!selectable && !isDeployed) return null;
        const liveState = isDeployed ? tlStates[sumoTlId] : undefined;
        const meta = isDeployed ? tlMetadata[sumoTlId] : undefined;
        const icon = isDeployed
          ? (liveState ? buildDeployedIcon(liveState.state, meta, isSelected) : purpleIcon)
          : isSelected ? amberIcon : greenIcon;

        return (
          <Marker
            key={intersection.id}
            position={[intersection.lat, intersection.lon]}
            icon={icon}
            eventHandlers={{
              click: () => {
                // Deployed (purple): open live deploy modal, do NOT toggle training.
                // Non-deployed (green/amber): toggle training selection only when
                // selectable (i.e. user is in a training context).
                if (isDeployed) {
                  onIntersectionClick?.(intersection);
                } else if (selectable) {
                  toggleJunctionSelection(sumoTlId);
                }
              },
            }}
          >
            <Popup>
              <div className="text-sm">
                <p className="font-semibold">
                  {intersection.name || `Junction ${sumoTlId}`}
                </p>
                <p className="text-xs text-gray-600">SUMO TL: {sumoTlId}</p>
                <p className="text-xs text-gray-500">
                  {intersection.lat.toFixed(6)}, {intersection.lon.toFixed(6)}
                </p>
                {isSelected && (
                  <p className="text-xs text-amber-600 font-medium mt-1">Selected for training</p>
                )}
                {isDeployed && (
                  <p className="text-xs text-purple-600 font-medium mt-1">AI Model Deployed — click to view</p>
                )}
              </div>
            </Popup>
          </Marker>
        );
      })}
      {unmatchedSumoTls.map((tl) => {
        const isDeployed = deployedJunctionIds.includes(tl.id);
        const isSelected = selectable && selectedJunctionIds.includes(tl.id);
        // Deploy-only view: render only the deployed (purple) junctions.
        if (!selectable && !isDeployed) return null;
        const liveState = isDeployed ? tlStates[tl.id] : undefined;
        const meta = isDeployed ? tlMetadata[tl.id] : undefined;
        const icon = isDeployed
          ? (liveState ? buildDeployedIcon(liveState.state, meta, isSelected) : purpleIcon)
          : isSelected ? amberIcon : greenIcon;
        return (
          <Marker
            key={`sumo-${tl.id}`}
            position={[tl.lat as number, tl.lon as number]}
            icon={icon}
            eventHandlers={{
              click: () => {
                // No OSM intersection to pass — for deployed unmatched TLs we
                // still synthesize a minimal Intersection for the modal so the
                // user can see live deploy state.
                if (isDeployed) {
                  onIntersectionClick?.({
                    id: tl.id,
                    osm_id: 0,
                    lat: tl.lat as number,
                    lon: tl.lon as number,
                    name: `Junction ${tl.id}`,
                    has_traffic_light: true,
                    sumo_tl_id: tl.id,
                  } as Intersection);
                } else if (selectable) {
                  toggleJunctionSelection(tl.id);
                }
              },
            }}
          >
            <Popup>
              <div className="text-sm">
                <p className="font-semibold">Junction {tl.id}</p>
                <p className="text-xs text-gray-600">SUMO TL: {tl.id}</p>
                <p className="text-xs text-gray-400 italic">No OSM match</p>
                {isSelected && (
                  <p className="text-xs text-amber-600 font-medium mt-1">Selected for training</p>
                )}
              </div>
            </Popup>
          </Marker>
        );
      })}
    </>
  );
}
