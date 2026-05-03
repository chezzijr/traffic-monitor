import { Activity, Package, Brain } from 'lucide-react';
import { useModelStore } from '../../store/modelStore';

export function Header() {
  const togglePanel = useModelStore((s) => s.togglePanel);
  const modelCount = useModelStore((s) => s.models.length);

  return (
    <header className="h-12 bg-white border-b px-4 flex items-center justify-between">
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2 text-sm text-gray-600">
          <Activity size={16} />
          <a href="/" className="hover:text-gray-900 transition-colors">
            HCMC Traffic Light Optimization
          </a>
        </div>
        <a
          href="/evaluate"
          className="flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-lg border border-violet-200 bg-violet-50 hover:bg-violet-100 transition-colors text-violet-700"
        >
          <Brain size={14} />
          Evaluate
        </a>
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
