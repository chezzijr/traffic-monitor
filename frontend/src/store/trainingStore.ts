import { create } from 'zustand';
import type { Algorithm, TrafficScenario, TaskInfo, TrainingProgressEvent } from '../types';

interface TrainingState {
  // Config
  algorithm: Algorithm;
  totalTimesteps: number;
  scenario: TrafficScenario;

  // Tasks
  tasks: TaskInfo[];
  activeTaskId: string | null;
  liveProgress: Record<string, TrainingProgressEvent>;

  // Actions
  setAlgorithm: (algorithm: Algorithm) => void;
  setTotalTimesteps: (timesteps: number) => void;
  setScenario: (scenario: TrafficScenario) => void;
  setTasks: (tasks: TaskInfo[]) => void;
  addTask: (task: TaskInfo) => void;
  setActiveTaskId: (taskId: string | null) => void;
  updateProgress: (taskId: string, progress: TrainingProgressEvent) => void;
  removeProgress: (taskId: string) => void;
}

export const useTrainingStore = create<TrainingState>((set) => ({
  // Config defaults
  algorithm: 'dqn',
  totalTimesteps: 10000,
  scenario: 'moderate',

  // Tasks
  tasks: [],
  activeTaskId: null,
  liveProgress: {},

  // Actions
  setAlgorithm: (algorithm) => set({ algorithm }),
  setTotalTimesteps: (totalTimesteps) => set({ totalTimesteps }),
  setScenario: (scenario) => set({ scenario }),
  setTasks: (tasks) => set({ tasks }),
  addTask: (task) =>
    set((state) => ({ tasks: [task, ...state.tasks] })),
  setActiveTaskId: (activeTaskId) => set({ activeTaskId }),
  updateProgress: (taskId, progress) =>
    set((state) => ({
      liveProgress: { ...state.liveProgress, [taskId]: progress },
    })),
  removeProgress: (taskId) =>
    set((state) => ({
      liveProgress: Object.fromEntries(
        Object.entries(state.liveProgress).filter(([key]) => key !== taskId)
      ),
    })),
}));
