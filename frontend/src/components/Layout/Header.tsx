import { Activity, Package } from 'lucide-react';
import { useModelStore } from '../../store/modelStore';

export function Header() {
  const togglePanel = useModelStore((s) => s.togglePanel);
  const modelCount = useModelStore((s) => s.models.length);

  return (
    <header className="h-12 bg-white border-b px-4 flex items-center justify-between">
      <div className="flex items-center gap-2 text-sm text-gray-600">
        <Activity size={16} />
        <span>HCMC Traffic Light Optimization</span>
      </div>
      <button
        onClick={togglePanel}
        className="flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-lg border border-gray-200 hover:bg-gray-50 transition-colors text-gray-700"
      >
        <Package size={14} />
        Models
        {modelCount > 0 && (
          <span className="bg-blue-500 text-white text-[10px] px-1.5 py-0.5 rounded-full font-medium">
            {modelCount}
          </span>
        )}
      </button>
    </header>
  );
}
