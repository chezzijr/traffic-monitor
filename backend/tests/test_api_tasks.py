"""Tests for task management API endpoints."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


class TestCreateTrainingTask:
    """Tests for POST /api/tasks/training endpoint."""

    def test_create_training_task_success(self, client: TestClient):
        """Create training task should return task info on success."""
        mock_result = {
            "task_id": "abc-123-def-456",
            "status": "PENDING",
            "created_at": "2024-01-01T12:00:00",
        }

        with patch("app.services.task_service.create_training_task") as mock_create:
            mock_create.return_value = mock_result

            response = client.post(
                "/api/tasks/training",
                json={
                    "network_id": "test-network",
                    "traffic_light_id": "tl_123",
                    "algorithm": "DQN",
                    "total_timesteps": 10000,
                },
            )

            assert response.status_code == 201
            data = response.json()
            assert data["task_id"] == "abc-123-def-456"
            assert data["status"] == "PENDING"
            assert "created_at" in data

    def test_create_training_task_with_ppo(self, client: TestClient):
        """Create training task with PPO algorithm."""
        mock_result = {
            "task_id": "ppo-task-123",
            "status": "PENDING",
            "created_at": "2024-01-01T12:00:00",
        }

        with patch("app.services.task_service.create_training_task") as mock_create:
            mock_create.return_value = mock_result

            response = client.post(
                "/api/tasks/training",
                json={
                    "network_id": "test-network",
                    "traffic_light_id": "tl_123",
                    "algorithm": "PPO",
                    "total_timesteps": 5000,
                },
            )

            assert response.status_code == 201
            mock_create.assert_called_once()
            call_kwargs = mock_create.call_args[1]
            assert call_kwargs["algorithm"] == "ppo"

    def test_create_training_task_invalid_algorithm(self, client: TestClient):
        """Create training task should fail with invalid algorithm."""
        response = client.post(
            "/api/tasks/training",
            json={
                "network_id": "test-network",
                "traffic_light_id": "tl_123",
                "algorithm": "INVALID",
                "total_timesteps": 10000,
            },
        )

        assert response.status_code == 422

    def test_create_training_task_missing_required_fields(self, client: TestClient):
        """Create training task should fail with missing required fields."""
        response = client.post(
            "/api/tasks/training",
            json={
                "network_id": "test-network",
            },
        )

        assert response.status_code == 422


class TestListTasks:
    """Tests for GET /api/tasks endpoint."""

    def test_list_tasks_empty(self, client: TestClient):
        """List tasks should return empty list when no tasks exist."""
        with patch("app.services.task_service.list_tasks") as mock_list:
            mock_list.return_value = []

            response = client.get("/api/tasks")

            assert response.status_code == 200
            assert response.json() == []

    def test_list_tasks_with_results(self, client: TestClient):
        """List tasks should return task list."""
        mock_tasks = [
            {
                "task_id": "task-1",
                "status": "SUCCESS",
                "metadata": {"network_id": "net-1", "tl_id": "tl-1"},
                "info": {},
            },
            {
                "task_id": "task-2",
                "status": "STARTED",
                "metadata": {"network_id": "net-2", "tl_id": "tl-2"},
                "info": {"progress": 0.5},
            },
        ]

        with patch("app.services.task_service.list_tasks") as mock_list:
            mock_list.return_value = mock_tasks

            response = client.get("/api/tasks")

            assert response.status_code == 200
            data = response.json()
            assert len(data) == 2
            assert data[0]["task_id"] == "task-1"
            # API route maps STARTED → running
            assert data[1]["status"] == "running"

    def test_list_tasks_with_status_filter(self, client: TestClient):
        """List tasks should filter by status."""
        mock_tasks = [
            {
                "task_id": "task-1",
                "status": "SUCCESS",
                "metadata": {},
                "info": {},
            },
        ]

        with patch("app.services.task_service.list_tasks") as mock_list:
            mock_list.return_value = mock_tasks

            response = client.get("/api/tasks?status=SUCCESS")

            assert response.status_code == 200
            mock_list.assert_called_once_with(status="SUCCESS")


class TestGetTask:
    """Tests for GET /api/tasks/{task_id} endpoint."""

    def test_get_task_success(self, client: TestClient):
        """Get task should return task details."""
        mock_task = {
            "task_id": "task-123",
            "status": "SUCCESS",
            "metadata": {
                "network_id": "net-1",
                "tl_id": "tl-1",
                "algorithm": "dqn",
                "total_timesteps": 10000,
            },
            "info": {"model_path": "/models/test.zip"},
        }

        with patch("app.services.task_service.get_task") as mock_get:
            mock_get.return_value = mock_task

            response = client.get("/api/tasks/task-123")

            assert response.status_code == 200
            data = response.json()
            assert data["task_id"] == "task-123"
            # API route maps SUCCESS → completed
            assert data["status"] == "completed"
            assert data["metadata"]["network_id"] == "net-1"

    def test_get_task_not_found(self, client: TestClient):
        """Get task should return 404 for unknown task."""
        with patch("app.services.task_service.get_task") as mock_get:
            mock_get.return_value = None

            response = client.get("/api/tasks/unknown-task-id")

            assert response.status_code == 404
            assert "not found" in response.json()["detail"].lower()


class TestCancelTask:
    """Tests for POST /api/tasks/{task_id}/cancel endpoint."""

    def test_cancel_task_success(self, client: TestClient):
        """Cancel task should succeed for running task."""
        mock_result = {
            "status": "cancelled",
            "task_id": "task-123",
        }

        with patch("app.services.task_service.cancel_task") as mock_cancel:
            mock_cancel.return_value = mock_result

            response = client.post("/api/tasks/task-123/cancel")

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "cancelled"

    def test_cancel_task_already_completed(self, client: TestClient):
        """Cancel task should fail for completed task."""
        with patch("app.services.task_service.cancel_task") as mock_cancel:
            mock_cancel.side_effect = ValueError("Cannot cancel completed task")

            response = client.post("/api/tasks/completed-task/cancel")

            assert response.status_code == 400
            assert "cannot cancel" in response.json()["detail"].lower()

    def test_cancel_task_already_failed(self, client: TestClient):
        """Cancel task should fail for failed task."""
        with patch("app.services.task_service.cancel_task") as mock_cancel:
            mock_cancel.side_effect = ValueError("Cannot cancel failed task")

            response = client.post("/api/tasks/failed-task/cancel")

            assert response.status_code == 400
            assert "cannot cancel" in response.json()["detail"].lower()


class TestTaskStream:
    """Tests for GET /api/tasks/{task_id}/stream endpoint."""

    def test_stream_returns_sse_content_type(self, client: TestClient):
        """Stream endpoint should return SSE content type."""
        # Mock task exists
        with patch("app.services.task_service.get_task") as mock_get:
            mock_get.return_value = {
                "task_id": "task-123",
                "status": "STARTED",
                "metadata": {},
                "info": {},
            }

            # Mock Redis to return completed progress (triggers immediate stop)
            with patch("app.services.task_service.get_redis_client") as mock_redis:
                redis_mock = MagicMock()
                redis_mock.get.return_value = b'{"status": "completed", "task_id": "task-123", "progress": 1.0}'
                mock_redis.return_value = redis_mock

                response = client.get("/api/tasks/task-123/stream")

                assert response.status_code == 200
                assert "text/event-stream" in response.headers["content-type"]

    def test_stream_task_not_found(self, client: TestClient):
        """Stream should return 404 for unknown task."""
        with patch("app.services.task_service.get_task") as mock_get:
            mock_get.return_value = None

            response = client.get("/api/tasks/unknown-task/stream")

            assert response.status_code == 404
