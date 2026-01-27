import { Car, Clock, Activity, TrendingUp } from 'lucide-react';
import type { SimulationMetrics } from '../../types';

interface MetricsPanelProps {
  metrics: SimulationMetrics | null;
  isLoading?: boolean;
}

export function MetricsPanel({ metrics, isLoading }: MetricsPanelProps) {
  if (isLoading) {
    return (
      <div className="grid grid-cols-2 gap-4">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="bg-white rounded-lg shadow p-4 animate-pulse">
            <div className="h-4 bg-gray-200 rounded w-1/2 mb-2" />
            <div className="h-8 bg-gray-200 rounded w-3/4" />
          </div>
        ))}
      </div>
    );
  }

  const cards = [
    { label: 'Total Vehicles', value: metrics?.total_vehicles ?? 0, icon: Car, color: 'text-blue-500' },
    { label: 'Avg Wait Time', value: `${(metrics?.average_wait_time ?? 0).toFixed(1)}s`, icon: Clock, color: 'text-yellow-500' },
    { label: 'Current Step', value: metrics?.current_step ?? 0, icon: Activity, color: 'text-green-500' },
    { label: 'Throughput', value: metrics?.throughput ?? 0, icon: TrendingUp, color: 'text-purple-500' },
  ];

  return (
    <div className="grid grid-cols-2 gap-4">
      {cards.map((card) => (
        <div key={card.label} className="bg-white rounded-lg shadow p-4">
          <div className="flex items-center gap-2 text-sm text-gray-500 mb-1">
            <card.icon size={16} className={card.color} />
            {card.label}
          </div>
          <p className="text-2xl font-semibold">{card.value}</p>
        </div>
      ))}
    </div>
  );
}
