import { create } from 'zustand';
import type { BoundingBox, Intersection, TrafficSignal, LatLng, TrafficLight } from '../types';

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
  reset: () => set(initialState),
}));
