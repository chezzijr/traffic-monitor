import { useMapEvents, Marker, Popup } from 'react-leaflet';
import L from 'leaflet';
import { useMapStore } from '../../store/mapStore';

const selectedLocationIcon = L.divIcon({
    className: 'selected-location-marker',
    html: '<div class="w-6 h-6 bg-red-500 rounded-full border-2 border-white shadow-lg flex items-center justify-center"><div class="w-2 h-2 bg-white rounded-full"></div></div>',
    iconSize: [24, 24],
    iconAnchor: [12, 12],
});

export function LocationSelector() {
    const { isSelectingLocation, selectedLocation, setSelectedLocation, setIsSelectingLocation } =
        useMapStore();

    useMapEvents({
        click(e) {
            if (isSelectingLocation) {
                setSelectedLocation({
                    lat: e.latlng.lat,
                    lng: e.latlng.lng,
                });
                setIsSelectingLocation(false);
            }
        },
    });

    // Show marker and popup when location is selected
    if (!selectedLocation) return null;

    return (
        <Marker position={[selectedLocation.lat, selectedLocation.lng]} icon={selectedLocationIcon}>
            <Popup>
                <div className="text-sm">
                    <p className="font-semibold">Selected Location</p>
                    <p className="text-xs text-gray-600">
                        Lat: {selectedLocation.lat.toFixed(6)}
                    </p>
                    <p className="text-xs text-gray-600">
                        Lng: {selectedLocation.lng.toFixed(6)}
                    </p>
                </div>
            </Popup>
        </Marker>
    );
}
