"""Tests for training Celery task."""

import json
from unittest.mock import MagicMock, patch
from pathlib import Path

import pytest


class TestTrainingProgress:
    """Tests for TrainingProgress data class."""

    def test_to_dict_contains_all_fields(self):
        """TrainingProgress.to_dict should include all fields."""
        from app.tasks.training_task import TrainingProgress

        progress = TrainingProgress(
            task_id="test-task-123",
            status="running",
            timestep=500,
            total_timesteps=1000,
            progress=0.5,
            episode_count=5,
            mean_reward=-10.5,
            message="Training in progress",
        )

        result = progress.to_dict()

        assert result["task_id"] == "test-task-123"
        assert result["status"] == "running"
        assert result["timestep"] == 500
        assert result["total_timesteps"] == 1000
        assert result["progress"] == 0.5
        assert result["episode_count"] == 5
        assert result["mean_reward"] == -10.5
        assert result["message"] == "Training in progress"

    def test_to_dict_handles_none_values(self):
        """TrainingProgress.to_dict should handle None values."""
        from app.tasks.training_task import TrainingProgress

        progress = TrainingProgress(
            task_id="test-task",
            status="pending",
        )

        result = progress.to_dict()

        assert result["task_id"] == "test-task"
        assert result["status"] == "pending"
        assert result["timestep"] is None
        assert result["mean_reward"] is None


class TestCancellationCallback:
    """Tests for the CancellationCallback."""

    def test_callback_returns_true_when_not_revoked(self):
        """Callback should return True when task is not revoked."""
        from app.tasks.training_task import CancellationCallback

        with patch("app.tasks.training_task.AsyncResult") as mock_async:
            mock_result = MagicMock()
            mock_result.state = "STARTED"
            mock_async.return_value = mock_result

            callback = CancellationCallback(task_id="test-123")
            callback.model = MagicMock()  # SB3 sets this during training
            callback.num_timesteps = 100
            callback.n_calls = 0
            callback._step_count = 99  # Will be 100 after increment

            # Simulate _on_step
            result = callback._on_step()

            assert result is True

    def test_callback_returns_false_when_revoked(self):
        """Callback should return False when task is revoked."""
        from app.tasks.training_task import CancellationCallback

        with patch("app.tasks.training_task.AsyncResult") as mock_async:
            mock_result = MagicMock()
            mock_result.state = "REVOKED"
            mock_async.return_value = mock_result

            callback = CancellationCallback(task_id="test-456")
            callback.model = MagicMock()
            callback.num_timesteps = 100
            callback.n_calls = 0
            callback._step_count = 99  # Will be 100 after increment

            result = callback._on_step()

            assert result is False

    def test_callback_skips_check_between_intervals(self):
        """Callback should not check AsyncResult between intervals."""
        from app.tasks.training_task import CancellationCallback

        with patch("app.tasks.training_task.AsyncResult") as mock_async:
            callback = CancellationCallback(task_id="test-789", check_interval=100)
            callback._step_count = 50  # Will be 51, not divisible by 100

            result = callback._on_step()

            # Should return True without checking AsyncResult
            assert result is True
            mock_async.assert_not_called()


class TestProgressPublishingCallback:
    """Tests for ProgressPublishingCallback."""

    def test_publishes_at_interval(self):
        """Callback should publish progress at specified interval."""
        from app.tasks.training_task import ProgressPublishingCallback

        mock_redis = MagicMock()
        callback = ProgressPublishingCallback(
            task_id="test-publish",
            total_timesteps=1000,
            redis_client=mock_redis,
            publish_interval=100,
        )
        callback.num_timesteps = 100
        callback.n_calls = 100  # At interval
        callback.locals = {"rewards": [0.5], "dones": [False]}

        callback._on_step()

        # Should have published
        mock_redis.publish.assert_called_once()
        channel, message = mock_redis.publish.call_args[0]
        assert channel == "task:test-publish:updates"
        data = json.loads(message)
        assert data["status"] == "running"

    def test_tracks_episode_rewards(self):
        """Callback should track episode rewards when episode ends."""
        from app.tasks.training_task import ProgressPublishingCallback

        mock_redis = MagicMock()
        callback = ProgressPublishingCallback(
            task_id="test-episodes",
            total_timesteps=1000,
            redis_client=mock_redis,
            publish_interval=100,
        )
        callback.num_timesteps = 50
        callback.n_calls = 50
        callback.locals = {"rewards": [10.0], "dones": [True]}  # Episode ended

        callback._on_step()

        assert len(callback._episode_rewards) == 1
        assert callback._episode_rewards[0] == 10.0
        assert callback._current_episode_reward == 0.0  # Reset after episode


