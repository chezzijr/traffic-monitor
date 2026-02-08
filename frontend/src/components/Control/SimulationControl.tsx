import { useState } from 'react';
import { Play, Pause, Square, StepForward } from 'lucide-react';
import { useMapStore } from '../../store/mapStore';
import type { SimulationStatus } from '../../types';

interface SimulationControlProps {
  status: SimulationStatus;
  currentStep: number;
  onStart: (scenario: string) => Promise<void>;
  onPause: () => Promise<void>;
  onResume: () => Promise<void>;
  onStop: () => Promise<void>;
  onStep: () => Promise<void>;
}

export function SimulationControl({
  status,
  currentStep,
  onStart,
  onPause,
  onResume,
  onStop,
  onStep,
}: SimulationControlProps) {
  const [isLoading, setIsLoading] = useState(false);
  const [scenario, setScenario] = useState<'light' | 'moderate' | 'heavy' | 'rush_hour'>('moderate');
  const networkId = useMapStore((state) => state.currentNetworkId);

  const handleAction = async (action: () => Promise<void>) => {
    setIsLoading(true);
    try {
      await action();
    } finally {
      setIsLoading(false);
    }
  };

  const isIdle = status === 'idle' || status === 'stopped';
  const isRunning = status === 'running';
  const isPaused = status === 'paused';

  return (
    <div className="bg-white rounded-lg shadow p-4">
      <h3 className="text-lg font-semibold mb-4">Simulation Control</h3>

      {/* Status indicator */}
      <div className="flex items-center gap-2 mb-4">
        <span className={`w-3 h-3 rounded-full ${
          isRunning ? 'bg-green-500' : isPaused ? 'bg-yellow-500' : 'bg-gray-400'
        }`} />
        <span className="text-sm capitalize">{status}</span>
        {!isIdle && <span className="text-sm text-gray-500">Step: {currentStep}</span>}
      </div>

      {/* Scenario selector - only show when idle */}
      {isIdle && (
        <div className="mb-4">
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Traffic Scenario
          </label>
          <select
            value={scenario}
            onChange={(e) => setScenario(e.target.value as typeof scenario)}
            className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
            disabled={!networkId}
          >
            <option value="light">Light Traffic</option>
            <option value="moderate">Moderate Traffic</option>
            <option value="heavy">Heavy Traffic</option>
            <option value="rush_hour">Rush Hour</option>
          </select>
        </div>
      )}

      {/* Control buttons */}
      <div className="flex gap-2">
        {isIdle ? (
          <button
            onClick={() => handleAction(() => onStart(scenario))}
            disabled={isLoading || !networkId}
            className="flex items-center gap-2 px-4 py-2 bg-green-500 text-white rounded hover:bg-green-600 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Play size={16} />
            Start
          </button>
        ) : (
          <>
            {isRunning ? (
              <button
                onClick={() => handleAction(onPause)}
                disabled={isLoading}
                className="flex items-center gap-2 px-4 py-2 bg-yellow-500 text-white rounded hover:bg-yellow-600 disabled:opacity-50"
              >
                <Pause size={16} />
                Pause
              </button>
            ) : (
              <button
                onClick={() => handleAction(onResume)}
                disabled={isLoading}
                className="flex items-center gap-2 px-4 py-2 bg-green-500 text-white rounded hover:bg-green-600 disabled:opacity-50"
              >
                <Play size={16} />
                Resume
              </button>
            )}

            <button
              onClick={() => handleAction(onStep)}
              disabled={isLoading || isRunning}
              className="flex items-center gap-2 px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600 disabled:opacity-50"
            >
              <StepForward size={16} />
              Step
            </button>

            <button
              onClick={() => handleAction(onStop)}
              disabled={isLoading}
              className="flex items-center gap-2 px-4 py-2 bg-red-500 text-white rounded hover:bg-red-600 disabled:opacity-50"
            >
              <Square size={16} />
              Stop
            </button>
          </>
        )}
      </div>

      {!networkId && isIdle && (
        <p className="mt-2 text-sm text-gray-500">
          Select a region and extract the network first
        </p>
      )}
    </div>
  );
}
