import { create } from 'zustand';
import type { NetworkDetail } from '../types';

interface NetworkState {
  // State
  networks: NetworkDetail[];
  activeNetworkId: string | null;
  isLoading: boolean;
  error: string | null;

  // Actions
  setNetworks: (networks: NetworkDetail[]) => void;
  addNetwork: (network: NetworkDetail) => void;
  removeNetwork: (networkId: string) => void;
  setActiveNetworkId: (id: string | null) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
}

export const useNetworkStore = create<NetworkState>((set) => ({
  // Initial state
  networks: [],
  activeNetworkId: null,
  isLoading: false,
  error: null,

  // Actions
  setNetworks: (networks) => set({ networks }),
  addNetwork: (network) =>
    set((state) => ({ networks: [...state.networks, network] })),
  removeNetwork: (networkId) =>
    set((state) => ({
      networks: state.networks.filter((n) => n.network_id !== networkId),
      activeNetworkId:
        state.activeNetworkId === networkId ? null : state.activeNetworkId,
    })),
  setActiveNetworkId: (id) => set({ activeNetworkId: id }),
  setLoading: (loading) => set({ isLoading: loading }),
  setError: (error) => set({ error }),
}));
