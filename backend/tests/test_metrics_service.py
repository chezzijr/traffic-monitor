"""Tests for metrics service logic."""

from datetime import datetime

from app.services.metrics_service import (
    MetricsHistory,
    MetricsSnapshot,
    clear_metrics,
    get_current_metrics,
    get_metrics_history,
    get_summary_stats,
    record_metrics,
)


class TestMetricsSnapshot:
    """Tests for MetricsSnapshot dataclass."""

    def test_snapshot_creation(self):
        """Snapshot should store all fields correctly."""
        now = datetime.now()
        snapshot = MetricsSnapshot(
            timestamp=now,
            step=10,
            total_vehicles=50,
            total_wait_time=100.5,
            average_wait_time=2.01,
            throughput=5,
        )

        assert snapshot.timestamp == now
        assert snapshot.step == 10
        assert snapshot.total_vehicles == 50
        assert snapshot.total_wait_time == 100.5
        assert snapshot.average_wait_time == 2.01
        assert snapshot.throughput == 5


class TestMetricsHistory:
    """Tests for MetricsHistory class."""

    def test_add_and_get_recent(self):
        """Adding snapshots and retrieving them should work."""
        history = MetricsHistory(max_size=100)

        for i in range(5):
            snapshot = MetricsSnapshot(
                timestamp=datetime.now(),
                step=i,
                total_vehicles=i * 10,
                total_wait_time=i * 5.0,
                average_wait_time=0.5,
                throughput=i,
            )
            history.add(snapshot)

        recent = history.get_recent(3)
        assert len(recent) == 3
        assert recent[-1].step == 4

    def test_max_size_limit(self):
        """History should not exceed max_size."""
        history = MetricsHistory(max_size=5)

        for i in range(10):
            snapshot = MetricsSnapshot(
                timestamp=datetime.now(),
                step=i,
                total_vehicles=i,
                total_wait_time=0.0,
                average_wait_time=0.0,
                throughput=0,
            )
            history.add(snapshot)

        all_snapshots = history.get_recent(100)
        assert len(all_snapshots) == 5
        assert all_snapshots[0].step == 5  # oldest should be step 5
        assert all_snapshots[-1].step == 9  # newest should be step 9

    def test_clear(self):
        """Clear should remove all snapshots."""
        history = MetricsHistory(max_size=100)

        for i in range(5):
            snapshot = MetricsSnapshot(
                timestamp=datetime.now(),
                step=i,
                total_vehicles=i,
                total_wait_time=0.0,
                average_wait_time=0.0,
                throughput=0,
            )
            history.add(snapshot)

        history.clear()
        assert len(history.get_recent(100)) == 0


class TestMetricsServiceFunctions:
    """Tests for module-level metrics service functions."""

    def test_record_metrics_returns_snapshot(self):
        """record_metrics should return the created snapshot."""
        snapshot = record_metrics(
            step=1,
            total_vehicles=20,
            total_wait_time=40.0,
            average_wait_time=2.0,
            throughput=3,
        )

        assert snapshot.step == 1
        assert snapshot.total_vehicles == 20
        assert snapshot.total_wait_time == 40.0
        assert snapshot.average_wait_time == 2.0
        assert snapshot.throughput == 3

    def test_get_current_metrics_returns_latest(self):
        """get_current_metrics should return the most recent snapshot."""
        record_metrics(step=1, total_vehicles=10, total_wait_time=5.0, average_wait_time=0.5)
        record_metrics(step=2, total_vehicles=20, total_wait_time=10.0, average_wait_time=0.5)

        current = get_current_metrics()
        assert current is not None
        assert current.step == 2
        assert current.total_vehicles == 20

    def test_get_current_metrics_empty(self):
        """get_current_metrics should return None when no metrics recorded."""
        clear_metrics()
        current = get_current_metrics()
        assert current is None

    def test_get_metrics_history(self):
        """get_metrics_history should return requested number of snapshots."""
        for i in range(10):
            record_metrics(
                step=i,
                total_vehicles=i * 10,
                total_wait_time=i * 5.0,
                average_wait_time=0.5,
            )

        history = get_metrics_history(5)
        assert len(history) == 5
        assert history[-1].step == 9

    def test_get_summary_stats_empty(self):
        """get_summary_stats should return zeros when empty."""
        clear_metrics()
        stats = get_summary_stats()

        assert stats["total_snapshots"] == 0
        assert stats["avg_vehicles"] == 0
        assert stats["avg_wait_time"] == 0
        assert stats["total_throughput"] == 0

    def test_get_summary_stats_with_data(self):
        """get_summary_stats should compute correct statistics."""
        # Record 3 snapshots with known values
        record_metrics(step=1, total_vehicles=10, total_wait_time=20.0, average_wait_time=2.0, throughput=5)
        record_metrics(step=2, total_vehicles=20, total_wait_time=40.0, average_wait_time=2.0, throughput=10)
        record_metrics(step=3, total_vehicles=30, total_wait_time=60.0, average_wait_time=2.0, throughput=15)

        stats = get_summary_stats()

        assert stats["total_snapshots"] == 3
        assert stats["avg_vehicles"] == 20.0  # (10+20+30)/3
        assert stats["avg_wait_time"] == 2.0  # (2+2+2)/3
        assert stats["total_throughput"] == 30  # 5+10+15

    def test_clear_metrics(self):
        """clear_metrics should remove all stored metrics."""
        record_metrics(step=1, total_vehicles=10, total_wait_time=5.0, average_wait_time=0.5)

        clear_metrics()

        assert get_current_metrics() is None
        assert len(get_metrics_history(100)) == 0
