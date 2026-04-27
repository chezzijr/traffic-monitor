import { api } from './api';
import type { BoundingBox, NetworkInfo, Intersection, SUMOTrafficLight } from '../types';

export interface TlCluster {
  cluster_id: string;
  size: number;
  tl_ids: string[];
}

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
    traffic_lights: SUMOTrafficLight[];
    osm_sumo_mapping: Record<string, string>;
  }> {
    const response = await api.post<{
      sumo_network_path: string;
      network_id: string;
      traffic_lights: SUMOTrafficLight[];
      osm_sumo_mapping: Record<string, string>;
    }>(`/map/convert-to-sumo/${networkId}`);
    return response.data;
  },

  // Get list of cached network IDs
  async getNetworks(): Promise<string[]> {
    const response = await api.get<string[]>('/map/networks');
    return response.data;
  },

  // Get connected components of the TL-to-TL graph for a network
  async getTlClusters(networkId: string): Promise<TlCluster[]> {
    const response = await api.get<TlCluster[]>(`/networks/${networkId}/tl-clusters`);
    return response.data;
  },
};
