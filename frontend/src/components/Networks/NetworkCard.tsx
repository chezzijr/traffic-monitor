import { useState } from 'react';
import toast from 'react-hot-toast';
import { MapPin, Trash2, Navigation, GitFork, Calendar, Loader2 } from 'lucide-react';
import { mapService } from '../../services/mapService';
import { useMapStore } from '../../store/mapStore';
import { useNetworkStore } from '../../store/networkStore';
import type { NetworkDetail } from '../../types';

interface NetworkCardProps {
  network: NetworkDetail;
  isActive: boolean;
}

function formatDate(isoString: string): string {
  return new Date(isoString).toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function formatBbox(bbox: NetworkDetail['bbox']): string {
  return `${bbox.south.toFixed(4)}, ${bbox.west.toFixed(4)} - ${bbox.north.toFixed(4)}, ${bbox.east.toFixed(4)}`;
}

export function NetworkCard({ network, isActive }: NetworkCardProps) {
  const [isLoadingMap, setIsLoadingMap] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);

  const setCurrentNetworkId = useMapStore((s) => s.setCurrentNetworkId);
  const setIntersections = useMapStore((s) => s.setIntersections);
  const setSelectedRegion = useMapStore((s) => s.setSelectedRegion);
  const setActiveNetworkId = useNetworkStore((s) => s.setActiveNetworkId);
  const removeNetwork = useNetworkStore((s) => s.removeNetwork);

  const shortId = network.network_id.slice(0, 8);
  const displayName = network.name || `Network ${shortId}`;

  const handleLoadOnMap = async () => {
    setIsLoadingMap(true);
    try {
      const detail = await mapService.loadNetwork(network.network_id);
      const intersections = detail.junctions.map((j) => ({
        id: j.id,
        lat: j.lat,
        lon: j.lon,
        num_roads: 0,
        has_traffic_light: j.tl_id !== null,
        sumo_tl_id: j.tl_id ?? undefined,
      }));
      setCurrentNetworkId(network.network_id);
      setIntersections(intersections);
      setSelectedRegion(network.bbox);
      setActiveNetworkId(network.network_id);
      toast.success(`Loaded network ${shortId} on map`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to load network');
    } finally {
      setIsLoadingMap(false);
    }
  };

  const handleDelete = async () => {
    if (!window.confirm(`Delete network ${shortId}? This cannot be undone.`)) return;

    setIsDeleting(true);
    try {
      await mapService.deleteNetwork(network.network_id);
      removeNetwork(network.network_id);
      toast.success(`Deleted network ${shortId}`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to delete network');
    } finally {
      setIsDeleting(false);
    }
  };

  return (
    <div
      className={`bg-white rounded-lg shadow-sm border p-4 ${
        isActive ? 'border-blue-400 ring-1 ring-blue-200' : 'border-gray-200'
      }`}
    >
      {/* Header */}
      <div className="flex items-start justify-between mb-3">
        <div>
          <h4 className="text-sm font-semibold text-gray-900">{displayName}</h4>
          <p className="text-xs text-gray-400 font-mono">{shortId}...</p>
        </div>
        {isActive && (
          <span className="text-xs font-medium text-blue-600 bg-blue-50 px-2 py-0.5 rounded">
            Active
          </span>
        )}
      </div>

      {/* Metadata */}
      <div className="space-y-1.5 text-sm mb-3">
        <div className="flex items-center gap-2 text-gray-600">
          <MapPin size={14} className="text-gray-400 shrink-0" />
          <span className="text-xs truncate" title={formatBbox(network.bbox)}>
            {formatBbox(network.bbox)}
          </span>
        </div>
        <div className="flex items-center gap-2 text-gray-600">
          <GitFork size={14} className="text-gray-400 shrink-0" />
          <span className="text-xs">
            {network.junctions.length} junctions ({network.signalized_junction_count} signalized)
          </span>
        </div>
        <div className="flex items-center gap-2 text-gray-600">
          <Navigation size={14} className="text-gray-400 shrink-0" />
          <span className="text-xs">{network.road_count} roads</span>
        </div>
        <div className="flex items-center gap-2 text-gray-600">
          <Calendar size={14} className="text-gray-400 shrink-0" />
          <span className="text-xs">{formatDate(network.created_at)}</span>
        </div>
      </div>

      {/* Actions */}
      <div className="flex gap-2">
        <button
          onClick={handleLoadOnMap}
          disabled={isLoadingMap || isActive}
          className="flex-1 flex items-center justify-center gap-1.5 px-3 py-1.5 text-sm rounded-md bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {isLoadingMap ? (
            <Loader2 size={14} className="animate-spin" />
          ) : (
            <MapPin size={14} />
          )}
          {isActive ? 'Active' : 'Load on Map'}
        </button>
        <button
          onClick={handleDelete}
          disabled={isDeleting}
          className="flex items-center justify-center gap-1.5 px-3 py-1.5 text-sm rounded-md bg-red-50 text-red-600 hover:bg-red-100 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {isDeleting ? (
            <Loader2 size={14} className="animate-spin" />
          ) : (
            <Trash2 size={14} />
          )}
          Delete
        </button>
      </div>
    </div>
  );
}
