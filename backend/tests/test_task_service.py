"""Tests for task service module."""

import json
from datetime import datetime
from unittest.mock import MagicMock, patch, call

import pytest


class TestCreateTrainingTask:
    """Tests for create_training_task function."""

    def test_dispatches_celery_task(self):
        """create_training_task should dispatch a Celery task."""
        from app.services.task_service import create_training_task

        with patch("app.services.task_service.train_traffic_light") as mock_task:
            mock_async = MagicMock()
            mock_async.id = "celery-task-123"
            mock_task.delay.return_value = mock_async

            with patch("app.services.task_service.get_redis_client") as mock_redis:
                mock_redis.return_value = MagicMock()

                result = create_training_task(
                    network_id="test_network",
                    tl_id="tl_1",
                    algorithm="dqn",
                    total_timesteps=10000,
                )

        mock_task.delay.assert_called_once_with(
            network_id="test_network",
            traffic_light_id="tl_1",
            algorithm="dqn",
            total_timesteps=10000,
            scenario="moderate",
        )
        assert result["task_id"] == "celery-task-123"
        assert result["status"] == "PENDING"

    def test_stores_task_metadata_in_redis(self):
        """create_training_task should store task metadata in Redis."""
        from app.services.task_service import create_training_task

        with patch("app.services.task_service.train_traffic_light") as mock_task:
            mock_async = MagicMock()
            mock_async.id = "celery-task-456"
            mock_task.delay.return_value = mock_async

            with patch("app.services.task_service.get_redis_client") as mock_redis:
                redis_mock = MagicMock()
                mock_redis.return_value = redis_mock

                create_training_task(
                    network_id="test_network",
                    tl_id="tl_2",
                    algorithm="ppo",
                    total_timesteps=5000,
                )

        # Verify Redis set was called with metadata
        redis_mock.set.assert_called_once()
        call_args = redis_mock.set.call_args
        key = call_args[0][0]
        value = call_args[0][1]

        assert key == "task:celery-task-456:meta"
        metadata = json.loads(value)
        assert metadata["network_id"] == "test_network"
        assert metadata["tl_id"] == "tl_2"
        assert metadata["algorithm"] == "ppo"
        assert metadata["total_timesteps"] == 5000
        assert "created_at" in metadata

    def test_adds_task_id_to_list(self):
        """create_training_task should add task ID to the task list."""
        from app.services.task_service import create_training_task

        with patch("app.services.task_service.train_traffic_light") as mock_task:
            mock_async = MagicMock()
            mock_async.id = "celery-task-789"
            mock_task.delay.return_value = mock_async

            with patch("app.services.task_service.get_redis_client") as mock_redis:
                redis_mock = MagicMock()
                mock_redis.return_value = redis_mock

                create_training_task(
                    network_id="test_network",
                    tl_id="tl_1",
                    algorithm="dqn",
                    total_timesteps=10000,
                )

        # Verify task ID added to list
        redis_mock.lpush.assert_called_once_with("tasks:list", "celery-task-789")


