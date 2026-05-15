import { useState, useEffect, useCallback, useRef } from 'react';
// (useRef already imported)
import toast, { Toaster } from 'react-hot-toast';
import {
  MapContainer,
  RegionSelector,
  MapLegend,
  SelectableIntersectionMarkers,
} from './components/Map';
import { CameraModal } from './components/Control';
import { Sidebar, Header, BottomDrawer, RightPanel } from './components/Layout';
import { JunctionSelector, TrainingConfigPanel, ActiveTasksPanel, TrainingProgressPanel } from './components/Training';
import { ModelsPanel, DeploymentsPanel } from './components/Models';
import { useMapStore } from './store/mapStore';
import { useTrainingStore } from './store/trainingStore';
import { useModelStore } from './store/modelStore';
import { mapService } from './services/mapService';
import { modelService } from './services/modelService';
import { deploymentService } from './services/deploymentService';
import { digitalTwinDeployService } from './services/digitalTwinDeployService';
import { TrainingSSE } from './services/sseService';
import type { TrainingProgressEvent, TrainingCompletionEvent, Intersection } from './types';

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
  const setDeployments = useModelStore((s) => s.setDeployments);

  // Training progress
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [progressHistory, setProgressHistory] = useState<TrainingProgressEvent[]>([]);
  const [cameraOpen, setCameraOpen] = useState(false);
  const [activeIntersection, setActiveIntersection] = useState<Intersection | null>(null);

  // SSE ref
  const sseRef = useRef<TrainingSSE | null>(null);

  // Deployed junction IDs for map markers — flatten multi-agent tl_ids
  const deployedJunctionIds = deployments.flatMap((d) =>
    d.tl_ids && d.tl_ids.length > 0 ? d.tl_ids : [d.tl_id],
  );

  // Whether SUMO conversion is done (show selectable markers instead of regular ones)
  const hasSumoData = sumoTrafficLights.length > 0;

  // Poll deployments every 2s so root-map purple markers stay fresh after
  // deploys/swaps initiated from this or any other tab.
  useEffect(() => {
    let cancelled = false;
    const refresh = async () => {
      try {
        const list = await deploymentService.listDeployments();
        if (!cancelled) setDeployments(list);
      } catch {
        /* swallow — polling is best-effort */
      }
    };
    refresh();
    const id = setInterval(refresh, 2000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [setDeployments]);

  // Live TL phase state per deployed junction — same DT snapshot the
  // /simulation/view canvas consumes. Renders inline on the root map so
  // the user can verify the simulation is running without clicking
  // each marker or opening the debug view.
  const [tlStates, setTlStates] = useState<Record<string, { state: string; phase: number }>>({});
  // Per-TL approach metadata from DT (one entry per physical road). Static
  // for a deploy — refreshes only when deploy_id changes.
  const [tlMetadata, setTlMetadata] = useState<Record<string, {
    approaches: Array<{ angle_deg: number; link_indices: number[]; from_edge: string }>;
  }>>({});
  const lastDeployIdRef = useRef<string | null>(null);
  useEffect(() => {
    if (deployments.length === 0) {
      setTlStates({});
      setTlMetadata({});
      lastDeployIdRef.current = null;
      return;
    }
    let cancelled = false;
    const poll = async () => {
      try {
        const snap = await digitalTwinDeployService.getSnapshot();
        if (cancelled) return;
        const ts = snap.tl_state;
        const next: Record<string, { state: string; phase: number }> = {};
        if (ts) {
          if (typeof ts === 'object' && 'tl_id' in ts && typeof (ts as { tl_id?: string }).tl_id === 'string') {
            const single = ts as { tl_id: string; state: string; phase: number };
            next[single.tl_id] = { state: single.state, phase: single.phase };
          } else {
            for (const [tlId, v] of Object.entries(ts as Record<string, { state: string; phase: number }>)) {
              next[tlId] = { state: v.state, phase: v.phase };
            }
          }
        }
        setTlStates(next);

        const snapDeployId = (snap as { deploy_id?: string | null }).deploy_id ?? null;
        const incomingMeta = snap.tl_link_metadata;
        const hasIncomingMeta = !!incomingMeta && Object.keys(incomingMeta).length > 0;

        if (snapDeployId !== lastDeployIdRef.current) {
          // Deploy changed — reset metadata (will be repopulated below if
          // DT has finished computing it).
          lastDeployIdRef.current = snapDeployId;
          setTlMetadata(hasIncomingMeta ? incomingMeta! : {});
        } else if (hasIncomingMeta) {
          // Same deploy, but DT may have just finished computing metadata
          // (it's populated asynchronously in _deploy_loop, ~1-3s after
          // start_deploy returns). Update if our cache is empty or shape
          // differs, otherwise the heuristic-fallback markers stick
          // forever until the user reloads.
          setTlMetadata((prev) => {
            const prevKeys = Object.keys(prev).length;
            const newKeys = Object.keys(incomingMeta!).length;
            if (prevKeys === 0 || prevKeys !== newKeys) return incomingMeta!;
            return prev;
          });
        }
      } catch {
        /* DT transient — keep last known state */
      }
    };
    poll();
    const id = window.setInterval(poll, 1000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
    // Depend on the deploy-ID set, not just count — a swap with same number
    // of deployments (e.g., undeploy A + deploy B same-tick) must restart
    // polling so lastDeployIdRef is re-evaluated against the new DT state.
  }, [deployments.length, deployments.map((d) => d.deploy_id ?? d.tl_id).join(',')]);

  // Auto-seed the map from the deployment's saved network so purple
  // markers render even before the user picks a region. Without this,
  // an opened-fresh `/` shows an empty map after a deploy from
  // another session — the deploy is real (visible in /simulation/view)
  // but the marker overlay has no SUMO data to layer on top of.
  // Skipped once the user actively selects a region (selectedRegion set)
  // so we don't fight their training workflow.
  const currentNetworkId = useMapStore((s) => s.currentNetworkId);
  const intersections = useMapStore((s) => s.intersections);
  useEffect(() => {
    if (deployments.length === 0) return;
    if (selectedRegion) return; // user-driven flow takes precedence
    const deployNetworkId = deployments[0].network_id;
    if (!deployNetworkId) return;
    if (currentNetworkId === deployNetworkId && intersections.length > 0) return;

    let cancelled = false;
    (async () => {
      try {
        const meta = await mapService.getNetworkMetadata(deployNetworkId);
        if (cancelled) return;
        // Synthesize Intersection records from persisted junctions. We
        // only need lat/lon/sumo_tl_id for marker rendering; the heavier
        // OSM fields (num_roads, name) are skipped — the modal pulls
        // them lazily via the camera-feed lookup.
        const interSeed = meta.junctions.map((j) => ({
          id: j.id,
          osm_id: Number.isFinite(Number(j.id)) ? Number(j.id) : 0,
          lat: j.lat,
          lon: j.lon,
          num_roads: 0,
          has_traffic_light: !!j.tl_id,
          sumo_tl_id: j.tl_id,
        }));
        const tlSeed = meta.junctions
          .filter((j) => !!j.tl_id)
          .map((j) => ({
            id: j.tl_id as string,
            type: 'traffic_light',
            program_id: '0',
            num_phases: 0,
            lat: j.lat,
            lon: j.lon,
          }));
        const osmSumoMapping: Record<string, string> = {};
        for (const j of meta.junctions) {
          if (j.tl_id) osmSumoMapping[j.id] = j.tl_id;
        }

        setIntersections(interSeed);
        setSumoTrafficLights(tlSeed);
        setOsmSumoMapping(osmSumoMapping);
        setCurrentNetworkId(deployNetworkId);
      } catch (err) {
        console.warn('Failed to auto-seed deploy network metadata:', err);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [
    deployments,
    selectedRegion,
    currentNetworkId,
    intersections.length,
    setIntersections,
    setSumoTrafficLights,
    setOsmSumoMapping,
    setCurrentNetworkId,
  ]);

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

  // Click on a DEPLOYED (purple) marker opens the live deploy modal.
  // Green/amber clicks toggle training selection only — the marker
  // component does NOT fire this callback for non-deployed clicks.
  const handleDeployedIntersectionClick = useCallback((intersection: Intersection) => {
    setActiveIntersection(intersection);
    setCameraOpen(true);
  }, []);

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
            {hasSumoData && (
              <SelectableIntersectionMarkers
                deployedJunctionIds={deployedJunctionIds}
                tlStates={tlStates}
                tlMetadata={tlMetadata}
                onIntersectionClick={handleDeployedIntersectionClick}
              />
            )}
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

          <CameraModal
            intersection={activeIntersection}
            isOpen={cameraOpen}
            onClose={() => setCameraOpen(false)}
          />
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
