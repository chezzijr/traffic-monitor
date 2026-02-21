import { useEffect } from 'react';
import toast from 'react-hot-toast';
import { Network, RefreshCw, Loader2, AlertCircle, FolderOpen } from 'lucide-react';
import { mapService } from '../../services/mapService';
import { useNetworkStore } from '../../store/networkStore';
import { NetworkCard } from './NetworkCard';

export function NetworksPanel() {
  const networks = useNetworkStore((s) => s.networks);
  const activeNetworkId = useNetworkStore((s) => s.activeNetworkId);
  const isLoading = useNetworkStore((s) => s.isLoading);
  const error = useNetworkStore((s) => s.error);
  const setNetworks = useNetworkStore((s) => s.setNetworks);
  const setLoading = useNetworkStore((s) => s.setLoading);
  const setError = useNetworkStore((s) => s.setError);

  const fetchNetworks = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await mapService.getNetworkDetails();
      setNetworks(data);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to fetch networks';
      setError(message);
      toast.error(message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchNetworks();
  }, []);

  return (
    <div className="bg-white rounded-lg shadow p-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold flex items-center gap-2">
          <Network size={20} />
          Networks
        </h3>
        <button
          onClick={fetchNetworks}
          disabled={isLoading}
          className="p-1.5 text-gray-500 hover:text-blue-600 hover:bg-blue-50 rounded-md transition-colors disabled:opacity-50"
          title="Refresh networks"
        >
          <RefreshCw size={16} className={isLoading ? 'animate-spin' : ''} />
        </button>
      </div>

      {/* Loading state */}
      {isLoading && networks.length === 0 && (
        <div className="flex flex-col items-center justify-center py-8 text-gray-400">
          <Loader2 size={24} className="animate-spin mb-2" />
          <p className="text-sm">Loading networks...</p>
        </div>
      )}

      {/* Error state */}
      {error && !isLoading && (
        <div className="flex items-center gap-2 p-3 bg-red-50 border border-red-200 rounded-md mb-4">
          <AlertCircle size={16} className="text-red-500 shrink-0" />
          <p className="text-sm text-red-700">{error}</p>
        </div>
      )}

      {/* Empty state */}
      {!isLoading && !error && networks.length === 0 && (
        <div className="flex flex-col items-center justify-center py-8 text-gray-400">
          <FolderOpen size={32} className="mb-2" />
          <p className="text-sm font-medium">No saved networks</p>
          <p className="text-xs mt-1">Select a region on the map to create one</p>
        </div>
      )}

      {/* Network cards */}
      {networks.length > 0 && (
        <div className="space-y-3">
          {networks.map((network) => (
            <NetworkCard
              key={network.network_id}
              network={network}
              isActive={network.network_id === activeNetworkId}
            />
          ))}
        </div>
      )}
    </div>
  );
}
