import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
TOPOLOGY_PATH = BASE_DIR / "intersection.json"

with open(TOPOLOGY_PATH, "r", encoding="utf-8") as f:
    data = json.load(f)

CAM_TO_INTERSECTION = {}
CAM_TO_DIRECTION = {}
INTERSECTIONS = {}

for inter in data["intersections"]:
    inter_id = inter["id"]
    INTERSECTIONS[inter_id] = inter

    for app in inter["approaches"]:
        direction = app["direction"]
        for cam in app["cameras"]:
            CAM_TO_INTERSECTION[cam] = inter_id
            CAM_TO_DIRECTION[cam] = direction
