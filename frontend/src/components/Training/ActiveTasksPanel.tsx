import { useTrainingStore } from '../../store/trainingStore';
import { taskService } from '../../services/taskService';
import { TaskCard } from './TaskCard';
import toast from 'react-hot-toast';

interface ActiveTasksPanelProps {
  onTaskSelect?: (taskId: string) => void;
}

export function ActiveTasksPanel({ onTaskSelect }: ActiveTasksPanelProps) {
  const tasks = useTrainingStore((s) => s.tasks);
  const activeTaskId = useTrainingStore((s) => s.activeTaskId);
  const setActiveTaskId = useTrainingStore((s) => s.setActiveTaskId);

  const handleCancel = async (taskId: string) => {
    try {
      await taskService.cancelTask(taskId);
      toast.success('Task cancelled');
    } catch {
      toast.error('Failed to cancel task');
    }
  };

  const handleClick = (taskId: string) => {
    setActiveTaskId(taskId);
    onTaskSelect?.(taskId);
  };

  if (tasks.length === 0) return null;

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-3">
      <h3 className="text-sm font-semibold text-gray-700 mb-2">
        Active Tasks ({tasks.length})
      </h3>
      <div className="space-y-2 max-h-60 overflow-y-auto">
        {tasks.map((task) => (
          <TaskCard
            key={task.task_id}
            task={task}
            isActive={task.task_id === activeTaskId}
            onClick={() => handleClick(task.task_id)}
            onCancel={() => handleCancel(task.task_id)}
          />
        ))}
      </div>
    </div>
  );
}
