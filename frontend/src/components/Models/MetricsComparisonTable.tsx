import type { ModelBaselineMetrics, ModelTrainedMetrics } from '../../types';

interface MetricsComparisonTableProps {
  baseline: ModelBaselineMetrics;
  trained: ModelTrainedMetrics;
}

function formatDelta(baseline: number, trained: number, higherIsBetter: boolean): { text: string; colorClass: string } {
  if (baseline === 0) {
    return { text: '—', colorClass: 'text-gray-400' };
  }

  const delta = ((trained - baseline) / baseline) * 100;
  const isIncrease = delta > 0;
  const arrow = isIncrease ? '▲' : '▼';
  const isImprovement = higherIsBetter ? isIncrease : !isIncrease;
  const colorClass = delta === 0 ? 'text-gray-500' : isImprovement ? 'text-green-600' : 'text-red-600';

  return {
    text: `${arrow}${Math.abs(delta).toFixed(1)}%`,
    colorClass,
  };
}

export function MetricsComparisonTable({ baseline, trained }: MetricsComparisonTableProps) {
  const rows: {
    label: string;
    baselineValue: string;
    trainedValue: string;
    delta: { text: string; colorClass: string } | null;
  }[] = [
    {
      label: 'Avg Wait Time',
      baselineValue: `${baseline.avg_waiting_time.toFixed(1)}s`,
      trainedValue: `${trained.avg_waiting_time.toFixed(1)}s`,
      delta: formatDelta(baseline.avg_waiting_time, trained.avg_waiting_time, false),
    },
    {
      label: 'Avg Queue Length',
      baselineValue: baseline.avg_queue_length.toFixed(1),
      trainedValue: trained.avg_queue_length.toFixed(1),
      delta: formatDelta(baseline.avg_queue_length, trained.avg_queue_length, false),
    },
    {
      label: 'Throughput',
      baselineValue: String(baseline.throughput),
      trainedValue: String(trained.throughput),
      delta: formatDelta(baseline.throughput, trained.throughput, true),
    },
    {
      label: 'Mean Reward',
      baselineValue: '—',
      trainedValue: trained.mean_reward.toFixed(2),
      delta: null,
    },
  ];

  return (
    <table className="w-full text-xs border-collapse">
      <thead>
        <tr className="text-left text-gray-500 border-b border-gray-200">
          <th className="py-1 pr-2 font-medium">Metric</th>
          <th className="py-1 pr-2 font-medium">Baseline</th>
          <th className="py-1 font-medium">AI Model</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.label} className="border-b border-gray-100 last:border-b-0">
            <td className="py-1 pr-2 text-gray-600">{row.label}</td>
            <td className="py-1 pr-2 text-gray-700 font-mono">{row.baselineValue}</td>
            <td className="py-1 font-mono">
              <span className="text-gray-700">{row.trainedValue}</span>
              {row.delta && (
                <span className={`ml-1 text-[10px] ${row.delta.colorClass}`}>
                  ({row.delta.text})
                </span>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
