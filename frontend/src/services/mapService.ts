import { api } from './api';
import type { BoundingBox, NetworkInfo, NetworkDetail, Intersection, SumoJunction } from '../types';

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
  async convertToSumo(networkId: string): Promise<{
    sumo_network_path: string;
    network_id: string;
    osm_sumo_mapping: Record<string, string>;
    sumo_junctions: SumoJunction[];
  }> {
    const response = await api.post<{
      sumo_network_path: string;
      network_id: string;
      osm_sumo_mapping: Record<string, string>;
      sumo_junctions: SumoJunction[];
    }>(`/map/convert-to-sumo/${networkId}`);
    return response.data;
  },

  // Get list of cached network IDs
  async getNetworks(): Promise<string[]> {
    const response = await api.get<string[]>('/map/networks');
    return response.data;
  },

  // Get detailed info for all saved networks
  async getNetworkDetails(): Promise<NetworkDetail[]> {
    const response = await api.get<NetworkDetail[]>('/networks');
    return response.data;
  },

  // Delete a saved network
  async deleteNetwork(id: string): Promise<void> {
    await api.delete(`/networks/${id}`);
  },

  // Load a saved network into the active session
  async loadNetwork(id: string): Promise<NetworkDetail> {
    const response = await api.post<NetworkDetail>(`/networks/${id}/load`);
    return response.data;
  },
};
