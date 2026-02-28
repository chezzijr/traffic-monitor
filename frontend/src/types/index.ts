// TypeScript interfaces matching backend schemas

// Coordinates
export interface LatLng {
  lat: number;
  lng: number;
}

// Matches backend BoundingBox
export interface BoundingBox {
  south: number;
  west: number;
  north: number;
  east: number;
}

// Matches backend Intersection
export interface Intersection {
  id: string;
  lat: number;
  lon: number;
  name?: string;
  num_roads: number;
  has_traffic_light: boolean;
  sumo_tl_id?: string;
  trafficLight?: TrafficLight;
}

// OSM traffic signal
export interface TrafficSignal {
  osm_id: number;
  lat: number;
  lon: number;
}

// OSM traffic light (preferred name)
export interface TrafficLight {
  osm_id: number;
  lat: number;
  lon: number;
}

// Matches backend NetworkInfo
export interface NetworkInfo {
  network_id: string;
  intersections: Intersection[];
  road_count: number;
  bbox: BoundingBox;
}

// Traffic light state
export type TrafficLightPhase = 'red' | 'yellow' | 'green';

export interface TrafficLightState {
  intersection_id: string;
  current_phase: TrafficLightPhase;
  remaining_time: number;
}

// Traffic light information from backend
export interface TrafficLightInfo {
  id: string;
  phase: number;
  program: string;
}

export interface DirectionFrame {
  direction: string;
  image: string | null;
}

export interface IntersectionFrames {
  intersection_id?: string | number;
  roads?: string[];
  frames: DirectionFrame[];
}
