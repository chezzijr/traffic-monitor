import { create } from 'zustand';
import type { BoundingBox, Intersection, TrafficSignal, SUMOTrafficLight } from '../types';

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
};

export const useMapStore = create<MapState>((set) => ({
  // Initial state
  ...initialState,

  // Actions
  setIntersections: (intersections) => set({ intersections }),
  setTrafficSignals: (signals) => set({ trafficSignals: signals }),
  setSelectedRegion: (bbox) => set({ selectedRegion: bbox }),
  setCurrentNetworkId: (id) => set({ currentNetworkId: id }),
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
      if (!bbox) {
        return { selectedJunctionIds: state.sumoTrafficLights.map((tl) => tl.id) };
      }
      const insideTlIds = new Set(
        state.intersections
          .filter(
            (i) =>
              i.sumo_tl_id &&
              i.lat >= bbox.south &&
              i.lat <= bbox.north &&
              i.lon >= bbox.west &&
              i.lon <= bbox.east,
          )
          .map((i) => i.sumo_tl_id as string),
      );
      return {
        selectedJunctionIds: state.sumoTrafficLights
          .map((tl) => tl.id)
          .filter((id) => insideTlIds.has(id)),
      };
    }),
  clearJunctionSelection: () => set({ selectedJunctionIds: [] }),
  setSumoTrafficLights: (lights) => set({ sumoTrafficLights: lights }),
  setOsmSumoMapping: (mapping) => set({ osmSumoMapping: mapping }),
  reset: () => set(initialState),
}));
