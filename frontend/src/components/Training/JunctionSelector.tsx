import { useEffect } from 'react';
import { CheckSquare, Square, Network } from 'lucide-react';
import { useMapStore } from '../../store/mapStore';

export function JunctionSelector() {
  const sumoTrafficLights = useMapStore((s) => s.sumoTrafficLights);
  const selectedRegion = useMapStore((s) => s.selectedRegion);
  const selectedJunctionIds = useMapStore((s) => s.selectedJunctionIds);
  const toggleJunctionSelection = useMapStore((s) => s.toggleJunctionSelection);
  const selectAllJunctions = useMapStore((s) => s.selectAllJunctions);
  const clearJunctionSelection = useMapStore((s) => s.clearJunctionSelection);
  const tlClusters = useMapStore((s) => s.tlClusters);
  const loadTlClusters = useMapStore((s) => s.loadTlClusters);
  const selectCluster = useMapStore((s) => s.selectCluster);
  const currentNetworkId = useMapStore((s) => s.currentNetworkId);

  // Restrict the list to TLs inside the user's bbox with a renderable coord.
  // netconvert's buffer leaks tlLogics beyond the drawn rectangle; listing
  // them here would confuse selection since they don't highlight on the map.
  const visibleTls = sumoTrafficLights.filter(
    (tl) =>
      tl.lat != null &&
      tl.lon != null &&
      (!selectedRegion ||
        (tl.lat >= selectedRegion.south &&
          tl.lat <= selectedRegion.north &&
          tl.lon >= selectedRegion.west &&
          tl.lon <= selectedRegion.east)),
  );
  const totalCount = visibleTls.length;
  const selectedCount = selectedJunctionIds.length;

  useEffect(() => {
    if (currentNetworkId && sumoTrafficLights.length > 0 && tlClusters.length === 0) {
      loadTlClusters(currentNetworkId);
    }
  }, [currentNetworkId, sumoTrafficLights.length, tlClusters.length, loadTlClusters]);

  if (totalCount === 0) return null;

  const multiTlClusters = tlClusters.filter((c) => c.size >= 2);

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-3">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm font-semibold text-gray-700">Junctions</h3>
        <span className="text-xs text-gray-500">
          {selectedCount} of {totalCount} selected
        </span>
      </div>

      <div className="flex gap-2 mb-2">
        <button
          onClick={selectAllJunctions}
          className="text-xs px-2 py-1 rounded bg-blue-50 text-blue-600 hover:bg-blue-100 transition-colors"
        >
          Select All In Region
        </button>
        <button
          onClick={clearJunctionSelection}
          className="text-xs px-2 py-1 rounded bg-gray-50 text-gray-600 hover:bg-gray-100 transition-colors"
        >
          Clear
        </button>
      </div>

      {multiTlClusters.length > 0 && (
        <div className="mb-3 border-t pt-2">
          <div className="flex items-center gap-1.5 mb-1.5">
            <Network size={12} className="text-purple-600" />
            <h4 className="text-xs font-semibold text-gray-600">
              Connected Clusters
            </h4>
            <span className="text-[10px] text-gray-400">
              — recommended for CoLight training
            </span>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {multiTlClusters.map((c) => (
              <button
                key={c.cluster_id}
                onClick={() => selectCluster(c.cluster_id)}
                className="text-xs px-2 py-1 rounded bg-purple-50 text-purple-700 hover:bg-purple-100 transition-colors font-mono"
                title={c.tl_ids.join(', ')}
              >
                {c.cluster_id} — {c.size} TLs
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="max-h-48 overflow-y-auto space-y-1">
        {visibleTls.map((tl) => {
          const isSelected = selectedJunctionIds.includes(tl.id);
          return (
            <button
              key={tl.id}
              onClick={() => toggleJunctionSelection(tl.id)}
              className={`w-full flex items-center gap-2 px-2 py-1.5 rounded text-left text-sm transition-colors ${
                isSelected
                  ? 'bg-amber-50 text-amber-800'
                  : 'hover:bg-gray-50 text-gray-700'
              }`}
            >
              {isSelected ? (
                <CheckSquare size={14} className="text-amber-500 shrink-0" />
              ) : (
                <Square size={14} className="text-gray-400 shrink-0" />
              )}
              <span className="truncate font-mono text-xs">{tl.id}</span>
              <span className="text-xs text-gray-400 ml-auto">{tl.num_phases}p</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
