import { MapPin } from 'lucide-react';
import { useMapStore } from '../../store/mapStore';

interface SidebarProps {
  children: React.ReactNode;
}

export function Sidebar({ children }: SidebarProps) {
  const { selectionMode, setSelectionMode, currentNetworkId, reset } = useMapStore();

  return (
    <aside className="w-80 bg-gray-50 border-r overflow-y-auto flex flex-col">
      <div className="p-4 border-b">
        <h1 className="text-xl font-bold flex items-center gap-2">
          <MapPin className="text-blue-500" />
          Traffic Monitor
        </h1>
      </div>

      <div className="p-4 border-b">
        <button
          onClick={() => setSelectionMode(!selectionMode)}
          className={`w-full px-4 py-2 rounded font-medium transition-colors ${
            selectionMode
              ? 'bg-blue-500 text-white'
              : 'bg-white border border-gray-300 hover:bg-gray-50'
          }`}
        >
          {selectionMode ? 'Cancel Selection' : 'Select Region'}
        </button>
        {currentNetworkId && (
          <div className="mt-2 flex items-center justify-between gap-2">
            <p className="text-sm text-gray-500 truncate flex-1">
              Network: {currentNetworkId}
            </p>
            <button
              onClick={() => reset()}
              className="text-xs text-red-500 hover:text-red-700 whitespace-nowrap"
            >
              New Region
            </button>
          </div>
        )}
      </div>

      <div className="flex-1 p-4 space-y-4">
        {children}
      </div>
    </aside>
  );
}
