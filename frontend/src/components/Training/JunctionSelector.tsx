import { CheckSquare, Square } from 'lucide-react';
import { useMapStore } from '../../store/mapStore';

export function JunctionSelector() {
  const sumoTrafficLights = useMapStore((s) => s.sumoTrafficLights);
  const selectedJunctionIds = useMapStore((s) => s.selectedJunctionIds);
  const toggleJunctionSelection = useMapStore((s) => s.toggleJunctionSelection);
  const selectAllJunctions = useMapStore((s) => s.selectAllJunctions);
  const clearJunctionSelection = useMapStore((s) => s.clearJunctionSelection);

  const totalCount = sumoTrafficLights.length;
  const selectedCount = selectedJunctionIds.length;

  if (totalCount === 0) return null;

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

      <div className="max-h-48 overflow-y-auto space-y-1">
        {sumoTrafficLights.map((tl) => {
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
