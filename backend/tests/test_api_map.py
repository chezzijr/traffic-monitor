"""Tests for map API endpoints."""

from unittest.mock import patch

from fastapi.testclient import TestClient


def test_get_networks_empty(client: TestClient):
    """Get networks should return empty list when no networks cached."""
    response = client.get("/api/map/networks")

    assert response.status_code == 200
    assert response.json() == []


def test_extract_region_invalid_bbox_south_north(client: TestClient):
    """Extract region should fail when south >= north."""
    response = client.post(
        "/api/map/extract-region",
        json={
            "south": 21.03,
            "west": 105.81,
            "north": 21.02,  # north < south
            "east": 105.82,
        },
    )

    assert response.status_code == 400
    assert "South" in response.json()["detail"]


def test_extract_region_invalid_bbox_west_east(client: TestClient):
    """Extract region should fail when west >= east."""
    response = client.post(
        "/api/map/extract-region",
        json={
            "south": 21.02,
            "west": 105.85,
            "north": 21.03,
            "east": 105.82,  # east < west
        },
    )

    assert response.status_code == 400
    assert "West" in response.json()["detail"]


def test_extract_region_success_mocked(client: TestClient, mock_network_data: dict):
    """Extract region should return network info on success (mocked)."""
    with patch("app.services.osm_service.extract_network") as mock_extract:
        mock_extract.return_value = mock_network_data

        response = client.post(
            "/api/map/extract-region",
            json={
                "south": 21.0227,
                "west": 105.8194,
                "north": 21.0327,
                "east": 105.8294,
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["network_id"] == mock_network_data["network_id"]
        assert len(data["intersections"]) == 2
        assert data["road_count"] == 15


def test_get_intersections_not_found(client: TestClient):
    """Get intersections should return 404 for unknown network."""
    response = client.get("/api/map/intersections/unknown-network-id")

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_get_intersections_success_mocked(client: TestClient, mock_network_data: dict):
    """Get intersections should return list for known network (mocked)."""
    with patch("app.services.osm_service.get_intersections") as mock_get:
        mock_get.return_value = mock_network_data["intersections"]

        response = client.get("/api/map/intersections/test-network-id")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert data[0]["id"] == "12345"
        assert data[0]["lat"] == 21.025
        assert data[1]["name"] is None


def test_convert_to_sumo_not_found(client: TestClient):
    """Convert to SUMO should return 404 for unknown network."""
    response = client.post("/api/map/convert-to-sumo/unknown-network-id")

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_convert_to_sumo_success_mocked(client: TestClient, tmp_path):
    """Convert to SUMO should return path and traffic light data on success (mocked)."""
    fake_path = tmp_path / "test.net.xml"
    fake_path.touch()

    mock_result = {
        "network_path": str(fake_path),
        "traffic_lights": [
            {
                "id": "tl_1",
                "x": 100.0,
                "y": 200.0,
                "type": "actuated",
                "phases": [{"duration": 30, "state": "GGrrGGrr"}],
            }
        ],
        "osm_to_sumo_tl_map": {"123456": "tl_1"},
    }

    with patch("app.services.osm_service.convert_to_sumo") as mock_convert:
        mock_convert.return_value = mock_result

        response = client.post("/api/map/convert-to-sumo/test-network-id")

        assert response.status_code == 201
        data = response.json()
        assert data["network_id"] == "test-network-id"
        assert "sumo_network_path" in data
        assert "traffic_lights" in data
        assert "osm_to_sumo_tl_map" in data
        assert len(data["traffic_lights"]) == 1
        assert data["traffic_lights"][0]["id"] == "tl_1"
