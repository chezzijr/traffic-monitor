import { api } from './api';
import type { BoundingBox, NetworkInfo, Intersection, TrafficSignal } from '../types';

export const mapService = {
  // Extract network from OSM for a given bounding box
  async extractRegion(bbox: BoundingBox): Promise<NetworkInfo> {
    const response = await api.post<NetworkInfo>('/map/extract-region', bbox);
    return response.data;
  },


  // Get intersections for a network
  async getIntersections(networkId: string): Promise<Intersection[]> {
    const response = await api.get<Intersection[]>(`/map/intersections/${networkId}`);
    return response.data;
  },

  // Convert network to SUMO format
  async convertToSumo(networkId: string): Promise<{ sumo_network_path: string; network_id: string }> {
    const response = await api.post<{ sumo_network_path: string; network_id: string }>(
      `/map/convert-to-sumo/${networkId}`
    );
    return response.data;
  },

  // Get list of cached network IDs
  async getNetworks(): Promise<string[]> {
    const response = await api.get<string[]>('/map/networks');
    return response.data;
  },

  // Get OSM traffic signals around a point
  async getTrafficSignals(params: { lat: number; lng: number; radius: number }): Promise<TrafficSignal[]> {
    const response = await api.get<TrafficSignal[]>('/map/traffic-signals', { params });
    return response.data;
  },
};
