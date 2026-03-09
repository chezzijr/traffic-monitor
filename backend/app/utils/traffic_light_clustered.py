import json
import math
from typing import List, Dict
import numpy as np
from scipy.spatial import KDTree

EARTH_RADIUS = 6371000
DIST_THRESHOLD = 50  # meters


def latlon_to_xy(lat, lon):
    """
    Convert lat/lon to meters for KDTree
    """
    x = math.radians(lon) * EARTH_RADIUS * math.cos(math.radians(lat))
    y = math.radians(lat) * EARTH_RADIUS
    return x, y


def haversine(lat1, lon1, lat2, lon2):
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)

    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )

    return 2 * EARTH_RADIUS * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def build_kdtree(nodes: List[Dict]):

    coords = [latlon_to_xy(n["lat"], n["lon"]) for n in nodes]
    tree = KDTree(coords)

    return tree, np.array(coords)


def cluster_traffic_lights(nodes: List[Dict]) -> List[Dict]:

    tree, coords = build_kdtree(nodes)

    visited = set()
    clusters = []

    for i in range(len(nodes)):

        if i in visited:
            continue

        idxs = tree.query_ball_point(coords[i], DIST_THRESHOLD)

        cluster = []
        stack = list(idxs)

        while stack:
            j = stack.pop()

            if j in visited:
                continue

            visited.add(j)
            cluster.append(nodes[j])

            neighbors = tree.query_ball_point(coords[j], DIST_THRESHOLD)

            for n in neighbors:
                if n not in visited:
                    stack.append(n)

        clusters.append(cluster)

    result = []

    for cluster in clusters:

        lat = sum(p["lat"] for p in cluster) / len(cluster)
        lon = sum(p["lon"] for p in cluster) / len(cluster)

        lat = round(lat, 7)
        lon = round(lon, 7)

        best_node = min(
            cluster,
            key=lambda p: haversine(lat, lon, p["lat"], p["lon"])
        )

        result.append({
            "osm_id": best_node["osm_id"],
            "lat": lat,
            "lon": lon
        })

    return result


def cluster_traffic_light_file(input_file: str, output_file: str):

    with open(input_file, "r") as f:
        nodes = json.load(f)

    clustered = cluster_traffic_lights(nodes)

    with open(output_file, "w") as f:
        json.dump(clustered, f, indent=2)

    print("Original:", len(nodes))
    print("Clustered:", len(clustered))