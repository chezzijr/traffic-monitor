import { memo, useMemo } from 'react';
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend } from 'recharts';

interface ChartDataPoint {
  step: number;
  vehicles: number;
  waitTime: number;
}

interface ChartsProps {
  data: ChartDataPoint[];
}

const MAX_DISPLAY_POINTS = 100;

// Downsample data to reduce chart rendering overhead
function downsample(data: ChartDataPoint[], maxPoints: number): ChartDataPoint[] {
  if (data.length <= maxPoints) return data;
  const step = Math.ceil(data.length / maxPoints);
  return data.filter((_, i) => i % step === 0 || i === data.length - 1);
}

export const MetricsChart = memo(function MetricsChart({ data }: ChartsProps) {
  // Downsample large datasets for rendering performance
  const displayData = useMemo(() => downsample(data, MAX_DISPLAY_POINTS), [data]);

  if (data.length === 0) {
    return (
      <div className="bg-white rounded-lg shadow p-4 h-64 flex items-center justify-center text-gray-400">
        No data available
      </div>
    );
  }

  return (
    <div className="bg-white rounded-lg shadow p-4">
      <h3 className="text-lg font-semibold mb-3">Metrics History</h3>
      <div className="h-48">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={displayData}>
            <XAxis
              dataKey="step"
              tick={{ fontSize: 12 }}
              label={{ value: 'Step', position: 'insideBottomRight', offset: -5, fontSize: 11 }}
            />
            <YAxis
              yAxisId="left"
              tick={{ fontSize: 12 }}
              label={{ value: 'Vehicles', angle: -90, position: 'insideLeft', fontSize: 11 }}
            />
            <YAxis
              yAxisId="right"
              orientation="right"
              tick={{ fontSize: 12 }}
              label={{ value: 'Wait Time (s)', angle: 90, position: 'insideRight', fontSize: 11 }}
            />
            <Tooltip
              formatter={(value, name) => [
                name === 'vehicles' ? value : Number(value).toFixed(2),
                name === 'vehicles' ? 'Total Vehicles' : 'Avg Wait Time (s)',
              ]}
              labelFormatter={(label) => `Step: ${label}`}
            />
            <Legend
              verticalAlign="top"
              height={36}
              formatter={(value) => (value === 'vehicles' ? 'Total Vehicles' : 'Avg Wait Time (s)')}
            />
            <Line
              yAxisId="left"
              type="monotone"
              dataKey="vehicles"
              stroke="#3b82f6"
              strokeWidth={2}
              dot={false}
              name="vehicles"
              isAnimationActive={false}
            />
            <Line
              yAxisId="right"
              type="monotone"
              dataKey="waitTime"
              stroke="#f59e0b"
              strokeWidth={2}
              dot={false}
              name="waitTime"
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
});