class TestGetTask:
    """Tests for get_task function."""

    def test_returns_task_status_and_metadata(self):
        """get_task should return task status and metadata."""
        from app.services.task_service import get_task

        with patch("app.services.task_service.AsyncResult") as mock_async:
            mock_result = MagicMock()
            mock_result.state = "STARTED"
            mock_result.info = {"progress": 0.5}
            mock_async.return_value = mock_result

            with patch("app.services.task_service.get_redis_client") as mock_redis:
                redis_mock = MagicMock()
                # get() called twice: metadata key, then progress key
                redis_mock.get.side_effect = [
                    json.dumps({
                        "network_id": "test_network",
                        "tl_id": "tl_1",
                        "algorithm": "dqn",
                        "total_timesteps": 10000,
                        "created_at": "2024-01-01T00:00:00",
                    }),
                    json.dumps({
                        "progress": 0.5,
                        "timestep": 5000,
                        "avg_waiting_time": 15.2,
                        "avg_queue_length": 3.4,
                    }),
                ]
                mock_redis.return_value = redis_mock

                result = get_task("celery-task-123")

        assert result is not None
        assert result["task_id"] == "celery-task-123"
        assert result["status"] == "STARTED"
        assert result["metadata"]["network_id"] == "test_network"
        assert result["info"]["progress"] == 0.5
        assert result["info"]["avg_waiting_time"] == 15.2
        assert result["info"]["avg_queue_length"] == 3.4

    def test_returns_none_for_missing_task(self):
        """get_task should return None if task doesn't exist."""
        from app.services.task_service import get_task

        with patch("app.services.task_service.AsyncResult") as mock_async:
            mock_result = MagicMock()
            mock_result.state = "PENDING"
            mock_result.info = None
            mock_async.return_value = mock_result

            with patch("app.services.task_service.get_redis_client") as mock_redis:
                redis_mock = MagicMock()
                redis_mock.get.return_value = None  # No metadata
                mock_redis.return_value = redis_mock

                result = get_task("nonexistent-task")

        # Task with PENDING state and no metadata = doesn't exist
        assert result is None

    def test_handles_completed_task_with_traffic_metrics(self):
        """get_task should return traffic metrics and baseline for completed task."""
        from app.services.task_service import get_task

        with patch("app.services.task_service.AsyncResult") as mock_async:
            mock_result = MagicMock()
            mock_result.state = "SUCCESS"
            mock_result.info = {"model_path": "/models/test.zip", "status": "completed"}
            mock_async.return_value = mock_result

            with patch("app.services.task_service.get_redis_client") as mock_redis:
                redis_mock = MagicMock()
                redis_mock.get.side_effect = [
                    json.dumps({
                        "network_id": "test_network",
                        "tl_id": "tl_1",
                        "algorithm": "dqn",
                        "total_timesteps": 10000,
                        "created_at": "2024-01-01T00:00:00",
                    }),
                    json.dumps({
                        "progress": 1.0,
                        "model_path": "/models/test.zip",
                        "avg_waiting_time": 12.3,
                        "avg_queue_length": 2.1,
                        "throughput": 847.0,
                        "baseline_avg_waiting_time": 28.1,
                        "baseline_avg_queue_length": 5.8,
                        "baseline_throughput": 612.0,
                    }),
                ]
                mock_redis.return_value = redis_mock

                result = get_task("completed-task")

        assert result is not None
        assert result["status"] == "SUCCESS"
        assert result["info"]["model_path"] == "/models/test.zip"
        assert result["info"]["avg_waiting_time"] == 12.3
        assert result["info"]["avg_queue_length"] == 2.1
        assert result["info"]["throughput"] == 847.0
        assert result["info"]["baseline_avg_waiting_time"] == 28.1
        assert result["info"]["baseline_avg_queue_length"] == 5.8
        assert result["info"]["baseline_throughput"] == 612.0

    def test_handles_failed_task(self):
        """get_task should handle failed task with error."""
        from app.services.task_service import get_task

        with patch("app.services.task_service.AsyncResult") as mock_async:
            mock_result = MagicMock()
            mock_result.state = "FAILURE"
            mock_result.info = Exception("Training failed")
            mock_async.return_value = mock_result

            with patch("app.services.task_service.get_redis_client") as mock_redis:
                redis_mock = MagicMock()
                # get() called twice: metadata key, then progress key
                redis_mock.get.side_effect = [
                    json.dumps({
                        "network_id": "test_network",
                        "tl_id": "tl_1",
                        "algorithm": "dqn",
                        "total_timesteps": 10000,
                        "created_at": "2024-01-01T00:00:00",
                    }),
                    None,  # No progress data for failed task
                ]
                mock_redis.return_value = redis_mock

                result = get_task("failed-task")

        assert result is not None
        assert result["status"] == "FAILURE"
        assert "error" in result


