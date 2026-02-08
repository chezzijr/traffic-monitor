import { useState, useEffect } from 'react';
import { Play, Square, Brain } from 'lucide-react';
import { useMLStore } from '../../store/mlStore';
import { useMapStore } from '../../store/mapStore';
import { mlService } from '../../services/mlService';
import { connectTrainingSSE, disconnectTrainingSSE } from '../../services/trainingSSE';
import type { TrainingAlgorithm } from '../../types/ml';

export function TrainingPanel() {
  const [tlId, setTlId] = useState('');
  const [algorithm, setAlgorithm] = useState<TrainingAlgorithm>('dqn');
  const [totalTimesteps, setTotalTimesteps] = useState(10000);
  const [isLoading, setIsLoading] = useState(false);

  const networkId = useMapStore((state) => state.currentNetworkId);
  const intersections = useMapStore((state) => state.intersections);
  const { trainingStatus, trainingJob, setError } = useMLStore();

  // Get traffic lights from intersections
  const trafficLights = intersections.filter((i) => i.has_traffic_light && i.sumo_tl_id);

  const isTraining = trainingStatus === 'running' || trainingStatus === 'stopping';
  const isCompleted = trainingStatus === 'completed';
  const isFailed = trainingStatus === 'failed';

  // Cleanup SSE on unmount
  useEffect(() => {
    return () => {
      disconnectTrainingSSE();
    };
  }, []);

  const handleStartTraining = async () => {
    if (!networkId || !tlId) return;

    setIsLoading(true);
    setError(null);

    try {
      await mlService.startTraining({
        network_id: networkId,
        tl_id: tlId,
        algorithm,
        total_timesteps: totalTimesteps,
      });
      connectTrainingSSE();
    } catch (error) {
      setError(error instanceof Error ? error.message : 'Failed to start training');
    } finally {
      setIsLoading(false);
    }
  };

  const handleStopTraining = async () => {
    setIsLoading(true);
    try {
      await mlService.stopTraining();
    } catch (error) {
      setError(error instanceof Error ? error.message : 'Failed to stop training');
    } finally {
      setIsLoading(false);
    }
  };

  const progressPercent = trainingJob ? Math.round(trainingJob.progress * 100) : 0;

  return (
    <div className="bg-white rounded-lg shadow p-4">
      <h3 className="text-lg font-semibold mb-4 flex items-center gap-2">
        <Brain size={20} />
        Training
      </h3>

      {/* Training configuration - show when not training */}
      {!isTraining && (
        <>
          {/* Traffic light selector */}
          <div className="mb-4">
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Traffic Light
            </label>
            <select
              value={tlId}
              onChange={(e) => setTlId(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
              disabled={!networkId || trafficLights.length === 0}
            >
              <option value="">Select a traffic light</option>
              {trafficLights.map((tl) => (
                <option key={tl.sumo_tl_id} value={tl.sumo_tl_id}>
                  {tl.sumo_tl_id} {tl.name ? `(${tl.name})` : ''}
                </option>
              ))}
            </select>
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
            Start Training
          </button>
        </>
      )}

      {/* Training progress - show when training */}
      {isTraining && trainingJob && (
        <>
          <div className="mb-4">
            <div className="flex justify-between text-sm mb-1">
              <span>Progress</span>
              <span>{progressPercent}%</span>
            </div>
            <div className="w-full bg-gray-200 rounded-full h-2">
              <div
                className="bg-blue-500 h-2 rounded-full transition-all"
                style={{ width: `${progressPercent}%` }}
              />
            </div>
          </div>

          <div className="text-sm space-y-1 mb-4">
            <p>TL: {trainingJob.tl_id}</p>
            <p>Step: {trainingJob.current_timestep} / {trainingJob.total_timesteps}</p>
            <p>Episodes: {trainingJob.total_episodes}</p>
            <p>Mean Reward: {trainingJob.mean_reward.toFixed(2)}</p>
          </div>

          <button
            onClick={handleStopTraining}
            disabled={isLoading || trainingStatus === 'stopping'}
            className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-red-500 text-white rounded hover:bg-red-600 disabled:opacity-50"
          >
            <Square size={16} />
            {trainingStatus === 'stopping' ? 'Stopping...' : 'Stop Training'}
          </button>
        </>
      )}

      {/* Completion message */}
      {isCompleted && trainingJob && (
        <div className="p-3 bg-green-50 border border-green-200 rounded">
          <p className="text-green-700 font-medium">Training Complete!</p>
          <p className="text-sm text-green-600">Model saved: {trainingJob.model_path?.split('/').pop()}</p>
        </div>
      )}

      {/* Error message */}
      {isFailed && trainingJob?.error_message && (
        <div className="p-3 bg-red-50 border border-red-200 rounded">
          <p className="text-red-700 font-medium">Training Failed</p>
          <p className="text-sm text-red-600">{trainingJob.error_message}</p>
        </div>
      )}

      {!networkId && (
        <p className="text-sm text-gray-500 mt-2">
          Extract a network first to start training
        </p>
      )}
    </div>
  );
}
