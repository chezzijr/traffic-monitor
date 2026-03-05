import { create } from 'zustand';
import type { Algorithm, TrafficScenario, TaskInfo, TrainingProgressEvent, TrainingCompletionEvent } from '../types';

interface TrainingState {
  // Config
  algorithm: Algorithm;
  totalTimesteps: number;
  scenario: TrafficScenario;

  // Tasks
  tasks: TaskInfo[];
  activeTaskId: string | null;
  liveProgress: Record<string, TrainingProgressEvent>;
  completions: Record<string, TrainingCompletionEvent>;

  // Actions
  setAlgorithm: (algorithm: Algorithm) => void;
  setTotalTimesteps: (timesteps: number) => void;
  setScenario: (scenario: TrafficScenario) => void;
  setTasks: (tasks: TaskInfo[]) => void;
  addTask: (task: TaskInfo) => void;
  setActiveTaskId: (taskId: string | null) => void;
  updateProgress: (taskId: string, progress: TrainingProgressEvent) => void;
  removeProgress: (taskId: string) => void;
  completeTask: (taskId: string, data: TrainingCompletionEvent) => void;
  dismissCompletion: (taskId: string) => void;
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
  completions: {},

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
      tasks: state.tasks.map((t) =>
        t.task_id === taskId
          ? { ...t, progress: progress.progress, status: 'running' as const }
          : t
      ),
    })),
  removeProgress: (taskId) =>
    set((state) => ({
      liveProgress: Object.fromEntries(
        Object.entries(state.liveProgress).filter(([key]) => key !== taskId)
      ),
    })),
  completeTask: (taskId, data) =>
    set((state) => ({
      completions: { ...state.completions, [taskId]: data },
      tasks: state.tasks.map((t) =>
        t.task_id === taskId
          ? { ...t, status: 'completed' as const, progress: 1.0, model_path: data.model_path }
          : t
      ),
    })),
  dismissCompletion: (taskId) =>
    set((state) => {
      const { [taskId]: _, ...remainingCompletions } = state.completions;
      const { [taskId]: __, ...remainingProgress } = state.liveProgress;
      return {
        completions: remainingCompletions,
        liveProgress: remainingProgress,
        activeTaskId: state.activeTaskId === taskId ? null : state.activeTaskId,
      };
    }),
}));
