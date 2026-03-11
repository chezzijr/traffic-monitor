import { create } from 'zustand';
import type { BoundingBox, Intersection, TrafficSignal, LatLng, TrafficLight, SUMOTrafficLight } from '../types';

interface MapState {
  // State
  intersections: Intersection[];
  trafficSignals: TrafficSignal[];
  trafficLights: TrafficLight[];
  selectedLocation: LatLng | null;
  isSelectingLocation: boolean;
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
  setTrafficLights: (lights: TrafficLight[]) => void;
  setSelectedLocation: (location: LatLng | null) => void;
  setIsSelectingLocation: (selecting: boolean) => void;
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
  trafficLights: [],
  selectedLocation: null,
  isSelectingLocation: false,
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
  setTrafficLights: (lights) => set({ trafficLights: lights }),
  setSelectedLocation: (location) => set({ selectedLocation: location }),
  setIsSelectingLocation: (selecting) => set({ isSelectingLocation: selecting }),
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
    set((state) => ({
      selectedJunctionIds: state.sumoTrafficLights.map((tl) => tl.id),
    })),
  clearJunctionSelection: () => set({ selectedJunctionIds: [] }),
  setSumoTrafficLights: (lights) => set({ sumoTrafficLights: lights }),
  setOsmSumoMapping: (mapping) => set({ osmSumoMapping: mapping }),
  reset: () => set(initialState),
}));
