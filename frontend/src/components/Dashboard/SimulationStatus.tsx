import type { SimulationStatus } from '../../types';

interface SimulationStatusProps {
  status: SimulationStatus;
  currentStep: number;
  networkId?: string | null;
}

export function SimulationStatusDisplay({ status, currentStep, networkId }: SimulationStatusProps) {
  const statusColors = {
    idle: 'bg-gray-400',
    running: 'bg-green-500',
    paused: 'bg-yellow-500',
    stopped: 'bg-red-500',
  };

  return (
    <div className="bg-white rounded-lg shadow p-4">
      <h3 className="text-lg font-semibold mb-3">Simulation Status</h3>
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <span className={`w-3 h-3 rounded-full ${statusColors[status]}`} />
          <span className="capitalize">{status}</span>
        </div>
        <div className="text-sm text-gray-600">
          <p>Step: {currentStep}</p>
          {networkId && <p className="truncate">Network: {networkId}</p>}
        </div>
      </div>
    </div>
  );
}
