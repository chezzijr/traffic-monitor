"""Tests for OSM service functions."""

import pytest

from app.services.osm_service import _populate_sumo_tl_ids


class TestPopulateSumoTlIds:
    """Tests for _populate_sumo_tl_ids function."""

    def test_populates_matching_intersections(self):
        """Should populate sumo_tl_id for intersections in the mapping."""
        intersections = [
            {"id": "123", "lat": 21.0, "lon": 105.0, "has_traffic_light": True},
            {"id": "456", "lat": 21.1, "lon": 105.1, "has_traffic_light": True},
            {"id": "789", "lat": 21.2, "lon": 105.2, "has_traffic_light": False},
        ]
        osm_to_sumo_map = {
            "123": "tl_abc",
            "456": "tl_def",
        }

        _populate_sumo_tl_ids(intersections, osm_to_sumo_map)

        assert intersections[0]["sumo_tl_id"] == "tl_abc"
        assert intersections[1]["sumo_tl_id"] == "tl_def"
        assert intersections[2]["sumo_tl_id"] is None

    def test_sets_none_for_unmapped_intersections(self):
        """Should set sumo_tl_id to None for intersections not in the mapping."""
        intersections = [
            {"id": "123", "lat": 21.0, "lon": 105.0, "has_traffic_light": True},
            {"id": "456", "lat": 21.1, "lon": 105.1, "has_traffic_light": True},
        ]
        osm_to_sumo_map = {"123": "tl_abc"}  # Only one intersection mapped

        _populate_sumo_tl_ids(intersections, osm_to_sumo_map)

        assert intersections[0]["sumo_tl_id"] == "tl_abc"
        assert intersections[1]["sumo_tl_id"] is None

    def test_handles_empty_mapping(self):
        """Should set all sumo_tl_id to None when mapping is empty."""
        intersections = [
            {"id": "123", "lat": 21.0, "lon": 105.0, "has_traffic_light": True},
            {"id": "456", "lat": 21.1, "lon": 105.1, "has_traffic_light": True},
        ]
        osm_to_sumo_map: dict[str, str] = {}

        _populate_sumo_tl_ids(intersections, osm_to_sumo_map)

        assert intersections[0]["sumo_tl_id"] is None
        assert intersections[1]["sumo_tl_id"] is None

    def test_handles_empty_intersections(self):
        """Should handle empty intersections list gracefully."""
        intersections: list[dict] = []
        osm_to_sumo_map = {"123": "tl_abc"}

        # Should not raise
        _populate_sumo_tl_ids(intersections, osm_to_sumo_map)

        assert intersections == []

    def test_preserves_existing_sumo_tl_id(self):
        """Should overwrite existing sumo_tl_id if mapped."""
        intersections = [
            {"id": "123", "lat": 21.0, "lon": 105.0, "sumo_tl_id": "old_tl"},
        ]
        osm_to_sumo_map = {"123": "new_tl"}

        _populate_sumo_tl_ids(intersections, osm_to_sumo_map)

        assert intersections[0]["sumo_tl_id"] == "new_tl"

    def test_keeps_existing_sumo_tl_id_if_not_mapped(self):
        """Should preserve existing sumo_tl_id if not in mapping (via setdefault)."""
        intersections = [
            {"id": "123", "lat": 21.0, "lon": 105.0, "sumo_tl_id": "existing_tl"},
        ]
        osm_to_sumo_map: dict[str, str] = {}  # No mapping for this intersection

        _populate_sumo_tl_ids(intersections, osm_to_sumo_map)

        # setdefault keeps existing value
        assert intersections[0]["sumo_tl_id"] == "existing_tl"