class TestListTasks:
    """Tests for list_tasks function."""

    def test_returns_all_tasks(self):
        """list_tasks should return all tasks from Redis list."""
        from app.services.task_service import list_tasks

        with patch("app.services.task_service.AsyncResult") as mock_async:
            def async_side_effect(task_id, app=None):
                mock = MagicMock()
                if task_id == "task-1":
                    mock.state = "STARTED"
                    mock.info = {"progress": 0.5}
                elif task_id == "task-2":
                    mock.state = "SUCCESS"
                    mock.info = {"model_path": "/models/test.zip"}
                else:
                    mock.state = "PENDING"
                    mock.info = None
                return mock

            mock_async.side_effect = async_side_effect

            with patch("app.services.task_service.get_redis_client") as mock_redis:
                redis_mock = MagicMock()
                redis_mock.lrange.return_value = [b"task-1", b"task-2"]
                # get() called 4 times: meta1, progress1, meta2, progress2
                redis_mock.get.side_effect = [
                    json.dumps({"network_id": "net1", "tl_id": "tl1", "algorithm": "dqn", "total_timesteps": 10000, "created_at": "2024-01-01"}),
                    json.dumps({"progress": 0.5, "timestep": 5000}),
                    json.dumps({"network_id": "net2", "tl_id": "tl2", "algorithm": "ppo", "total_timesteps": 5000, "created_at": "2024-01-02"}),
                    json.dumps({"progress": 1.0, "model_path": "/models/test.zip", "avg_waiting_time": 12.3, "baseline_avg_waiting_time": 28.1}),
                ]
                mock_redis.return_value = redis_mock

                result = list_tasks()

        assert len(result) == 2
        assert result[0]["task_id"] == "task-1"
        assert result[0]["status"] == "STARTED"
        assert result[1]["task_id"] == "task-2"
        assert result[1]["status"] == "SUCCESS"
        assert result[1]["info"]["avg_waiting_time"] == 12.3
        assert result[1]["info"]["baseline_avg_waiting_time"] == 28.1

    def test_returns_empty_list_when_no_tasks(self):
        """list_tasks should return empty list when no tasks exist."""
        from app.services.task_service import list_tasks

        with patch("app.services.task_service.get_redis_client") as mock_redis:
            redis_mock = MagicMock()
            redis_mock.lrange.return_value = []
            mock_redis.return_value = redis_mock

            result = list_tasks()

        assert result == []

    def test_filters_by_status(self):
        """list_tasks should filter by status when specified."""
        from app.services.task_service import list_tasks

        with patch("app.services.task_service.AsyncResult") as mock_async:
            def async_side_effect(task_id, app=None):
                mock = MagicMock()
                if task_id == "task-1":
                    mock.state = "STARTED"
                    mock.info = {}
                elif task_id == "task-2":
                    mock.state = "SUCCESS"
                    mock.info = {}
                else:
                    mock.state = "PENDING"
                    mock.info = None
                return mock

            mock_async.side_effect = async_side_effect

            with patch("app.services.task_service.get_redis_client") as mock_redis:
                redis_mock = MagicMock()
                redis_mock.lrange.return_value = [b"task-1", b"task-2"]
                # get() called per task: meta + progress
                # task-1 (STARTED) matches filter, so gets both calls
                # task-2 (SUCCESS) doesn't match STARTED filter, but get() is still called for metadata and progress
                redis_mock.get.side_effect = [
                    json.dumps({"network_id": "net1", "tl_id": "tl1", "algorithm": "dqn", "total_timesteps": 10000, "created_at": "2024-01-01"}),
                    json.dumps({"progress": 0.5}),
                    json.dumps({"network_id": "net2", "tl_id": "tl2", "algorithm": "ppo", "total_timesteps": 5000, "created_at": "2024-01-02"}),
                    json.dumps({"progress": 1.0}),
                ]
                mock_redis.return_value = redis_mock

                result = list_tasks(status="STARTED")

        assert len(result) == 1
        assert result[0]["task_id"] == "task-1"


