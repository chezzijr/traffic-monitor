import { useState, useEffect, useCallback, useRef } from 'react';
// (useRef already imported)
import toast, { Toaster } from 'react-hot-toast';
import {
  MapContainer,
  RegionSelector,
  MapLegend,
  SelectableIntersectionMarkers,
} from './components/Map';
import { DeployedNetworkMarkers } from './components/Map/DeployedNetworkMarkers';
import { CameraModal } from './components/Control';
import { Sidebar, Header, BottomDrawer, RightPanel } from './components/Layout';
import { ActivityStatusBar } from './components/Layout/ActivityStatusBar';
import { JunctionSelector, TrainingConfigPanel, ActiveTasksPanel, TrainingProgressPanel } from './components/Training';
import { ModelsPanel, DeploymentsPanel } from './components/Models';
import { useMapStore } from './store/mapStore';
import { useTrainingStore } from './store/trainingStore';
import { useModelStore } from './store/modelStore';
import { mapService } from './services/mapService';
import { modelService } from './services/modelService';
import { deploymentService } from './services/deploymentService';
import { taskService } from './services/taskService';
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
  const setNetworkSource = useMapStore((s) => s.setNetworkSource);
  const networkSource = useMapStore((s) => s.networkSource);
  const reset = useMapStore((s) => s.reset);
  // Training store
  const activeTaskId = useTrainingStore((s) => s.activeTaskId);
  const setActiveTaskId = useTrainingStore((s) => s.setActiveTaskId);
  const updateProgress = useTrainingStore((s) => s.updateProgress);
  const completeTask = useTrainingStore((s) => s.completeTask);
  const failTask = useTrainingStore((s) => s.failTask);
  const cancelTask = useTrainingStore((s) => s.cancelTask);
  const setTasks = useTrainingStore((s) => s.setTasks);

  // Model store
  const isPanelOpen = useModelStore((s) => s.isPanelOpen);
  const togglePanel = useModelStore((s) => s.togglePanel);
  const setModels = useModelStore((s) => s.setModels);
  const deployments = useModelStore((s) => s.deployments);
  const setDeployments = useModelStore((s) => s.setDeployments);
  const isDeploying = useModelStore((s) => s.isDeploying);

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
  const deployNetworkId = deployments[0]?.network_id ?? null;

  // Whether SUMO conversion is done (show selectable markers instead of regular ones)
  const hasSumoData = sumoTrafficLights.length > 0;

  // Deploy network's junction coordinates — fetched independently of the
  // training network so the deployed (purple) markers stay on the map even
  // when the user is training a different network.
  const [deployJunctions, setDeployJunctions] = useState<
    { id: string; lat: number; lon: number; tl_id?: string | null }[]
  >([]);

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

  // Poll the backend task list every 3s so a training run is visible on any
  // client — a different machine on the LAN or this tab after a reload. Local
  // trainingStore.tasks alone only knows runs started in *this* browser.
  useEffect(() => {
    let cancelled = false;
    const refresh = async () => {
      try {
        const backend = await taskService.listTasks();
        if (cancelled) return;
        const local = useTrainingStore.getState().tasks;
        const backendById = new Map(backend.map((t) => [t.task_id, t]));
        const localIds = new Set(local.map((t) => t.task_id));
        // Refresh known tasks from the backend's source-of-truth status/
        // progress so a run that finished elsewhere flips terminal here too.
        const merged = local.map((t) => {
          const bt = backendById.get(t.task_id);
          if (!bt) return t;
          // A locally-terminal task — the SSE flow already wrote completed/
          // failed here — must not be downgraded by a staler backend record.
          // Local terminal state wins; the poll only promotes, never demotes.
          if (t.status === 'completed' || t.status === 'failed') return t;
          return {
            ...t,
            status: bt.status,
            // Progress is monotonic and the SSE flow updates it faster than
            // this 3s poll, so never let a lagging backend value move the
            // bar backward.
            progress: Math.max(t.progress ?? 0, bt.progress ?? 0),
            error: bt.error ?? t.error,
            model_path: bt.model_path ?? t.model_path,
          };
        });
        // Add running tasks started on another machine. Only `running` ones —
        // the backend's tasks:list is never pruned, so importing every entry
        // would dump the whole completed/failed history into the panel. A
        // local-only `queued` task is left as-is (not yet in the backend list).
        for (const bt of backend) {
          if (bt.status === 'running' && !localIds.has(bt.task_id)) {
            merged.unshift(bt);
          }
        }
        setTasks(merged);
      } catch {
        /* swallow — polling is best-effort */
      }
    };
    refresh();
    const id = setInterval(refresh, 3000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [setTasks]);

  // Load the deploy network's junction coords (once per deploy network) so the
  // always-on deployed-marker overlay can render regardless of which network
  // is currently on the map.
  useEffect(() => {
    if (!deployNetworkId) {
      setDeployJunctions([]);
      return;
    }
    let cancelled = false;
    mapService
      .getNetworkMetadata(deployNetworkId)
      .then((meta) => {
        if (cancelled) return;
        setDeployJunctions(
          (meta.junctions ?? [])
            .filter((j) => !!j.tl_id)
            .map((j) => ({ id: j.id, lat: j.lat, lon: j.lon, tl_id: j.tl_id })),
        );
      })
      .catch(() => {
        /* transient — overlay just stays empty */
      });
    return () => {
      cancelled = true;
    };
  }, [deployNetworkId]);

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
        // Marker-display only — must NOT enable the training panel.
        setNetworkSource('deploy');
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
    setNetworkSource,
  ]);

  // After a deploy is stopped (from any path — Stop All, per-TL undeploy, or a
  // stop issued from another view), the deployment list empties. If the map is
  // only showing a deploy-seeded network, wipe it so the page returns to a
  // clean fresh-start state instead of stranding a stale network + markers.
  // Skipped while a deploy/swap is in flight (`isDeploying`) — the backend
  // clears Redis between stop and start, so the list briefly empties mid-swap.
  // Also debounced as defense-in-depth for stops issued outside this page.
  useEffect(() => {
    if (deployments.length === 0 && networkSource === 'deploy' && !isDeploying) {
      const t = setTimeout(() => reset(), 5000);
      return () => clearTimeout(t);
    }
  }, [deployments.length, networkSource, isDeploying, reset]);

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
        setNetworkSource('training');
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
  }, [selectedRegion, setIntersections, setCurrentNetworkId, setError, setLoading, setSumoTrafficLights, setOsmSumoMapping, setNetworkSource]);

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
        // Mark the task failed so it stops latching the running/queued
        // guards (Sidebar confirm, activity status bar).
        failTask(taskId);
      },
      onCancelled: (data) => {
        cancelTask(data.task_id);
        toast.success('Training cancelled');
      },
    });

    sse.connect(taskId);
  }, [updateProgress, setActiveTaskId, setModels, completeTask, failTask, cancelTask]);

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
      <ActivityStatusBar onViewTraining={connectSSE} />
      <div className="flex-1 flex overflow-hidden">
        <Sidebar>
          {hasSumoData && networkSource === 'training' ? (
            <>
              <JunctionSelector />
              <TrainingConfigPanel onTrainingStarted={handleTrainingStarted} />
              <ActiveTasksPanel onTaskSelect={handleTaskSelect} />
            </>
          ) : networkSource === 'deploy' ? (
            <div className="text-center py-8 text-sm text-gray-400">
              <p>A model is deployed.</p>
              <p className="text-xs mt-1 mb-3">Manage or stop it in the Models panel.</p>
              {!isPanelOpen && (
                <button
                  onClick={togglePanel}
                  className="text-xs px-3 py-1.5 rounded bg-blue-500 text-white hover:bg-blue-600 transition-colors"
                >
                  Open Models panel
                </button>
              )}
            </div>
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
                selectable={networkSource === 'training'}
                onIntersectionClick={handleDeployedIntersectionClick}
              />
            )}
            {/* Always-on overlay: deployed junctions of a *different* network
                than the one on the map (same-network deploys are already drawn
                by SelectableIntersectionMarkers above). */}
            {deployNetworkId && deployNetworkId !== currentNetworkId && (
              <DeployedNetworkMarkers
                junctions={deployJunctions}
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
