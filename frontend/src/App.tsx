import { useState, useEffect, useCallback } from 'react';
import { MapContainer, IntersectionMarkers, RegionSelector } from './components/Map';
import { Sidebar, Header } from './components/Layout';
import { SimulationControl, CameraPanel } from './components/Control';
import { MetricsPanel, SimulationStatusDisplay, MetricsChart } from './components/Dashboard';
import { useMapStore } from './store/mapStore';
import { mapService } from './services';
import type { SimulationStatus, SimulationMetrics } from './types';

export default function App() {
  const { selectedRegion, setIntersections, setCurrentNetworkId, setError, setLoading, isLoading } = useMapStore();

  // Simulation state
  const [simStatus, setSimStatus] = useState<SimulationStatus>('idle');
  const [currentStep, setCurrentStep] = useState(0);
  const [metrics, setMetrics] = useState<SimulationMetrics | null>(null);
  const [metricsHistory, setMetricsHistory] = useState<Array<{step: number; vehicles: number; waitTime: number}>>([]);

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
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to extract region');
      } finally {
        setLoading(false);
      }
    };

    extractRegion();
  }, [selectedRegion, setIntersections, setCurrentNetworkId, setError, setLoading]);

  // Simulation control handlers (placeholder - will call API)
  const handleStart = useCallback(async () => {
    setSimStatus('running');
    setCurrentStep(0);
  }, []);

  const handlePause = useCallback(async () => {
    setSimStatus('paused');
  }, []);

  const handleResume = useCallback(async () => {
    setSimStatus('running');
  }, []);

  const handleStop = useCallback(async () => {
    setSimStatus('stopped');
    setMetrics(null);
    setMetricsHistory([]);
  }, []);

  const handleStep = useCallback(async () => {
    setCurrentStep(prev => prev + 1);
  }, []);

  return (
    <div className="h-screen flex flex-col">
      <Header />
      <div className="flex-1 flex overflow-hidden">
        <Sidebar>
          <SimulationControl
            status={simStatus}
            currentStep={currentStep}
            onStart={handleStart}
            onPause={handlePause}
            onResume={handleResume}
            onStop={handleStop}
            onStep={handleStep}
          />
          <SimulationStatusDisplay
            status={simStatus}
            currentStep={currentStep}
            networkId={useMapStore.getState().currentNetworkId}
          />
          <MetricsPanel metrics={metrics} isLoading={isLoading} />
          <MetricsChart data={metricsHistory} />
          <CameraPanel />
        </Sidebar>
        <main className="flex-1">
          <MapContainer>
            <IntersectionMarkers />
            <RegionSelector />
          </MapContainer>
        </main>
      </div>
    </div>
  );
}
