import json
from pathlib import Path
from service.naming import make_intersection_id

BASE_DIR = Path(__file__).resolve().parent.parent
TOPOLOGY_PATH = BASE_DIR / "intersection.json"

with open(TOPOLOGY_PATH, "r", encoding="utf-8") as f:
    data = json.load(f)

CAM_TO_INTERSECTION = {}
CAM_TO_DIRECTION = {}
INTERSECTIONS = {}

for inter in data["intersections"]:
    r1, r2 = inter["osm_query"]
    inter_id = make_intersection_id(r1, r2)

    INTERSECTIONS[inter_id] = inter

    for app in inter["approaches"]:
        direction = app["direction"]
        for cam in app["cameras"]:
            CAM_TO_INTERSECTION[cam] = inter_id
            CAM_TO_DIRECTION[cam] = direction
