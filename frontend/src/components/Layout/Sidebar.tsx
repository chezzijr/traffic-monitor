import { useState } from 'react';
import { MapPin } from 'lucide-react';
import { useMapStore } from '../../store/mapStore';
import { TrainingPanel, ModelsPanel, DeploymentPanel } from '../ML';

type TabType = 'simulation' | 'training' | 'models' | 'deployment';

interface SidebarProps {
  children: React.ReactNode;  // Simulation controls passed from App
}

export function Sidebar({ children }: SidebarProps) {
  const [activeTab, setActiveTab] = useState<TabType>('simulation');
  const { selectionMode, setSelectionMode, currentNetworkId } = useMapStore();

  const tabs: { id: TabType; label: string }[] = [
    { id: 'simulation', label: 'Simulation' },
    { id: 'training', label: 'Training' },
    { id: 'models', label: 'Models' },
    { id: 'deployment', label: 'Deploy' },
  ];

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
          <p className="mt-2 text-sm text-gray-500 truncate">
            Network: {currentNetworkId}
          </p>
        )}
      </div>

      {/* Tab navigation */}
      <div className="flex border-b">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`flex-1 px-2 py-2 text-sm font-medium transition-colors ${
              activeTab === tab.id
                ? 'text-blue-600 border-b-2 border-blue-600 bg-white'
                : 'text-gray-500 hover:text-gray-700 hover:bg-gray-100'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="flex-1 p-4 space-y-4 overflow-y-auto">
        {activeTab === 'simulation' && children}
        {activeTab === 'training' && <TrainingPanel />}
        {activeTab === 'models' && <ModelsPanel />}
        {activeTab === 'deployment' && <DeploymentPanel />}
      </div>
    </aside>
  );
}
