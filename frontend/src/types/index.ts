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
  osm_id: number;
  lat: number;
  lon: number;
  name?: string;
  num_roads: number;
  has_traffic_light: boolean;
  sumo_tl_id?: string;
  roads?: string[];
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

// Mock traffic light snapshot (frontend-only, for UI demo)
export type MockSignalColor = "red" | "yellow" | "green";

export interface MockDirectionSnapshot {
  id: string; // e.g. 'north', 'south', 'east', 'west'
  roadName: string;
  color: MockSignalColor;
  remaining: number; // seconds remaining for this phase
  queue: number; // number of waiting vehicles
}

// Legacy types for backwards compatibility
export type SimulationStatus = 'idle' | 'running' | 'paused' | 'stopped';

export interface DirectionFrame {
  number?: number;
  image: string | null;
  image_annotated?: string | null;
}

export interface IntersectionFrames {
  intersection_id?: string | number;
  roads?: string[];
  frames: DirectionFrame[];
}

// Algorithm enum
export type Algorithm = 'dqn' | 'ppo' | 'colight';

// Traffic scenarios
export type TrafficScenario = 'light' | 'moderate' | 'heavy' | 'rush_hour';

// Task statuses
export type TaskStatus = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';

// SUMO traffic light from convertToSumo response
export interface SUMOTrafficLight {
  id: string;
  type: string;
  program_id: string;
  num_phases: number;
  lat?: number | null;
  lon?: number | null;
}

// Training requests
export interface SingleTrainingRequest {
  network_id: string;
  tl_id: string;
  algorithm: Algorithm;
  total_timesteps: number;
  scenario: TrafficScenario;
}

export interface MultiTrainingRequest {
  network_id: string;
  tl_ids: string[];
  algorithm: Algorithm;
  total_timesteps: number;
  scenario: TrafficScenario;
}

// Training response
export interface TrainingTaskResponse {
  task_id: string;
  status: string;
}

// Training progress from SSE
export interface TrainingProgressEvent {
  task_id: string;
  status: string;
  timestep: number;
  total_timesteps: number;
  progress: number;
  episode_count: number;
  mean_reward: number;
  avg_waiting_time: number;
  avg_queue_length: number;
  throughput: number;
  baseline_avg_waiting_time?: number;
  baseline_avg_queue_length?: number;
  baseline_throughput?: number;
}

// Training completion from SSE
export interface TrainingCompletionEvent {
  task_id: string;
  status: "completed";
  model_path: string;
  network_id: string;
  tl_id?: string;
  tl_ids?: string[];
  algorithm: string;
  timestep: number;
  total_timesteps: number;
  progress: number;
  mean_reward: number;
  avg_waiting_time: number;
  avg_queue_length: number;
  throughput: number;
  baseline_avg_waiting_time?: number;
  baseline_avg_queue_length?: number;
  baseline_throughput?: number;
}

// Model results from .results.json
export interface ModelBaselineMetrics {
  avg_waiting_time: number;
  avg_queue_length: number;
  throughput: number;
}

export interface ModelTrainedMetrics extends ModelBaselineMetrics {
  mean_reward: number;
}

export interface ModelTrainingConfig {
  algorithm: Algorithm;
  total_timesteps: number;
  scenario: TrafficScenario;
}

export interface ModelProgressPoint {
  timestep: number;
  avg_waiting_time: number;
  throughput: number;
  mean_reward: number;
}

export interface ModelResults {
  baseline: ModelBaselineMetrics;
  trained: ModelTrainedMetrics;
  training_config: ModelTrainingConfig;
  progress_history: ModelProgressPoint[];
}

// Task info
export interface TaskInfo {
  task_id: string;
  status: TaskStatus;
  network_id?: string;
  algorithm?: string;
  tl_ids: string[];
  total_timesteps?: number;
  progress: number;
  created_at?: string;
  completed_at?: string;
  error?: string;
  model_path?: string;
}

// Trained model
export interface TrainedModel {
  model_id: string;
  algorithm: Algorithm;
  network_id: string;
  tl_id: string;
  tl_ids?: string[];
  type?: 'single' | 'multi';
  model_path: string;
  created_at?: string;
  results?: ModelResults | null;
}

// Deployment
export interface Deployment {
  tl_id: string;
  model_id: string;
  model_path: string;
  network_id: string;
  ai_control_enabled: boolean;
}

// Network metadata
export interface NetworkJunction {
  id: string;
  lat: number;
  lon: number;
  tl_id?: string;
}

export interface NetworkMetadata {
  network_id: string;
  bbox: BoundingBox;
  intersection_count: number;
  traffic_light_count: number;
  created_at?: string;
  junctions: NetworkJunction[];
  road_count: number;
}

// Traffic light simulation state
export interface DirectionLightState {
  state: 'red' | 'yellow' | 'green';
  remaining: number;
}

export interface TrafficLightSimState {
  intersection_id: string;
  directions: Record<string, DirectionLightState>;
  cycle_duration: number;
}

// Waiting vehicle count per direction from backend
export interface WaitingCountResponse {
  id_camera: string;
  north: number;
  south: number;
  east: number;
  west: number;
  total: number;
}
