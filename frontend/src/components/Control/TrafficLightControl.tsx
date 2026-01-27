import { useState } from 'react';
import type { TrafficLightPhase } from '../../types';

interface TrafficLightInfo {
  id: string;
  phase: number;
  program: string;
}

interface TrafficLightControlProps {
  trafficLight: TrafficLightInfo;
  onSetPhase: (tlId: string, phase: number) => Promise<void>;
}

const phaseColors: Record<number, TrafficLightPhase> = {
  0: 'green',
  1: 'yellow',
  2: 'red',
  3: 'red',  // Common pattern: extended red
};

export function TrafficLightControl({ trafficLight, onSetPhase }: TrafficLightControlProps) {
  const [isLoading, setIsLoading] = useState(false);

  const handlePhaseChange = async (phase: number) => {
    setIsLoading(true);
    try {
      await onSetPhase(trafficLight.id, phase);
    } finally {
      setIsLoading(false);
    }
  };

  const currentColor = phaseColors[trafficLight.phase] ?? 'red';

  return (
    <div className="bg-white rounded-lg shadow p-4">
      <h4 className="font-medium mb-3 truncate" title={trafficLight.id}>
        {trafficLight.id}
      </h4>

      {/* Visual traffic light */}
      <div className="flex justify-center mb-4">
        <div className="bg-gray-800 rounded-lg p-2 space-y-2">
          {(['red', 'yellow', 'green'] as const).map((color) => (
            <div
              key={color}
              className={`w-8 h-8 rounded-full transition-colors ${
                currentColor === color
                  ? color === 'red'
                    ? 'bg-red-500 shadow-lg shadow-red-500/50'
                    : color === 'yellow'
                    ? 'bg-yellow-400 shadow-lg shadow-yellow-400/50'
                    : 'bg-green-500 shadow-lg shadow-green-500/50'
                  : 'bg-gray-600'
              }`}
            />
          ))}
        </div>
      </div>

      {/* Phase info */}
      <div className="text-sm text-gray-600 mb-3">
        <p>Phase: {trafficLight.phase}</p>
        <p>Program: {trafficLight.program}</p>
      </div>

      {/* Phase buttons */}
      <div className="grid grid-cols-4 gap-1">
        {[0, 1, 2, 3].map((phase) => (
          <button
            key={phase}
            onClick={() => handlePhaseChange(phase)}
            disabled={isLoading || trafficLight.phase === phase}
            className={`px-2 py-1 text-sm rounded transition-colors ${
              trafficLight.phase === phase
                ? 'bg-blue-500 text-white'
                : 'bg-gray-100 hover:bg-gray-200 disabled:opacity-50'
            }`}
          >
            {phase}
          </button>
        ))}
      </div>
    </div>
  );
}
