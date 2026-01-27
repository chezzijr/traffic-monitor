import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';

interface ChartDataPoint {
  step: number;
  vehicles: number;
  waitTime: number;
}

interface ChartsProps {
  data: ChartDataPoint[];
}

export function MetricsChart({ data }: ChartsProps) {
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
          <LineChart data={data}>
            <XAxis dataKey="step" tick={{ fontSize: 12 }} />
            <YAxis tick={{ fontSize: 12 }} />
            <Tooltip />
            <Line type="monotone" dataKey="vehicles" stroke="#3b82f6" strokeWidth={2} dot={false} name="Vehicles" />
            <Line type="monotone" dataKey="waitTime" stroke="#f59e0b" strokeWidth={2} dot={false} name="Wait Time" />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
