import { useState, useEffect, useCallback, useRef } from 'react';
import { MapContainer, IntersectionMarkers, RegionSelector } from './components/Map';
import { Sidebar, Header } from './components/Layout';
import { SimulationControl, CameraPanel } from './components/Control';
import { MetricsPanel, SimulationStatusDisplay, MetricsChart } from './components/Dashboard';
import { useMapStore } from './store/mapStore';
import { mapService, simulationService } from './services';
import type { SimulationStatus, SimulationMetrics } from './types';

export default function App() {
  const { selectedRegion, setIntersections, setCurrentNetworkId, setError, setLoading, isLoading, currentNetworkId } = useMapStore();

  // Simulation state
  const [simStatus, setSimStatus] = useState<SimulationStatus>('idle');
  const [currentStep, setCurrentStep] = useState(0);
  const [metrics, setMetrics] = useState<SimulationMetrics | null>(null);
  const [metricsHistory, setMetricsHistory] = useState<Array<{step: number; vehicles: number; waitTime: number}>>([]);
  const [simError, setSimError] = useState<string | null>(null);

  // Polling interval ref
  const pollingIntervalRef = useRef<number | null>(null);

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

  // Stop polling helper
  const stopPolling = useCallback(() => {
    if (pollingIntervalRef.current !== null) {
      clearInterval(pollingIntervalRef.current);
      pollingIntervalRef.current = null;
    }
  }, []);

  // Start polling helper
  const startPolling = useCallback(() => {
    stopPolling(); // Clear any existing interval
    pollingIntervalRef.current = window.setInterval(async () => {
      try {
        const stepMetrics = await simulationService.step();
        setCurrentStep(stepMetrics.step);
        setMetrics({
          current_step: stepMetrics.step,
          total_vehicles: stepMetrics.total_vehicles,
          average_wait_time: stepMetrics.average_wait_time,
          throughput: stepMetrics.total_vehicles, // Using total_vehicles as throughput proxy
        });
        setMetricsHistory(prev => [
          ...prev,
          {
            step: stepMetrics.step,
            vehicles: stepMetrics.total_vehicles,
            waitTime: stepMetrics.average_wait_time,
          },
        ]);
      } catch (err) {
        setSimError(err instanceof Error ? err.message : 'Polling step failed');
        stopPolling();
        setSimStatus('paused');
      }
    }, 100); // 10 steps/second
  }, [stopPolling]);

  // Cleanup polling on unmount
  useEffect(() => {
    return () => {
      stopPolling();
    };
  }, [stopPolling]);

  // Simulation control handlers
  const handleStart = useCallback(async () => {
    if (!currentNetworkId) {
      setSimError('No network selected. Please select a region first.');
      return;
    }

    setSimError(null);
    setLoading(true);
    try {
      // Convert to SUMO format
      await mapService.convertToSumo(currentNetworkId);

      // Start simulation
      await simulationService.start(currentNetworkId);

      // Fetch traffic lights (optional, for future use)
      await simulationService.getTrafficLights();

      // Reset state
      setCurrentStep(0);
      setMetrics(null);
      setMetricsHistory([]);
      setSimStatus('running');

      // Start polling loop
      startPolling();
    } catch (err) {
      setSimError(err instanceof Error ? err.message : 'Failed to start simulation');
      setSimStatus('idle');
    } finally {
      setLoading(false);
    }
  }, [currentNetworkId, setLoading, startPolling]);

  const handlePause = useCallback(async () => {
    setSimError(null);
    try {
      stopPolling();
      await simulationService.pause();
      setSimStatus('paused');
    } catch (err) {
      setSimError(err instanceof Error ? err.message : 'Failed to pause simulation');
    }
  }, [stopPolling]);

  const handleResume = useCallback(async () => {
    setSimError(null);
    try {
      await simulationService.resume();
      setSimStatus('running');
      startPolling();
    } catch (err) {
      setSimError(err instanceof Error ? err.message : 'Failed to resume simulation');
    }
  }, [startPolling]);

  const handleStop = useCallback(async () => {
    setSimError(null);
    try {
      stopPolling();
      await simulationService.stop();
      setSimStatus('stopped');
      setMetrics(null);
      setMetricsHistory([]);
      setCurrentStep(0);
    } catch (err) {
      setSimError(err instanceof Error ? err.message : 'Failed to stop simulation');
    }
  }, [stopPolling]);

  const handleStep = useCallback(async () => {
    setSimError(null);
    try {
      const stepMetrics = await simulationService.step();
      setCurrentStep(stepMetrics.step);
      setMetrics({
        current_step: stepMetrics.step,
        total_vehicles: stepMetrics.total_vehicles,
        average_wait_time: stepMetrics.average_wait_time,
        throughput: stepMetrics.total_vehicles,
      });
      setMetricsHistory(prev => [
        ...prev,
        {
          step: stepMetrics.step,
          vehicles: stepMetrics.total_vehicles,
          waitTime: stepMetrics.average_wait_time,
        },
      ]);
    } catch (err) {
      setSimError(err instanceof Error ? err.message : 'Failed to execute step');
    }
  }, []);

  return (
    <div className="h-screen flex flex-col">
      <Header />
      <div className="flex-1 flex overflow-hidden">
        <Sidebar>
          {/* Error banner */}
          {simError && (
            <div className="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded relative mb-4" role="alert">
              <strong className="font-bold">Error: </strong>
              <span className="block sm:inline">{simError}</span>
              <button
                className="absolute top-0 bottom-0 right-0 px-4 py-3"
                onClick={() => setSimError(null)}
                aria-label="Dismiss error"
              >
                <span className="text-red-500 text-xl">&times;</span>
              </button>
            </div>
          )}
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
