import { create } from 'zustand';
import type { Task, TaskStatus } from '../types';

interface TaskState {
  // State
  tasks: Task[];
  isLoading: boolean;
  error: string | null;

  // Actions
  setTasks: (tasks: Task[]) => void;
  addTask: (task: Task) => void;
  updateTask: (taskId: string, updates: Partial<Task>) => void;
  removeTask: (taskId: string) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;

  // Selectors
  getTaskById: (taskId: string) => Task | undefined;
  getTasksByStatus: (status: TaskStatus) => Task[];
  getTasksByNetworkId: (networkId: string) => Task[];

  // Reset
  reset: () => void;
}

const initialState = {
  tasks: [] as Task[],
  isLoading: false,
  error: null as string | null,
};

export const useTaskStore = create<TaskState>((set, get) => ({
  // Initial state
  ...initialState,

  // Actions
  setTasks: (tasks) => set({ tasks }),

  addTask: (task) =>
    set((state) => ({
      tasks: [...state.tasks, task],
    })),

  updateTask: (taskId, updates) =>
    set((state) => ({
      tasks: state.tasks.map((task) =>
        task.task_id === taskId ? { ...task, ...updates } : task
      ),
    })),

  removeTask: (taskId) =>
    set((state) => ({
      tasks: state.tasks.filter((task) => task.task_id !== taskId),
    })),

  setLoading: (loading) => set({ isLoading: loading }),

  setError: (error) => set({ error }),

  // Selectors
  getTaskById: (taskId) => get().tasks.find((task) => task.task_id === taskId),

  getTasksByStatus: (status) =>
    get().tasks.filter((task) => task.status === status),

  getTasksByNetworkId: (networkId) =>
    get().tasks.filter((task) => task.network_id === networkId),

  // Reset
  reset: () => set(initialState),
}));
