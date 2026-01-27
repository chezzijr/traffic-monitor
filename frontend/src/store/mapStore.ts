import { create } from 'zustand';
import type { BoundingBox, Intersection } from '../types';

interface MapState {
  // State
  intersections: Intersection[];
  selectedRegion: BoundingBox | null;
  currentNetworkId: string | null;
  selectionMode: boolean;
  isLoading: boolean;
  error: string | null;

  // Actions
  setIntersections: (intersections: Intersection[]) => void;
  setSelectedRegion: (bbox: BoundingBox | null) => void;
  setCurrentNetworkId: (id: string | null) => void;
  setSelectionMode: (mode: boolean) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
  reset: () => void;
}

const initialState = {
  intersections: [],
  selectedRegion: null,
  currentNetworkId: null,
  selectionMode: false,
  isLoading: false,
  error: null,
};

export const useMapStore = create<MapState>((set) => ({
  // Initial state
  ...initialState,

  // Actions
  setIntersections: (intersections) => set({ intersections }),
  setSelectedRegion: (bbox) => set({ selectedRegion: bbox }),
  setCurrentNetworkId: (id) => set({ currentNetworkId: id }),
  setSelectionMode: (mode) => set({ selectionMode: mode }),
  setLoading: (loading) => set({ isLoading: loading }),
  setError: (error) => set({ error }),
  reset: () => set(initialState),
}));