class TestRunTraining:
    """Tests for the run_training function.

    These tests call the core training logic directly with mocked dependencies.
    """

    @pytest.fixture
    def mock_redis(self):
        """Create a mock Redis client."""
        with patch("app.tasks.training_task.get_redis_client") as mock:
            redis_mock = MagicMock()
            mock.return_value = redis_mock
            yield redis_mock

    @pytest.fixture
    def mock_env(self):
        """Create a mock TrafficLightEnv."""
        with patch("app.tasks.training_task.TrafficLightEnv") as mock:
            env_instance = MagicMock()
            env_instance.observation_space = MagicMock()
            env_instance.observation_space.shape = (10,)
            env_instance.action_space = MagicMock()
            env_instance.action_space.n = 4
            env_instance._num_phases = 4
            env_instance._controlled_lanes = ["lane1", "lane2"]
            env_instance.scenario = "moderate"
            mock.return_value = env_instance
            yield mock

    @pytest.fixture
    def mock_trainer(self):
        """Create a mock TrafficLightTrainer."""
        with patch("app.tasks.training_task.TrafficLightTrainer") as mock:
            trainer_instance = MagicMock()
            trainer_instance.model = MagicMock()
            trainer_instance.model.num_timesteps = 10000
            mock.return_value = trainer_instance
            yield mock

    @pytest.fixture
    def mock_network_path(self, tmp_path):
        """Create a mock network file."""
        network_file = tmp_path / "test_network.net.xml"
        network_file.write_text("<net></net>")

        with patch("app.tasks.training_task.SIMULATION_NETWORKS_DIR", tmp_path):
            yield tmp_path

    @pytest.fixture
    def mock_models_dir(self, tmp_path):
        """Create a mock models directory."""
        models_dir = tmp_path / "models"
        models_dir.mkdir()

        with patch("app.tasks.training_task.MODELS_DIR", models_dir):
            yield models_dir

    def test_publishes_started_event(
        self, mock_redis, mock_env, mock_trainer, mock_network_path, mock_models_dir
    ):
        """run_training should publish started event to Redis."""
        from app.tasks.training_task import run_training

        with patch("app.tasks.training_task.AsyncResult") as mock_async:
            mock_result = MagicMock()
            mock_result.state = "STARTED"
            mock_async.return_value = mock_result

            run_training(
                task_id="celery-task-123",
                network_id="test_network",
                traffic_light_id="tl_1",
                algorithm="dqn",
                total_timesteps=100,
            )

        # Verify started event was published
        calls = mock_redis.publish.call_args_list
        assert len(calls) >= 1

        # First call should be "started" status
        first_call = calls[0]
        channel, message = first_call[0]
        assert "task:" in channel
        assert ":updates" in channel
        data = json.loads(message)
        assert data["status"] == "started"

    def test_publishes_completed_event(
        self, mock_redis, mock_env, mock_trainer, mock_network_path, mock_models_dir
    ):
        """run_training should publish completed event when training finishes."""
        from app.tasks.training_task import run_training

        with patch("app.tasks.training_task.AsyncResult") as mock_async:
            mock_result = MagicMock()
            mock_result.state = "STARTED"
            mock_async.return_value = mock_result

            run_training(
                task_id="celery-task-456",
                network_id="test_network",
                traffic_light_id="tl_1",
                algorithm="dqn",
                total_timesteps=100,
            )

        # Verify completed event was published
        calls = mock_redis.publish.call_args_list
        last_call = calls[-1]
        channel, message = last_call[0]
        data = json.loads(message)

        assert data["status"] == "completed"

    def test_publishes_failed_event_on_error(
        self, mock_redis, mock_env, mock_trainer, mock_network_path, mock_models_dir
    ):
        """run_training should publish failed event when training fails."""
        from app.tasks.training_task import run_training

        # Make trainer.train raise an exception
        mock_trainer.return_value.train.side_effect = RuntimeError("Training failed")

        with patch("app.tasks.training_task.AsyncResult") as mock_async:
            mock_result = MagicMock()
            mock_result.state = "STARTED"
            mock_async.return_value = mock_result

            # Task should raise but publish failure first
            with pytest.raises(RuntimeError):
                run_training(
                    task_id="celery-task-789",
                    network_id="test_network",
                    traffic_light_id="tl_1",
                    algorithm="dqn",
                    total_timesteps=100,
                )

        # Verify failed event was published
        calls = mock_redis.publish.call_args_list
        # Find the failed status call
        failed_call = None
        for call in calls:
            channel, message = call[0]
            data = json.loads(message)
            if data.get("status") == "failed":
                failed_call = data
                break

        assert failed_call is not None
        assert "Training failed" in failed_call.get("message", "")

    def test_creates_independent_sumo_instance(
        self, mock_redis, mock_env, mock_trainer, mock_network_path, mock_models_dir
    ):
        """run_training should create its own SUMO instance (TrafficLightEnv)."""
        from app.tasks.training_task import run_training

        with patch("app.tasks.training_task.AsyncResult") as mock_async:
            mock_result = MagicMock()
            mock_result.state = "STARTED"
            mock_async.return_value = mock_result

            run_training(
                task_id="celery-task-env",
                network_id="test_network",
                traffic_light_id="tl_custom",
                algorithm="ppo",
                total_timesteps=200,
            )

        # Verify TrafficLightEnv was created with correct params
        mock_env.assert_called_once()
        call_kwargs = mock_env.call_args[1]
        assert call_kwargs["network_id"] == "test_network"
        assert call_kwargs["tl_id"] == "tl_custom"
        assert call_kwargs["gui"] is False  # Background task should not use GUI

    def test_uses_correct_algorithm(
        self, mock_redis, mock_env, mock_trainer, mock_network_path, mock_models_dir
    ):
        """run_training should create trainer with specified algorithm."""
        from app.tasks.training_task import run_training

        with patch("app.tasks.training_task.AsyncResult") as mock_async:
            mock_result = MagicMock()
            mock_result.state = "STARTED"
            mock_async.return_value = mock_result

            run_training(
                task_id="celery-task-algo",
                network_id="test_network",
                traffic_light_id="tl_1",
                algorithm="ppo",
                total_timesteps=100,
            )

        # Verify trainer was created with PPO
        mock_trainer.assert_called_once()
        call_kwargs = mock_trainer.call_args[1]
        assert call_kwargs["algorithm"].value == "ppo"

    def test_closes_env_on_completion(
        self, mock_redis, mock_env, mock_trainer, mock_network_path, mock_models_dir
    ):
        """run_training should close the environment after training."""
        from app.tasks.training_task import run_training

        env_instance = mock_env.return_value

        with patch("app.tasks.training_task.AsyncResult") as mock_async:
            mock_result = MagicMock()
            mock_result.state = "STARTED"
            mock_async.return_value = mock_result

            run_training(
                task_id="celery-task-close",
                network_id="test_network",
                traffic_light_id="tl_1",
                algorithm="dqn",
                total_timesteps=100,
            )

        # Verify env.close() was called
        env_instance.close.assert_called_once()

    def test_closes_env_on_failure(
        self, mock_redis, mock_env, mock_trainer, mock_network_path, mock_models_dir
    ):
        """run_training should close the environment even when training fails."""
        from app.tasks.training_task import run_training

        env_instance = mock_env.return_value
        mock_trainer.return_value.train.side_effect = RuntimeError("Fail")

        with patch("app.tasks.training_task.AsyncResult") as mock_async:
            mock_result = MagicMock()
            mock_result.state = "STARTED"
            mock_async.return_value = mock_result

            with pytest.raises(RuntimeError):
                run_training(
                    task_id="celery-task-fail-close",
                    network_id="test_network",
                    traffic_light_id="tl_1",
                    algorithm="dqn",
                    total_timesteps=100,
                )

        # Verify env.close() was still called
        env_instance.close.assert_called_once()

    def test_raises_for_invalid_network(self, mock_redis, tmp_path):
        """run_training should raise FileNotFoundError for non-existent network."""
        from app.tasks.training_task import run_training

        with patch("app.tasks.training_task.SIMULATION_NETWORKS_DIR", tmp_path):
            with pytest.raises(FileNotFoundError):
                run_training(
                    task_id="celery-task-invalid",
                    network_id="nonexistent_network",
                    traffic_light_id="tl_1",
                    algorithm="dqn",
                    total_timesteps=100,
                )

    def test_raises_for_invalid_algorithm(
        self, mock_redis, mock_network_path, mock_models_dir
    ):
        """run_training should raise ValueError for invalid algorithm."""
        from app.tasks.training_task import run_training

        with pytest.raises(ValueError, match="Invalid algorithm"):
            run_training(
                task_id="celery-task-invalid-algo",
                network_id="test_network",
                traffic_light_id="tl_1",
                algorithm="invalid_algo",
                total_timesteps=100,
            )

    def test_returns_result_dict(
        self, mock_redis, mock_env, mock_trainer, mock_network_path, mock_models_dir
    ):
        """run_training should return a dict with training results."""
        from app.tasks.training_task import run_training

        with patch("app.tasks.training_task.AsyncResult") as mock_async:
            mock_result = MagicMock()
            mock_result.state = "STARTED"
            mock_async.return_value = mock_result

            result = run_training(
                task_id="celery-task-result",
                network_id="test_network",
                traffic_light_id="tl_1",
                algorithm="dqn",
                total_timesteps=100,
            )

        assert result["status"] == "completed"
        assert result["task_id"] == "celery-task-result"
        assert "model_path" in result


class TestTrainTrafficLightTask:
    """Tests for the Celery task wrapper."""

    def test_task_is_registered(self):
        """The task should be properly registered with Celery."""
        from app.tasks.training_task import train_traffic_light

        assert train_traffic_light.name == "tasks.train_traffic_light"

    def test_task_calls_run_training(self):
        """The task should delegate to run_training function."""
        from app.tasks.training_task import train_traffic_light

        # Verify the task wraps run_training by checking its signature
        # The task should accept the same parameters as run_training
        import inspect
        sig = inspect.signature(train_traffic_light)
        param_names = list(sig.parameters.keys())

        # Should have self (bound task) + run_training params
        assert "network_id" in param_names
        assert "traffic_light_id" in param_names
        assert "algorithm" in param_names
        assert "total_timesteps" in param_names
        assert "scenario" in param_names
