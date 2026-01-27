import { api } from './api';
import type {
  SimulationStatusResponse,
  SimulationStepMetrics,
  TrafficLightInfo,
} from '../types';

export const simulationService = {
  // Start a simulation for the given network
  async start(networkId: string, gui?: boolean): Promise<SimulationStatusResponse> {
    const response = await api.post<SimulationStatusResponse>('/simulation/start', {
      network_id: networkId,
      gui: gui ?? false,
    });
    return response.data;
  },

  // Advance simulation by one step
  async step(): Promise<SimulationStepMetrics> {
    const response = await api.post<SimulationStepMetrics>('/simulation/step');
    return response.data;
  },

  // Pause the currently running simulation
  async pause(): Promise<SimulationStatusResponse> {
    const response = await api.post<SimulationStatusResponse>('/simulation/pause');
    return response.data;
  },

  // Resume a paused simulation
  async resume(): Promise<SimulationStatusResponse> {
    const response = await api.post<SimulationStatusResponse>('/simulation/resume');
    return response.data;
  },

  // Stop and cleanup the current simulation
  async stop(): Promise<SimulationStatusResponse> {
    const response = await api.post<SimulationStatusResponse>('/simulation/stop');
    return response.data;
  },

  // Get current simulation status
  async getStatus(): Promise<SimulationStatusResponse> {
    const response = await api.get<SimulationStatusResponse>('/simulation/status');
    return response.data;
  },

  // Get all traffic lights and their states
  async getTrafficLights(): Promise<TrafficLightInfo[]> {
    const response = await api.get<TrafficLightInfo[]>('/control/traffic-lights');
    return response.data;
  },

  // Set a traffic light to a specific phase
  async setTrafficLightPhase(tlId: string, phase: number): Promise<TrafficLightInfo> {
    const response = await api.post<TrafficLightInfo>(
      `/control/traffic-lights/${tlId}/phase`,
      { phase }
    );
    return response.data;
  },
};
