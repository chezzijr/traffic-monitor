import { useEffect, useCallback, useState } from 'react';
import { ListTodo, RefreshCw, Inbox } from 'lucide-react';
import { useTaskStore } from '../../store/taskStore';
import { taskService } from '../../services/taskService';
import {
  subscribeToTask,
  unsubscribeFromTask,
  isTaskSubscriptionActive,
  unsubscribeFromAllTasks,
} from '../../services/taskSSE';
import { TaskCard } from './TaskCard';
import type { Task } from '../../types';

export function TaskListPanel() {
  const [cancellingTaskId, setCancellingTaskId] = useState<string | null>(null);

  const {
    tasks,
    isLoading,
    error,
    setTasks,
    setLoading,
    setError,
    updateTask,
  } = useTaskStore();

  // Fetch tasks from API
  const fetchTasks = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await taskService.listTasks();
      setTasks(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch tasks');
    } finally {
      setLoading(false);
    }
  }, [setTasks, setLoading, setError]);

  // Load tasks on mount
  useEffect(() => {
    fetchTasks();

    // Cleanup SSE connections on unmount
    return () => {
      unsubscribeFromAllTasks();
    };
  }, [fetchTasks]);

  // Subscribe to running/pending tasks for real-time updates
  useEffect(() => {
    const activeTasks = tasks.filter(
      (task) => task.status === 'running' || task.status === 'pending'
    );

    // Subscribe to new active tasks
    for (const task of activeTasks) {
      if (!isTaskSubscriptionActive(task.task_id)) {
        subscribeToTask(task.task_id);
      }
    }

    // Unsubscribe from completed/failed/cancelled tasks
    const inactiveTaskIds = tasks
      .filter(
        (task) =>
          task.status === 'completed' ||
          task.status === 'failed' ||
          task.status === 'cancelled'
      )
      .map((task) => task.task_id);

    for (const taskId of inactiveTaskIds) {
      if (isTaskSubscriptionActive(taskId)) {
        unsubscribeFromTask(taskId);
      }
    }
  }, [tasks]);

  // Handle task cancellation
  const handleCancelTask = async (taskId: string) => {
    setCancellingTaskId(taskId);
    try {
      await taskService.cancelTask(taskId);
      // Update local state immediately
      updateTask(taskId, { status: 'cancelled' });
      // Unsubscribe from SSE
      unsubscribeFromTask(taskId);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to cancel task');
    } finally {
      setCancellingTaskId(null);
    }
  };

  // Group tasks by status
  const runningTasks = tasks.filter((task) => task.status === 'running');
  const pendingTasks = tasks.filter((task) => task.status === 'pending');
  const completedTasks = tasks.filter(
    (task) =>
      task.status === 'completed' ||
      task.status === 'failed' ||
      task.status === 'cancelled'
  );

  // Sort completed tasks by completion date (newest first)
  completedTasks.sort((a, b) => {
    const dateA = a.completed_at ? new Date(a.completed_at).getTime() : 0;
    const dateB = b.completed_at ? new Date(b.completed_at).getTime() : 0;
    return dateB - dateA;
  });

  const isEmpty = tasks.length === 0;

  return (
    <div className="bg-white rounded-lg shadow p-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold flex items-center gap-2">
          <ListTodo size={20} />
          Training Tasks
        </h3>
        <button
          onClick={fetchTasks}
          disabled={isLoading}
          className="p-2 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded"
          title="Refresh tasks"
        >
          <RefreshCw size={16} className={isLoading ? 'animate-spin' : ''} />
        </button>
      </div>

      {/* Error display */}
      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Loading state */}
      {isLoading && isEmpty && (
        <p className="text-sm text-gray-500">Loading tasks...</p>
      )}

      {/* Empty state */}
      {!isLoading && isEmpty && (
        <div className="py-8 text-center text-gray-500">
          <Inbox size={40} className="mx-auto mb-2 opacity-50" />
          <p className="text-sm">No training tasks yet</p>
          <p className="text-xs mt-1">
            Start a training job from the Training panel
          </p>
        </div>
      )}

      {/* Task lists */}
      {!isEmpty && (
        <div className="space-y-4">
          {/* Running tasks */}
          {runningTasks.length > 0 && (
            <TaskSection
              title="Running"
              count={runningTasks.length}
              tasks={runningTasks}
              onCancel={handleCancelTask}
              cancellingTaskId={cancellingTaskId}
            />
          )}

          {/* Pending tasks */}
          {pendingTasks.length > 0 && (
            <TaskSection
              title="Pending"
              count={pendingTasks.length}
              tasks={pendingTasks}
              onCancel={handleCancelTask}
              cancellingTaskId={cancellingTaskId}
            />
          )}

          {/* Completed tasks */}
          {completedTasks.length > 0 && (
            <TaskSection
              title="Completed"
              count={completedTasks.length}
              tasks={completedTasks}
              onCancel={handleCancelTask}
              cancellingTaskId={cancellingTaskId}
              collapsible
            />
          )}
        </div>
      )}
    </div>
  );
}

interface TaskSectionProps {
  title: string;
  count: number;
  tasks: Task[];
  onCancel: (taskId: string) => void;
  cancellingTaskId: string | null;
  collapsible?: boolean;
}

function TaskSection({
  title,
  count,
  tasks,
  onCancel,
  cancellingTaskId,
  collapsible = false,
}: TaskSectionProps) {
  const [isCollapsed, setIsCollapsed] = useState(false);

  return (
    <div>
      <button
        className={`flex items-center gap-2 text-sm font-medium text-gray-700 mb-2 ${
          collapsible ? 'cursor-pointer hover:text-gray-900' : 'cursor-default'
        }`}
        onClick={() => collapsible && setIsCollapsed(!isCollapsed)}
        disabled={!collapsible}
      >
        <span>{title}</span>
        <span className="text-xs bg-gray-200 px-1.5 py-0.5 rounded-full">
          {count}
        </span>
        {collapsible && (
          <span className="text-xs text-gray-500">
            {isCollapsed ? '(show)' : '(hide)'}
          </span>
        )}
      </button>

      {!isCollapsed && (
        <div className="space-y-2">
          {tasks.map((task) => (
            <TaskCard
              key={task.task_id}
              task={task}
              onCancel={onCancel}
              isCancelling={cancellingTaskId === task.task_id}
            />
          ))}
        </div>
      )}
    </div>
  );
}
