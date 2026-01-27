import { Activity } from 'lucide-react';

export function Header() {
  return (
    <header className="h-12 bg-white border-b px-4 flex items-center justify-between">
      <div className="flex items-center gap-2 text-sm text-gray-600">
        <Activity size={16} />
        <span>HCMC Traffic Light Optimization</span>
      </div>
    </header>
  );
}
