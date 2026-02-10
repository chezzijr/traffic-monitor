import { useState, useEffect, useCallback, useRef } from 'react';
import toast, { Toaster } from 'react-hot-toast';
import { MapContainer, IntersectionMarkers, RegionSelector, MapLegend } from './components/Map';
import { Sidebar, Header } from './components/Layout';
import { SimulationControl, CameraPanel } from './components/Control';
import { MetricsPanel, SimulationStatusDisplay, MetricsChart } from './components/Dashboard';
import { useMapStore } from './store/mapStore';
import { mapService, simulationService, SimulationSSE } from './services';
import type { SimulationStatus, SimulationMetrics, SSEStepEvent } from './types';

const MAX_HISTORY_POINTS = 500;
const CHART_UPDATE_INTERVAL = 500; // Update chart every 500ms to reduce re-renders

export interface ChartDataPoint {
  step: number;
  vehicles: number;
  waitTime: number;
}

export default function App() {
  const { selectedRegion, intersections, setIntersections, setCurrentNetworkId, setError, setLoading, isLoading, currentNetworkId } = useMapStore();

  // Simulation state
  const [simStatus, setSimStatus] = useState<SimulationStatus>('idle');
  const [step, setStep] = useState(0);
  const [metrics, setMetrics] = useState<SimulationMetrics | null>(null);

  // History stored in ref to avoid re-renders on every SSE event
  // Only chartData state triggers re-renders (throttled)
  const historyRef = useRef<ChartDataPoint[]>([]);
  const [chartData, setChartData] = useState<ChartDataPoint[]>([]);

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

  // Throttled chart update - runs every CHART_UPDATE_INTERVAL ms when simulation is running
  useEffect(() => {
    if (simStatus !== 'running') return;

    const interval = setInterval(() => {
      // Copy history to chartData state (triggers chart re-render)
      setChartData([...historyRef.current]);
    }, CHART_UPDATE_INTERVAL);

    return () => clearInterval(interval);
  }, [simStatus]);

  // Handle SSE step event - O(1) update to ref, no re-render
  const handleSSEStep = useCallback((data: SSEStepEvent) => {
    const point: ChartDataPoint = {
      step: data.step,
      vehicles: data.total_vehicles,
      waitTime: data.average_wait_time,
    };

    // Update history ref without causing re-render
    const history = historyRef.current;
    if (history.length >= MAX_HISTORY_POINTS) {
      history.shift(); // Remove oldest point
    }
    history.push(point);

    // Update step and metrics (these are lightweight, OK to update frequently)
    setStep(data.step);
    setMetrics({
      current_step: data.step,
      total_vehicles: data.total_vehicles,
      average_wait_time: data.average_wait_time,
      throughput: data.throughput ?? data.total_vehicles, // Use actual throughput if available
    });
  }, []);

  // Initialize SSE on mount
  useEffect(() => {
    sseRef.current = new SimulationSSE({
      onStep: handleSSEStep,
      onStopped: () => {
        setSimStatus('stopped');
        // Final chart update when stopped
        setChartData([...historyRef.current]);
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
  }, [handleSSEStep]);

  // Reset simulation state
  const resetSimState = useCallback(() => {
    setStep(0);
    setMetrics(null);
    historyRef.current = [];
    setChartData([]);
  }, []);

  // Simulation control handlers
  const handleStart = useCallback(async (scenario: string) => {
    if (!currentNetworkId) {
      toast.error('No network selected. Please select a region first.');
      return;
    }

    setLoading(true);
    try {
      // Convert to SUMO format and get TL mappings
      const sumoResult = await mapService.convertToSumo(currentNetworkId);

      // Update intersections with SUMO TL IDs for Training panel
      if (sumoResult.osm_sumo_mapping && Object.keys(sumoResult.osm_sumo_mapping).length > 0) {
        const updatedIntersections = intersections.map((intersection) => {
          const sumoTlId = sumoResult.osm_sumo_mapping[intersection.id];
          return sumoTlId ? { ...intersection, sumo_tl_id: sumoTlId } : intersection;
        });
        setIntersections(updatedIntersections);
      }

      // Start simulation with selected scenario
      await simulationService.start(currentNetworkId, scenario);

      // Reset state
      resetSimState();
      setSimStatus('running');

      // Connect to SSE stream
      sseRef.current?.connect(100);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to start simulation');
      setSimStatus('idle');
    } finally {
      setLoading(false);
    }
  }, [currentNetworkId, setLoading, intersections, setIntersections, resetSimState]);

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
      resetSimState();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to stop simulation');
    }
  }, [resetSimState]);

  const handleStep = useCallback(async () => {
    try {
      const stepMetrics = await simulationService.step();
      handleSSEStep({
        step: stepMetrics.step,
        total_vehicles: stepMetrics.total_vehicles,
        total_wait_time: stepMetrics.total_wait_time,
        average_wait_time: stepMetrics.average_wait_time,
      });
      // Update chart immediately for manual steps
      setChartData([...historyRef.current]);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to execute step');
    }
  }, [handleSSEStep]);

  return (
    <div className="h-screen flex flex-col">
      <Toaster position="top-right" />
      <Header />
      <div className="flex-1 flex overflow-hidden">
        <Sidebar simStatus={simStatus}>
          <SimulationControl
            status={simStatus}
            currentStep={step}
            onStart={handleStart}
            onPause={handlePause}
            onResume={handleResume}
            onStop={handleStop}
            onStep={handleStep}
          />
          <SimulationStatusDisplay
            status={simStatus}
            currentStep={step}
            networkId={currentNetworkId}
          />
          <MetricsPanel metrics={metrics} isLoading={isLoading} />
          <MetricsChart data={chartData} />
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
