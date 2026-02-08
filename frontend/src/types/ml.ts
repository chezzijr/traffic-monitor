// ML-related TypeScript types matching backend schemas

export type TrainingAlgorithm = 'dqn' | 'ppo';

export type TrainingStatus = 'idle' | 'running' | 'completed' | 'failed' | 'stopping';

export interface TrainingJobInfo {
  network_id: string;
  tl_id: string;
  algorithm: string;
  total_timesteps: number;
  current_timestep: number;
  progress: number;
  start_time: string | null;
  end_time: string | null;
  error_message: string | null;
  model_path: string | null;
  total_episodes: number;
  mean_reward: number;
  std_reward: number;
}

export interface TrainingStatusResponse {
  status: TrainingStatus;
  job: TrainingJobInfo | null;
}

export interface TrainingStartRequest {
  network_id: string;
  tl_id: string;
  algorithm: TrainingAlgorithm;
  total_timesteps: number;
}

export interface ModelInfo {
  id: string;
  path: string;
  filename: string;
  network_id: string;
  tl_id: string;
  algorithm: string;
  timestamp: string;
  size_bytes: number;
  created_at: string;
}

export interface DeploymentInfo {
  tl_id: string;
  model_id: string;
  model_path: string;
  network_id: string;
  ai_control_enabled: boolean;
}

export interface DeployRequest {
  tl_id: string;
}

export interface ToggleAIRequest {
  tl_id: string;
  enabled: boolean;
}
