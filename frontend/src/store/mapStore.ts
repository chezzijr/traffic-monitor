import { create } from 'zustand';
import type { BoundingBox, Intersection, SumoJunction } from '../types';

interface MapState {
  // State
  intersections: Intersection[];
  sumoJunctions: SumoJunction[];
  selectedRegion: BoundingBox | null;
  currentNetworkId: string | null;
  selectionMode: boolean;
  isLoading: boolean;
  error: string | null;
  selectedTrafficLightId: string | null;
  manualOverrides: Set<string>;

  // Actions
  setIntersections: (intersections: Intersection[]) => void;
  setSumoJunctions: (junctions: SumoJunction[]) => void;
  setSelectedRegion: (bbox: BoundingBox | null) => void;
  setCurrentNetworkId: (id: string | null) => void;
  setSelectionMode: (mode: boolean) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
  setSelectedTrafficLightId: (id: string | null) => void;
  toggleTrafficLight: (intersectionId: string) => void;
  reset: () => void;
}

const initialState = {
  intersections: [] as Intersection[],
  sumoJunctions: [] as SumoJunction[],
  selectedRegion: null as BoundingBox | null,
  currentNetworkId: null as string | null,
  selectionMode: false,
  isLoading: false,
  error: null as string | null,
  selectedTrafficLightId: null as string | null,
  manualOverrides: new Set<string>(),
};

export const useMapStore = create<MapState>((set) => ({
  // Initial state
  ...initialState,

  // Actions
  setIntersections: (intersections) => set({ intersections }),
  setSumoJunctions: (junctions) => set({ sumoJunctions: junctions }),
  setSelectedRegion: (bbox) => set({ selectedRegion: bbox }),
  setCurrentNetworkId: (id) => set({ currentNetworkId: id }),
  setSelectionMode: (mode) => set({ selectionMode: mode }),
  setLoading: (loading) => set({ isLoading: loading }),
  setError: (error) => set({ error }),
  setSelectedTrafficLightId: (id) => set({ selectedTrafficLightId: id }),
  toggleTrafficLight: (intersectionId) =>
    set((state) => {
      const newManualOverrides = new Set(state.manualOverrides);
      if (newManualOverrides.has(intersectionId)) {
        newManualOverrides.delete(intersectionId);
      } else {
        newManualOverrides.add(intersectionId);
      }

      const newIntersections = state.intersections.map((intersection) =>
        intersection.id === intersectionId
          ? { ...intersection, has_traffic_light: !intersection.has_traffic_light }
          : intersection
      );

      return {
        intersections: newIntersections,
        manualOverrides: newManualOverrides,
      };
    }),
  reset: () =>
    set({
      intersections: [],
      sumoJunctions: [],
      selectedRegion: null,
      currentNetworkId: null,
      selectionMode: false,
      isLoading: false,
      error: null,
      selectedTrafficLightId: null,
      manualOverrides: new Set<string>(),
    }),
}));
