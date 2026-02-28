import { useState, useEffect, useCallback } from 'react';
import toast, { Toaster } from 'react-hot-toast';
import { MapContainer, IntersectionMarkers, TrafficLightMarkers, LocationSelector, RegionSelector, MapLegend } from './components/Map';
import { Sidebar, Header } from './components/Layout';
import { CameraPanel, CameraModal, TrafficLightSearch } from './components/Control';
import { useMapStore } from './store/mapStore';
import { mapService } from './services';
import type { Intersection, TrafficLight } from './types';

export default function App() {
  const { selectedRegion, setIntersections, setCurrentNetworkId, setError, setLoading, isLoading } = useMapStore();

  // Camera modal state
  const [selectedIntersection, setSelectedIntersection] = useState<Intersection | null>(null);
  const [cameraModalOpen, setCameraModalOpen] = useState(false);

  // All traffic lights in HCM City
  const setTrafficLights = useMapStore((state) => state.setTrafficLights);

  // Handle marker click
  const handleMarkerClick = useCallback((intersection: Intersection) => {
    setSelectedIntersection(intersection);
    setCameraModalOpen(true);
  }, []);

  // Handle traffic light marker click - convert to Intersection format
  const handleTrafficLightClick = useCallback((light: TrafficLight) => {
    const intersection: Intersection = {
      id: `osm_${light.osm_id}`,
      osm_id: light.osm_id,
      lat: light.lat,
      lon: light.lon,
      name: `OSM Traffic Light ${light.osm_id}`,
      num_roads: 0,
      has_traffic_light: true,
      sumo_tl_id: undefined,
      trafficLight: light,
    };
    setSelectedIntersection(intersection);
    setCameraModalOpen(true);
  }, []);

  // Load all traffic lights in HCM City
  useEffect(() => {
    async function loadAllTrafficLights() {
      try {
        const lights = await mapService.getAllTrafficLights();
        setTrafficLights(lights);
      } catch (err) {
        console.error('failed to load all traffic lights', err);
      }
    }
    loadAllTrafficLights();
  }, []);

  // Extract region when selected
  useEffect(() => {
    if (!selectedRegion) return;

    const extractRegion = async () => {
      setLoading(true);
      setError(null);
      try {
        const result = await mapService.extractRegion(selectedRegion);
        setIntersections(result.intersections);
        setCurrentNetworkId(result.network_id);
        toast.success('Region extracted successfully');
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Failed to extract region';
        setError(message);
        toast.error(message);
      } finally {
        setLoading(false);
      }
    };

    extractRegion();
  }, [selectedRegion, setIntersections, setCurrentNetworkId, setError, setLoading]);

  return (
    <div className="h-screen flex flex-col">
      <Toaster position="top-right" />
      <Header />
      <div className="flex-1 flex overflow-hidden">
        <Sidebar>
          <TrafficLightSearch />
          <CameraPanel />
        </Sidebar>
        <main className="flex-1 relative">
          <MapContainer>
            <IntersectionMarkers onMarkerClick={handleMarkerClick} />
            <TrafficLightMarkers onMarkerClick={handleTrafficLightClick} />
            <LocationSelector />
            <RegionSelector />
          </MapContainer>
          <MapLegend className="absolute bottom-4 left-4 z-[1000]" />
          {isLoading && (
            <div className="absolute inset-0 bg-black/50 flex items-center justify-center z-[2000]">
              <div className="bg-white rounded-lg p-6 shadow-xl flex flex-col items-center gap-3">
                <div className="w-10 h-10 border-4 border-blue-500 border-t-transparent rounded-full animate-spin" />
                <p className="text-gray-700 font-medium">Extracting road network...</p>
                <p className="text-gray-500 text-sm">This may take 30-60 seconds</p>
              </div>
            </div>
          )}
        </main>
      </div>
      <CameraModal
        intersection={selectedIntersection}
        isOpen={cameraModalOpen}
        onClose={() => setCameraModalOpen(false)}
      />
    </div>
  );
}
