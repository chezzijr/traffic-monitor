import { useMapStore } from '../../store/mapStore';
import { TrafficLightMarker } from './TrafficLightMarker';
import type { TrafficLight } from '../../types';

interface TrafficLightMarkersProps {
    onMarkerClick?: (light: TrafficLight) => void;
}

export function TrafficLightMarkers({ onMarkerClick }: TrafficLightMarkersProps) {
    const trafficLights = useMapStore((state) => state.trafficLights);

    return (
        <>
            {trafficLights.map((light) => (
                <TrafficLightMarker
                    key={light.osm_id}
                    light={light}
                    onClick={onMarkerClick}
                />
            ))}
        </>
    );
}
