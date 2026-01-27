"""Tests for health check endpoint."""

from fastapi.testclient import TestClient


def test_health_check_returns_ok(client: TestClient):
    """Health check endpoint should return status ok."""
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_check_is_json(client: TestClient):
    """Health check endpoint should return JSON content type."""
    response = client.get("/health")

    assert response.headers["content-type"] == "application/json"
