import { create } from 'zustand';
import type { BoundingBox, Intersection, TrafficSignal, SUMOTrafficLight } from '../types';
import { mapService, type TlCluster } from '../services/mapService';

interface MapState {
  // State
  intersections: Intersection[];
  trafficSignals: TrafficSignal[];
  selectedRegion: BoundingBox | null;
  currentNetworkId: string | null;
  selectionMode: boolean;
  isLoading: boolean;
  error: string | null;
  selectedJunctionIds: string[];
  sumoTrafficLights: SUMOTrafficLight[];
  osmSumoMapping: Record<string, string>;
  tlClusters: TlCluster[];

  // Actions
  setIntersections: (intersections: Intersection[]) => void;
  setTrafficSignals: (signals: TrafficSignal[]) => void;
  setSelectedRegion: (bbox: BoundingBox | null) => void;
  setCurrentNetworkId: (id: string | null) => void;
  setSelectionMode: (mode: boolean) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
  toggleJunctionSelection: (sumoTlId: string) => void;
  selectAllJunctions: () => void;
  clearJunctionSelection: () => void;
  setSumoTrafficLights: (lights: SUMOTrafficLight[]) => void;
  setOsmSumoMapping: (mapping: Record<string, string>) => void;
  loadTlClusters: (networkId: string) => Promise<void>;
  selectCluster: (clusterId: string) => void;
  reset: () => void;
}

const initialState = {
  intersections: [],
  trafficSignals: [],
  selectedRegion: null,
  currentNetworkId: null,
  selectionMode: false,
  isLoading: false,
  error: null,
  selectedJunctionIds: [] as string[],
  sumoTrafficLights: [] as SUMOTrafficLight[],
  osmSumoMapping: {} as Record<string, string>,
  tlClusters: [] as TlCluster[],
};

export const useMapStore = create<MapState>((set) => ({
  // Initial state
  ...initialState,

  // Actions
  setIntersections: (intersections) => set({ intersections }),
  setTrafficSignals: (signals) => set({ trafficSignals: signals }),
  setSelectedRegion: (bbox) => set({ selectedRegion: bbox }),
  setCurrentNetworkId: (id) => set((state) => ({
    currentNetworkId: id,
    tlClusters: state.currentNetworkId !== id ? [] : state.tlClusters,
  })),
  setSelectionMode: (mode) => set({ selectionMode: mode }),
  setLoading: (loading) => set({ isLoading: loading }),
  setError: (error) => set({ error }),
  toggleJunctionSelection: (sumoTlId) =>
    set((state) => ({
      selectedJunctionIds: state.selectedJunctionIds.includes(sumoTlId)
        ? state.selectedJunctionIds.filter((id) => id !== sumoTlId)
        : [...state.selectedJunctionIds, sumoTlId],
    })),
  selectAllJunctions: () =>
    set((state) => {
      const bbox = state.selectedRegion;
      // TLs with a boundary-reverse-projected coordinate within the user's bbox.
      // Covers both OSM-matched and unmatched SUMO TLs.
      const inside = state.sumoTrafficLights.filter(
        (tl) =>
          tl.lat != null &&
          tl.lon != null &&
          (!bbox ||
            (tl.lat >= bbox.south &&
              tl.lat <= bbox.north &&
              tl.lon >= bbox.west &&
              tl.lon <= bbox.east)),
      );
      return { selectedJunctionIds: inside.map((tl) => tl.id) };
    }),
  clearJunctionSelection: () => set({ selectedJunctionIds: [] }),
  setSumoTrafficLights: (lights) => set({ sumoTrafficLights: lights }),
  setOsmSumoMapping: (mapping) => set({ osmSumoMapping: mapping }),
  loadTlClusters: async (networkId) => {
    try {
      const clusters = await mapService.getTlClusters(networkId);
      // Clip clusters to TLs whose boundary-reverse-projected coordinate falls
      // inside the user's drawn bbox. SUMO .net.xml contains tlLogics beyond
      // the bbox (netconvert emits a buffered network); those shouldn't show
      // up as cluster options because selecting them highlights nothing
      // within the visible rectangle.
      const state = useMapStore.getState();
      const bbox = state.selectedRegion;
      const inBboxTlIds = new Set(
        state.sumoTrafficLights
          .filter(
            (tl) =>
              tl.lat != null &&
              tl.lon != null &&
              (!bbox ||
                (tl.lat >= bbox.south &&
                  tl.lat <= bbox.north &&
                  tl.lon >= bbox.west &&
                  tl.lon <= bbox.east)),
          )
          .map((tl) => tl.id),
      );
      const filtered = clusters
        .map((c) => {
          const tlIds = c.tl_ids.filter((id) => inBboxTlIds.has(id));
          return { ...c, tl_ids: tlIds, size: tlIds.length };
        })
        .filter((c) => c.size >= 1);
      set({ tlClusters: filtered });
    } catch (err) {
      console.error('Failed to load TL clusters', err);
      set({ tlClusters: [] });
    }
  },
  selectCluster: (clusterId) =>
    set((state) => {
      const cluster = state.tlClusters.find((c) => c.cluster_id === clusterId);
      return cluster ? { selectedJunctionIds: [...cluster.tl_ids] } : {};
    }),
  reset: () => set(initialState),
}));
