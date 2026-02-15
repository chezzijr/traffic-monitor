import { useState } from 'react';
import toast from 'react-hot-toast';
import { Play, Brain, RefreshCw, Info } from 'lucide-react';
import { useMapStore } from '../../store/mapStore';
import { taskService } from '../../services/taskService';
import { mapService } from '../../services/mapService';
import type { TrainingAlgorithm } from '../../types/ml';

export function TrainingPanel() {
  const [algorithm, setAlgorithm] = useState<TrainingAlgorithm>('dqn');
  const [totalTimesteps, setTotalTimesteps] = useState(10000);
  const [isLoading, setIsLoading] = useState(false);
  const [isPreparing, setIsPreparing] = useState(false);

  const networkId = useMapStore((state) => state.currentNetworkId);
  const sumoJunctions = useMapStore((state) => state.sumoJunctions);
  const setSumoJunctions = useMapStore((state) => state.setSumoJunctions);
  const tlId = useMapStore((state) => state.selectedTrafficLightId);
  const setTlId = useMapStore((state) => state.setSelectedTrafficLightId);

  // Filter to only signalized junctions (those with a traffic light ID)
  const signalizedJunctions = sumoJunctions.filter((j) => j.tl_id !== null);

  // Prepare network by converting to SUMO format and getting junctions
  const handlePrepareNetwork = async () => {
    if (!networkId) return;

    setIsPreparing(true);
    try {
      const sumoResult = await mapService.convertToSumo(networkId);

      // Update sumoJunctions from the conversion result
      if (sumoResult.sumo_junctions && sumoResult.sumo_junctions.length > 0) {
        setSumoJunctions(sumoResult.sumo_junctions);
        const signalized = sumoResult.sumo_junctions.filter((j) => j.tl_id !== null);
        toast.success(`Found ${signalized.length} signalized junctions`);
      } else {
        toast.error('No junctions found in the network');
      }
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to prepare network');
    } finally {
      setIsPreparing(false);
    }
  };

  const handleStartTraining = async () => {
    if (!networkId || !tlId) return;

    setIsLoading(true);

    try {
      const result = await taskService.createTrainingTask({
        network_id: networkId,
        traffic_light_id: tlId,
        algorithm: algorithm.toUpperCase() as 'DQN' | 'PPO',
        total_timesteps: totalTimesteps,
      });
      toast.success(`Training task created! View progress in Tasks tab (ID: ${result.task_id.slice(0, 8)}...)`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to create training task');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="bg-white rounded-lg shadow p-4">
      <h3 className="text-lg font-semibold mb-4 flex items-center gap-2">
        <Brain size={20} />
        Training
      </h3>

      {/* Info text explaining training */}
      <div className="mb-4 p-3 bg-blue-50 rounded-md flex gap-2">
        <Info size={16} className="text-blue-600 flex-shrink-0 mt-0.5" />
        <p className="text-xs text-blue-700">
          Training uses reinforcement learning to optimize traffic light timing at the selected junction.
          The agent learns to minimize vehicle waiting times by adjusting signal phases.
        </p>
      </div>

      {/* Traffic light selector */}
      <div className="mb-4">
        <label className="block text-sm font-medium text-gray-700 mb-1">
          Traffic Light Junction
        </label>
        <select
          value={tlId ?? ''}
          onChange={(e) => setTlId(e.target.value || null)}
          className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
          disabled={!networkId || signalizedJunctions.length === 0}
        >
          <option value="">Select a junction</option>
          {signalizedJunctions.map((junction) => (
            <option key={junction.tl_id} value={junction.tl_id!}>
              {junction.tl_id} ({junction.name || `Junction ${junction.id}`})
            </option>
          ))}
        </select>
        {signalizedJunctions.length === 0 && networkId && (
          <div className="mt-2">
            <p className="text-xs text-amber-600 mb-2">
              No signalized junctions found. Click below to prepare the network.
            </p>
            <button
              onClick={handlePrepareNetwork}
              disabled={isPreparing}
              className="w-full flex items-center justify-center gap-2 px-3 py-1.5 text-sm bg-amber-100 text-amber-700 rounded hover:bg-amber-200 disabled:opacity-50"
            >
              <RefreshCw size={14} className={isPreparing ? 'animate-spin' : ''} />
              {isPreparing ? 'Preparing...' : 'Prepare Network for Training'}
            </button>
          </div>
        )}
      </div>

      {/* Algorithm selector */}
      <div className="mb-4">
        <label className="block text-sm font-medium text-gray-700 mb-1">
          Algorithm
        </label>
        <select
          value={algorithm}
          onChange={(e) => setAlgorithm(e.target.value as TrainingAlgorithm)}
          className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="dqn">DQN (Deep Q-Network)</option>
          <option value="ppo">PPO (Proximal Policy Optimization)</option>
        </select>
      </div>

      {/* Timesteps input */}
      <div className="mb-4">
        <label className="block text-sm font-medium text-gray-700 mb-1">
          Total Timesteps
        </label>
        <input
          type="number"
          value={totalTimesteps}
          onChange={(e) => setTotalTimesteps(Math.max(100, Math.min(100000, parseInt(e.target.value) || 100)))}
          min={100}
          max={100000}
          step={1000}
          className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        <p className="text-xs text-gray-500 mt-1">Range: 100 - 100,000</p>
      </div>

      {/* Start button */}
      <button
        onClick={handleStartTraining}
        disabled={isLoading || !networkId || !tlId}
        className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed"
      >
        <Play size={16} />
        {isLoading ? 'Creating Task...' : 'Start Training'}
      </button>

      {!networkId && (
        <p className="text-sm text-gray-500 mt-2">
          Extract a network first to start training
        </p>
      )}

      <p className="text-xs text-gray-500 mt-3">
        Training runs in background. View progress in the Tasks tab.
      </p>
    </div>
  );
}
