import { useState } from 'react';
import toast from 'react-hot-toast';
import { Play, Brain } from 'lucide-react';
import { useMapStore } from '../../store/mapStore';
import { taskService } from '../../services/taskService';
import type { TrainingAlgorithm } from '../../types/ml';

export function TrainingPanel() {
  const [algorithm, setAlgorithm] = useState<TrainingAlgorithm>('dqn');
  const [totalTimesteps, setTotalTimesteps] = useState(10000);
  const [isLoading, setIsLoading] = useState(false);

  const networkId = useMapStore((state) => state.currentNetworkId);
  const intersections = useMapStore((state) => state.intersections);
  const tlId = useMapStore((state) => state.selectedTrafficLightId);
  const setTlId = useMapStore((state) => state.setSelectedTrafficLightId);

  // Get traffic lights from intersections (all TLs, not just those with SUMO IDs)
  const trafficLights = intersections.filter((i) => i.has_traffic_light);
  // Only TLs with SUMO IDs can be used for training
  const usableTrafficLights = trafficLights.filter((i) => i.sumo_tl_id);

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

      {/* Traffic light selector */}
      <div className="mb-4">
        <label className="block text-sm font-medium text-gray-700 mb-1">
          Traffic Light
        </label>
        <select
          value={tlId ?? ''}
          onChange={(e) => setTlId(e.target.value || null)}
          className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
          disabled={!networkId || usableTrafficLights.length === 0}
        >
          <option value="">Select a traffic light</option>
          {trafficLights.map((tl) => (
            <option
              key={tl.sumo_tl_id ?? tl.id}
              value={tl.sumo_tl_id ?? ''}
              disabled={!tl.sumo_tl_id}
            >
              {tl.sumo_tl_id
                ? `${tl.sumo_tl_id} ${tl.name ? `(${tl.name})` : ''}`
                : `${tl.name || `Intersection ${tl.id}`} (not available)`}
            </option>
          ))}
        </select>
        {usableTrafficLights.length === 0 && networkId && (
          <p className="text-xs text-amber-600 mt-1">
            No traffic lights with SUMO IDs found. Network may need re-extraction.
          </p>
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
