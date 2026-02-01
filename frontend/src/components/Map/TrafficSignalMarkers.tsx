import { useMapStore } from '../../store/mapStore';
import { TrafficSignalMarker } from './TrafficSignalMarker';

export function TrafficSignalMarkers() {
    const trafficSignals = useMapStore((state) => state.trafficSignals);

    return (
        <>
            {trafficSignals.map((signal) => (
                <TrafficSignalMarker key={signal.osm_id} signal={signal} />
            ))}
        </>
    );
}
