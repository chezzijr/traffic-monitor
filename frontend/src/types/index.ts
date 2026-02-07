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

// Simulation status response from backend
export interface SimulationStatusResponse {
  status: 'idle' | 'running' | 'paused' | 'started' | 'stopped';
  step: number;
  network_id: string | null;
}

// Simulation step metrics from backend
export interface SimulationStepMetrics {
  step: number;
  total_vehicles: number;
  total_wait_time: number;
  average_wait_time: number;
}

// Traffic light information from backend
export interface TrafficLightInfo {
  id: string;
  phase: number;
  program: string;
}

// Legacy types for backwards compatibility
export type SimulationStatus = 'idle' | 'running' | 'paused' | 'stopped';

export interface SimulationMetrics {
  current_step: number;
  total_vehicles: number;
  average_wait_time: number;
  throughput: number;
}

// SSE event types for simulation streaming
export interface SSEStepEvent {
  step: number;
  total_vehicles: number;
  total_wait_time: number;
  average_wait_time: number;
}

export interface SSEStatusEvent {
  step: number;
  final_step?: number;
}

export interface SSEErrorEvent {
  message: string;
}
// Camera snapshot data
export interface CameraSnapshot {
  id: string;
  intersection_id: string;
  timestamp: string;
  snapshot_data: string;
  media_type: string;
  step: number;
}

// Live stream information
export interface CameraStreamInfo {
  intersection_id: string;
  stream_url: string | null;
  is_available: boolean;
  last_snapshot_timestamp: string | null;
}

// Camera response with snapshot and stream
export interface CameraResponse {
  snapshot: CameraSnapshot | null;
  stream: CameraStreamInfo;
  available_snapshots: CameraSnapshot[];
}