class TestCancelTask:
    """Tests for cancel_task function."""

    def test_revokes_celery_task(self):
        """cancel_task should revoke the Celery task."""
        from app.services.task_service import cancel_task

        with patch("app.services.task_service.AsyncResult") as mock_async:
            mock_result = MagicMock()
            mock_result.state = "STARTED"
            mock_async.return_value = mock_result

            result = cancel_task("task-123")

        mock_result.revoke.assert_called_once_with(terminate=True)
        assert result["status"] == "cancelled"
        assert result["task_id"] == "task-123"

    def test_raises_for_completed_task(self):
        """cancel_task should raise error for completed task."""
        from app.services.task_service import cancel_task

        with patch("app.services.task_service.AsyncResult") as mock_async:
            mock_result = MagicMock()
            mock_result.state = "SUCCESS"
            mock_async.return_value = mock_result

            with pytest.raises(ValueError, match="Cannot cancel completed task"):
                cancel_task("completed-task")

    def test_raises_for_failed_task(self):
        """cancel_task should raise error for failed task."""
        from app.services.task_service import cancel_task

        with patch("app.services.task_service.AsyncResult") as mock_async:
            mock_result = MagicMock()
            mock_result.state = "FAILURE"
            mock_async.return_value = mock_result

            with pytest.raises(ValueError, match="Cannot cancel failed task"):
                cancel_task("failed-task")


class TestDeleteTask:
    """Tests for delete_task function."""

    def test_removes_task_metadata_from_redis(self):
        """delete_task should remove task metadata from Redis."""
        from app.services.task_service import delete_task

        with patch("app.services.task_service.AsyncResult") as mock_async:
            mock_result = MagicMock()
            mock_result.state = "SUCCESS"
            mock_async.return_value = mock_result

            with patch("app.services.task_service.get_redis_client") as mock_redis:
                redis_mock = MagicMock()
                mock_redis.return_value = redis_mock

                result = delete_task("task-123")

        redis_mock.delete.assert_called_with("task:task-123:meta")
        assert result["status"] == "deleted"

    def test_removes_task_from_list(self):
        """delete_task should remove task ID from task list."""
        from app.services.task_service import delete_task

        with patch("app.services.task_service.AsyncResult") as mock_async:
            mock_result = MagicMock()
            mock_result.state = "SUCCESS"
            mock_async.return_value = mock_result

            with patch("app.services.task_service.get_redis_client") as mock_redis:
                redis_mock = MagicMock()
                mock_redis.return_value = redis_mock

                delete_task("task-456")

        redis_mock.lrem.assert_called_with("tasks:list", 0, "task-456")

    def test_raises_for_running_task(self):
        """delete_task should raise error for running task."""
        from app.services.task_service import delete_task

        with patch("app.services.task_service.AsyncResult") as mock_async:
            mock_result = MagicMock()
            mock_result.state = "STARTED"
            mock_async.return_value = mock_result

            with pytest.raises(ValueError, match="Cannot delete running task"):
                delete_task("running-task")


class TestCleanupStaleTasks:
    """Tests for cleanup_stale_tasks function."""

    def test_removes_stale_tasks(self):
        """cleanup_stale_tasks should remove tasks with no Celery state."""
        from app.services.task_service import cleanup_stale_tasks

        with patch("app.services.task_service.AsyncResult") as mock_async:
            def async_side_effect(task_id, app=None):
                mock = MagicMock()
                if task_id == "valid-task":
                    mock.state = "SUCCESS"
                else:
                    mock.state = "PENDING"  # Unknown/stale
                mock.info = None
                return mock

            mock_async.side_effect = async_side_effect

            with patch("app.services.task_service.get_redis_client") as mock_redis:
                redis_mock = MagicMock()
                redis_mock.lrange.return_value = [b"valid-task", b"stale-task"]
                redis_mock.get.side_effect = [
                    json.dumps({"network_id": "net1", "tl_id": "tl1", "algorithm": "dqn", "total_timesteps": 10000, "created_at": "2024-01-01"}),
                    None,  # Stale task has no metadata
                ]
                mock_redis.return_value = redis_mock

                result = cleanup_stale_tasks()

        # Should have removed stale-task
        redis_mock.lrem.assert_called_with("tasks:list", 0, "stale-task")
        assert result["removed"] == 1
