"""Pytest fixtures for backend tests."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import metrics_service, osm_service


@pytest.fixture
def client() -> TestClient:
    """Create a test client for the FastAPI app."""
    return TestClient(app)


@pytest.fixture(autouse=True)
def reset_metrics():
    """Reset metrics service before each test."""
    metrics_service.clear_metrics()
    yield
    metrics_service.clear_metrics()


@pytest.fixture(autouse=True)
def reset_osm_cache():
    """Reset OSM service cache before each test."""
    osm_service.clear_cache()
    yield
    osm_service.clear_cache()


@pytest.fixture
def sample_bbox() -> dict:
    """Provide a sample bounding box for testing."""
    return {
        "south": 21.0227,
        "west": 105.8194,
        "north": 21.0327,
        "east": 105.8294,
    }


@pytest.fixture
def mock_network_data() -> dict:
    """Provide mock network data for testing."""
    return {
        "network_id": "abc123def456",
        "intersections": [
            {
                "id": "12345",
                "lat": 21.025,
                "lon": 105.822,
                "name": "Test Street",
                "num_roads": 4,
            },
            {
                "id": "67890",
                "lat": 21.027,
                "lon": 105.824,
                "name": None,
                "num_roads": 3,
            },
        ],
        "road_count": 15,
        "bbox": {
            "south": 21.0227,
            "west": 105.8194,
            "north": 21.0327,
            "east": 105.8294,
        },
    }
