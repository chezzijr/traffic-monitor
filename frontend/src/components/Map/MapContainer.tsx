import { MapContainer as LeafletMapContainer, TileLayer } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';

// HCMC center coordinates
const HCMC_CENTER: [number, number] = [10.8231, 106.6297];
const DEFAULT_ZOOM = 13;

interface MapContainerProps {
  children?: React.ReactNode;
}

export function MapContainer({ children }: MapContainerProps) {
  return (
    <LeafletMapContainer
      center={HCMC_CENTER}
      zoom={DEFAULT_ZOOM}
      className="h-full w-full"
    >
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      {children}
    </LeafletMapContainer>
  );
}
