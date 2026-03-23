import { useState, useEffect, useCallback, useRef } from 'react';
import toast, { Toaster } from 'react-hot-toast';
import {
  MapContainer,
  RegionSelector,
  MapLegend,
  SelectableIntersectionMarkers,
} from './components/Map';
import { Sidebar, Header, BottomDrawer, RightPanel } from './components/Layout';
import { JunctionSelector, TrainingConfigPanel, ActiveTasksPanel, TrainingProgressPanel } from './components/Training';
import { ModelsPanel, DeploymentsPanel } from './components/Models';
import { useMapStore } from './store/mapStore';
import { useTrainingStore } from './store/trainingStore';
import { useModelStore } from './store/modelStore';
import { mapService } from './services/mapService';
import { modelService } from './services/modelService';
import { TrainingSSE } from './services/sseService';
import type { TrainingProgressEvent, TrainingCompletionEvent } from './types';

export default function App() {
  // Map store — individual selectors to avoid unnecessary re-renders
  const selectedRegion = useMapStore((s) => s.selectedRegion);
  const sumoTrafficLights = useMapStore((s) => s.sumoTrafficLights);
  const isLoading = useMapStore((s) => s.isLoading);
  const setIntersections = useMapStore((s) => s.setIntersections);
  const setCurrentNetworkId = useMapStore((s) => s.setCurrentNetworkId);
  const setError = useMapStore((s) => s.setError);
  const setLoading = useMapStore((s) => s.setLoading);
  const setSumoTrafficLights = useMapStore((s) => s.setSumoTrafficLights);
  const setOsmSumoMapping = useMapStore((s) => s.setOsmSumoMapping);
  // Training store
  const activeTaskId = useTrainingStore((s) => s.activeTaskId);
  const setActiveTaskId = useTrainingStore((s) => s.setActiveTaskId);
  const updateProgress = useTrainingStore((s) => s.updateProgress);
  const completeTask = useTrainingStore((s) => s.completeTask);
  const cancelTask = useTrainingStore((s) => s.cancelTask);

  // Model store
  const isPanelOpen = useModelStore((s) => s.isPanelOpen);
  const togglePanel = useModelStore((s) => s.togglePanel);
  const setModels = useModelStore((s) => s.setModels);
  const deployments = useModelStore((s) => s.deployments);

  // Training progress
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [progressHistory, setProgressHistory] = useState<TrainingProgressEvent[]>([]);

  // SSE ref
  const sseRef = useRef<TrainingSSE | null>(null);

  // Deployed junction IDs for map markers
  const deployedJunctionIds = deployments.map((d) => d.tl_id);

  // Whether SUMO conversion is done (show selectable markers instead of regular ones)
  const hasSumoData = sumoTrafficLights.length > 0;

  // Extract region when selected, then auto-convert to SUMO
  useEffect(() => {
    if (!selectedRegion) return;

    const extractAndConvert = async () => {
      setLoading(true);
      setError(null);
      try {
        // Step 1: Extract region from OSM
        const result = await mapService.extractRegion(selectedRegion);
        setIntersections(result.intersections);
        setCurrentNetworkId(result.network_id);
        toast.success('Region extracted successfully');

        // Step 2: Auto-convert to SUMO
        const sumoResult = await mapService.convertToSumo(result.network_id);
        setSumoTrafficLights(sumoResult.traffic_lights);
        setOsmSumoMapping(sumoResult.osm_sumo_mapping);

        // Update intersections with SUMO TL mapping
        const updatedIntersections = result.intersections.map((inter) => {
          const sumoTlId = sumoResult.osm_sumo_mapping[String(inter.osm_id)];
          if (sumoTlId) {
            return { ...inter, sumo_tl_id: sumoTlId, has_traffic_light: true };
          }
          return inter;
        });
        setIntersections(updatedIntersections);

        toast.success(`SUMO network ready: ${sumoResult.traffic_lights.length} traffic lights`);
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Failed to extract region';
        setError(message);
        toast.error(message);
      } finally {
        setLoading(false);
      }
    };

    extractAndConvert();
  }, [selectedRegion, setIntersections, setCurrentNetworkId, setError, setLoading, setSumoTrafficLights, setOsmSumoMapping]);

  // Connect SSE when a task becomes active
  const connectSSE = useCallback((taskId: string) => {
    // Disconnect previous
    if (sseRef.current) {
      sseRef.current.disconnect();
    }

    const sse = new TrainingSSE();
    sseRef.current = sse;

    setProgressHistory([]);
    setDrawerOpen(true);
    setActiveTaskId(taskId);

    sse.setHandlers({
      onProgress: (data) => {
        updateProgress(taskId, data);
        setProgressHistory((prev) => [...prev, data]);
      },
      onComplete: (data: TrainingCompletionEvent) => {
        completeTask(data.task_id, data);

        // Re-fetch models from API to get full data including results
        // Delay to allow .results.json to flush to disk (especially in Docker volumes)
        setTimeout(() => {
          modelService.listModels().then(setModels).catch((err) => {
            console.error('Failed to refresh models after training:', err);
          });
        }, 500);

        toast.success(`Training complete for task ${data.task_id.slice(0, 8)}`);
      },
      onError: (data) => {
        toast.error(`Training failed: ${data.error}`);
      },
      onCancelled: (data) => {
        cancelTask(data.task_id);
        toast.success('Training cancelled');
      },
    });

    sse.connect(taskId);
  }, [updateProgress, setActiveTaskId, setModels, completeTask, cancelTask]);

  // Handle training started from config panel
  const handleTrainingStarted = useCallback((taskId: string) => {
    connectSSE(taskId);
  }, [connectSSE]);

  // Handle task select from active tasks panel
  const handleTaskSelect = useCallback((taskId: string) => {
    connectSSE(taskId);
  }, [connectSSE]);

  // Cleanup SSE on unmount
  useEffect(() => {
    return () => {
      if (sseRef.current) {
        sseRef.current.disconnect();
      }
    };
  }, []);

  return (
    <div className="h-screen flex flex-col">
      <Toaster position="top-right" />
      <Header />
      <div className="flex-1 flex overflow-hidden">
        <Sidebar>
          {hasSumoData ? (
            <>
              <JunctionSelector />
              <TrainingConfigPanel onTrainingStarted={handleTrainingStarted} />
              <ActiveTasksPanel onTaskSelect={handleTaskSelect} />
            </>
          ) : (
            <div className="text-center py-8 text-sm text-gray-400">
              <p>Select a region on the map to get started.</p>
            </div>
          )}
        </Sidebar>
        <main className="flex-1 relative">
          <MapContainer>
            {hasSumoData && <SelectableIntersectionMarkers deployedJunctionIds={deployedJunctionIds} />}
            <RegionSelector />
          </MapContainer>
          <MapLegend className="absolute bottom-4 left-4 z-[1000]" />

          {/* Bottom drawer for training progress */}
          <BottomDrawer isOpen={drawerOpen && !!activeTaskId} onClose={() => setDrawerOpen(false)}>
            <TrainingProgressPanel progressHistory={progressHistory} />
          </BottomDrawer>

          {/* Loading overlay */}
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

      {/* Right panel for models & deployments */}
      <RightPanel isOpen={isPanelOpen} onClose={togglePanel}>
        <ModelsPanel />
        <DeploymentsPanel />
      </RightPanel>
    </div>
  );
}
