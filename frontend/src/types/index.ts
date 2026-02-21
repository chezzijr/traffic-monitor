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
  has_traffic_light: boolean;
  sumo_tl_id?: string;
}

// Matches backend NetworkInfo
export interface NetworkInfo {
  network_id: string;
  intersections: Intersection[];
  road_count: number;
  bbox: BoundingBox;
}

// Matches backend NetworkDetail
export interface NetworkDetail {
  network_id: string;
  bbox: BoundingBox;
  created_at: string;
  junctions: { id: string; lat: number; lon: number; tl_id: string | null }[];
  road_count: number;
  name: string | null;
  signalized_junction_count: number;
}

// Matches backend SumoJunction
export interface SumoJunction {
  id: string;
  tl_id: string | null;
  lat: number;
  lon: number;
  junction_type: string;
  incoming_lanes: number;
  name: string | null;
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
  throughput?: number;  // Vehicles that completed their trip
}

export interface SSEStatusEvent {
  step: number;
  final_step?: number;
}

export interface SSEErrorEvent {
  message: string;
}

// Task types for background job tracking
export type TaskStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';

export type TaskType = 'training';

export interface TaskMetrics {
  current_timestep: number;
  total_timesteps: number;
  mean_reward: number;
  episode_count: number;
}

export interface Task {
  task_id: string;
  status: TaskStatus;
  type: TaskType;
  progress: number;
  network_id: string;
  traffic_light_id: string;
  mode?: 'single' | 'all';
  tl_ids?: string[];
  algorithm: 'DQN' | 'PPO';
  total_timesteps: number;
  current_timestep: number;
  mean_reward: number;
  episode_count: number;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  error_message: string | null;
  model_path: string | null;
  avg_waiting_time: number | null;
  avg_queue_length: number | null;
  throughput: number | null;
  baseline_avg_waiting_time: number | null;
  baseline_avg_queue_length: number | null;
  baseline_throughput: number | null;
}

// ML types
export * from './ml';
