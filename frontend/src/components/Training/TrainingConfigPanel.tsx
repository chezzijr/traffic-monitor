import { useState } from 'react';
import { Play, Loader2 } from 'lucide-react';
import toast from 'react-hot-toast';
import { useMapStore } from '../../store/mapStore';
import { useTrainingStore } from '../../store/trainingStore';
import { trainingService } from '../../services/trainingService';
import type { Algorithm, TrafficScenario } from '../../types';

const SCENARIOS: { value: TrafficScenario; label: string }[] = [
  { value: 'light', label: 'Light' },
  { value: 'moderate', label: 'Moderate' },
  { value: 'heavy', label: 'Heavy' },
  { value: 'rush_hour', label: 'Rush Hour' },
];

interface TrainingConfigPanelProps {
  onTrainingStarted?: (taskId: string) => void;
}

export function TrainingConfigPanel({ onTrainingStarted }: TrainingConfigPanelProps) {
  const currentNetworkId = useMapStore((s) => s.currentNetworkId);
  const selectedJunctionIds = useMapStore((s) => s.selectedJunctionIds);

  const algorithm = useTrainingStore((s) => s.algorithm);
  const totalTimesteps = useTrainingStore((s) => s.totalTimesteps);
  const scenario = useTrainingStore((s) => s.scenario);
  const setAlgorithm = useTrainingStore((s) => s.setAlgorithm);
  const setTotalTimesteps = useTrainingStore((s) => s.setTotalTimesteps);
  const setScenario = useTrainingStore((s) => s.setScenario);
  const addTask = useTrainingStore((s) => s.addTask);

  const [isSubmitting, setIsSubmitting] = useState(false);

  const junctionCount = selectedJunctionIds.length;
  const canStart = junctionCount > 0 && currentNetworkId && !isSubmitting;

  const handleStartTraining = async () => {
    if (!canStart || !currentNetworkId) return;
    setIsSubmitting(true);

    try {
      let response;
      if (junctionCount === 1) {
        response = await trainingService.startSingleTraining({
          network_id: currentNetworkId,
          tl_id: selectedJunctionIds[0],
          algorithm,
          total_timesteps: totalTimesteps,
          scenario,
        });
      } else {
        response = await trainingService.startMultiTraining({
          network_id: currentNetworkId,
          tl_ids: selectedJunctionIds,
          algorithm,
          total_timesteps: totalTimesteps,
          scenario,
        });
      }

      addTask({
        task_id: response.task_id,
        status: 'queued',
        network_id: currentNetworkId,
        algorithm,
        tl_ids: selectedJunctionIds,
        total_timesteps: totalTimesteps,
        progress: 0,
      });

      toast.success(`Training started for ${junctionCount} junction${junctionCount > 1 ? 's' : ''}`);
      onTrainingStarted?.(response.task_id);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to start training';
      toast.error(msg);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-3 space-y-3">
      <h3 className="text-sm font-semibold text-gray-700">Training Config</h3>

      {/* Algorithm toggle */}
      <div>
        <label className="text-xs text-gray-500 mb-1 block">Algorithm</label>
        <div className="flex rounded-lg border border-gray-200 overflow-hidden">
          {(['dqn', 'ppo', 'colight'] as Algorithm[]).map((alg) => (
            <button
              key={alg}
              onClick={() => setAlgorithm(alg)}
              className={`flex-1 py-1.5 text-xs font-medium transition-colors ${
                algorithm === alg
                  ? alg === 'colight' ? 'bg-amber-500 text-white' : 'bg-blue-500 text-white'
                  : 'bg-white text-gray-600 hover:bg-gray-50'
              }`}
            >
              {alg === 'colight' ? 'CoLight' : alg.toUpperCase()}
            </button>
          ))}
        </div>
      </div>

      {/* Timesteps slider */}
      <div>
        <label className="text-xs text-gray-500 mb-1 flex items-center justify-between">
          <span>Timesteps</span>
          <span className="font-mono text-gray-700">{totalTimesteps.toLocaleString()}</span>
        </label>
        <input
          type="range"
          min={1000}
          max={500000}
          step={1000}
          value={totalTimesteps}
          onChange={(e) => setTotalTimesteps(Number(e.target.value))}
          className="w-full accent-blue-500"
        />
        <div className="flex justify-between text-[10px] text-gray-400">
          <span>1K</span>
          <span>500K</span>
        </div>
      </div>

      {/* Scenario dropdown */}
      <div>
        <label className="text-xs text-gray-500 mb-1 block">Scenario</label>
        <select
          value={scenario}
          onChange={(e) => setScenario(e.target.value as TrafficScenario)}
          className="w-full text-sm border border-gray-200 rounded-lg px-2 py-1.5 bg-white text-gray-700"
        >
          {SCENARIOS.map((s) => (
            <option key={s.value} value={s.value}>
              {s.label}
            </option>
          ))}
        </select>
      </div>

      {/* Start button */}
      <button
        onClick={handleStartTraining}
        disabled={!canStart}
        className={`w-full flex items-center justify-center gap-2 py-2 rounded-lg text-sm font-medium transition-colors ${
          canStart
            ? 'bg-green-500 text-white hover:bg-green-600'
            : 'bg-gray-200 text-gray-400 cursor-not-allowed'
        }`}
      >
        {isSubmitting ? (
          <Loader2 size={14} className="animate-spin" />
        ) : (
          <Play size={14} />
        )}
        {isSubmitting
          ? 'Starting...'
          : `Train ${junctionCount} Junction${junctionCount !== 1 ? 's' : ''}`}
      </button>
    </div>
  );
}
