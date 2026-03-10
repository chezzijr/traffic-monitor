import base64
import redis
from pathlib import Path

from app.config import settings
from app.utils.intersection_resolver import resolve_intersection, roads_from_traffic_light

try:
    r = redis.Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        socket_connect_timeout=2
    )
    r.ping()
except redis.exceptions.ConnectionError:
    print("Redis not available → fallback to disk")
    r = None

DATASET_DIR = Path(__file__).parent.parent.parent.parent / "dataset"
NUMBERS = [1, 2]


def read_disk(intersection: str, number: int):
    path = DATASET_DIR / intersection / str(number) / "latest.jpg"
    if path.exists():
        return path.read_bytes()
    return None


def get_frame(intersection: str, number: int):
    key = f"frame:{intersection}:{number}"

    img = r.get(key)
    if not img:
        img = read_disk(intersection, number)

    if not img:
        return None

    return base64.b64encode(img).decode()


def get_frames_by_roads(roads: list[str]):
    intersection = resolve_intersection(roads)
    if not intersection:
        return None

    frames = []
    for n in NUMBERS:
        frames.append({
            "number": n,
            "image": get_frame(intersection, n)
        })

    return {
        "intersection_id": intersection,
        "frames": frames
    }




def get_frames_from_traffic_light(lat: float, lon: float, radius: int = 700):

    # 1 tìm intersection + roads
    result = roads_from_traffic_light(lat, lon, radius)

    if not result or not result["roads"]:
        return None

    roads = result["roads"]

    # 2 resolve dataset + load frames
    frames = get_frames_by_roads(roads)

    if not frames:
        return {
            "intersection_id": result["intersection_id"],
            "roads": roads,
            "frames": []
        }

    return {
        "intersection_id": result["intersection_id"],
        "roads": roads,
        "frames": frames["frames"]
    }