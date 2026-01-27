import { useState, useEffect, useCallback, useRef } from 'react';
import toast, { Toaster } from 'react-hot-toast';
import { MapContainer, IntersectionMarkers, RegionSelector, MapLegend } from './components/Map';
import { Sidebar, Header } from './components/Layout';
import { SimulationControl, CameraPanel } from './components/Control';
import { MetricsPanel, SimulationStatusDisplay, MetricsChart } from './components/Dashboard';
import { useMapStore } from './store/mapStore';
import { mapService, simulationService, SimulationSSE } from './services';
import type { SimulationStatus, SimulationMetrics, SSEStepEvent } from './types';

export default function App() {
  const { selectedRegion, setIntersections, setCurrentNetworkId, setError, setLoading, isLoading, currentNetworkId } = useMapStore();

  // Simulation state
  const [simStatus, setSimStatus] = useState<SimulationStatus>('idle');
  const [currentStep, setCurrentStep] = useState(0);
  const [metrics, setMetrics] = useState<SimulationMetrics | null>(null);
  const [metricsHistory, setMetricsHistory] = useState<Array<{step: number; vehicles: number; waitTime: number}>>([])

  // SSE connection ref
  const sseRef = useRef<SimulationSSE | null>(null);

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

  // Initialize SSE on mount
  useEffect(() => {
    sseRef.current = new SimulationSSE({
      onStep: (data: SSEStepEvent) => {
        setCurrentStep(data.step);
        setMetrics({
          current_step: data.step,
          total_vehicles: data.total_vehicles,
          average_wait_time: data.average_wait_time,
          throughput: data.total_vehicles, // Using total_vehicles as throughput proxy
        });
        setMetricsHistory(prev => [
          ...prev,
          {
            step: data.step,
            vehicles: data.total_vehicles,
            waitTime: data.average_wait_time,
          },
        ]);
      },
      onStopped: () => {
        setSimStatus('stopped');
      },
      onError: (data) => {
        toast.error(data.message);
        setSimStatus('paused');
      },
    });

    // Cleanup SSE on unmount
    return () => {
      sseRef.current?.disconnect();
    };
  }, []);

  // Simulation control handlers
  const handleStart = useCallback(async () => {
    if (!currentNetworkId) {
      toast.error('No network selected. Please select a region first.');
      return;
    }

    setLoading(true);
    try {
      // Convert to SUMO format
      await mapService.convertToSumo(currentNetworkId);

      // Start simulation
      await simulationService.start(currentNetworkId);

      // Reset state
      setCurrentStep(0);
      setMetrics(null);
      setMetricsHistory([]);
      setSimStatus('running');

      // Connect to SSE stream
      sseRef.current?.connect(100);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to start simulation');
      setSimStatus('idle');
    } finally {
      setLoading(false);
    }
  }, [currentNetworkId, setLoading]);

  const handlePause = useCallback(async () => {
    try {
      await simulationService.pause();
      setSimStatus('paused');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to pause simulation');
    }
  }, []);

  const handleResume = useCallback(async () => {
    try {
      await simulationService.resume();
      setSimStatus('running');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to resume simulation');
    }
  }, []);

  const handleStop = useCallback(async () => {
    try {
      sseRef.current?.disconnect();
      await simulationService.stop();
      setSimStatus('stopped');
      setMetrics(null);
      setMetricsHistory([]);
      setCurrentStep(0);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to stop simulation');
    }
  }, []);

  const handleStep = useCallback(async () => {
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
      toast.error(err instanceof Error ? err.message : 'Failed to execute step');
    }
  }, []);

  return (
    <div className="h-screen flex flex-col">
      <Toaster position="top-right" />
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
            networkId={currentNetworkId}
          />
          <MetricsPanel metrics={metrics} isLoading={isLoading} />
          <MetricsChart data={metricsHistory} />
          <CameraPanel />
        </Sidebar>
        <main className="flex-1 relative">
          <MapContainer>
            <IntersectionMarkers />
            <RegionSelector />
          </MapContainer>
          <MapLegend className="absolute bottom-4 left-4 z-[1000]" />
          {/* Loading overlay during region extraction */}
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
    </div>
  );
}
