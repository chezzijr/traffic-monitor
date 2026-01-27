// TypeScript interfaces matching backend schemas

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

// Simulation state
export type SimulationStatus = 'idle' | 'running' | 'paused' | 'stopped';

export interface SimulationMetrics {
  current_step: number;
  total_vehicles: number;
  average_wait_time: number;
  throughput: number;
}
