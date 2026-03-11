import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  Legend,
} from 'recharts';
import type { TrainingProgressEvent } from '../../types';

interface TrainingChartProps {
  data: TrainingProgressEvent[];
}

export function TrainingChart({ data }: TrainingChartProps) {
  if (data.length === 0) {
    return (
      <div className="h-full flex items-center justify-center text-sm text-gray-400">
        Waiting for training data...
      </div>
    );
  }

  const chartData = data.map((d) => ({
    timestep: d.timestep,
    avg_waiting_time: Number(d.avg_waiting_time.toFixed(2)),
    throughput: Number(d.throughput.toFixed(2)),
    mean_reward: Number(d.mean_reward.toFixed(2)),
  }));

  const latestEvent = data[data.length - 1];
  const hasBaseline = latestEvent.baseline_avg_waiting_time !== undefined;

  return (
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={chartData} margin={{ top: 5, right: 20, bottom: 5, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
        <XAxis
          dataKey="timestep"
          tick={{ fontSize: 10 }}
          tickFormatter={(v) => `${(v / 1000).toFixed(0)}k`}
        />
        <YAxis tick={{ fontSize: 10 }} />
        <Tooltip
          contentStyle={{ fontSize: 12 }}
          labelFormatter={(v) => `Step ${v.toLocaleString()}`}
        />
        <Legend wrapperStyle={{ fontSize: 11 }} />
        <Line
          type="monotone"
          dataKey="avg_waiting_time"
          stroke="#ef4444"
          strokeWidth={1.5}
          dot={false}
          name="Avg Wait Time"
        />
        <Line
          type="monotone"
          dataKey="throughput"
          stroke="#3b82f6"
          strokeWidth={1.5}
          dot={false}
          name="Throughput"
        />
        <Line
          type="monotone"
          dataKey="mean_reward"
          stroke="#22c55e"
          strokeWidth={1.5}
          dot={false}
          name="Mean Reward"
        />
        {hasBaseline && latestEvent.baseline_avg_waiting_time != null && (
          <ReferenceLine
            y={latestEvent.baseline_avg_waiting_time}
            stroke="#ef4444"
            strokeDasharray="5 5"
            label={{ value: 'Baseline Wait', fontSize: 9, fill: '#ef4444' }}
          />
        )}
        {hasBaseline && latestEvent.baseline_throughput != null && (
          <ReferenceLine
            y={latestEvent.baseline_throughput}
            stroke="#3b82f6"
            strokeDasharray="5 5"
            label={{ value: 'Baseline Tput', fontSize: 9, fill: '#3b82f6' }}
          />
        )}
      </LineChart>
    </ResponsiveContainer>
  );
}
