import redis
from service.config import REDIS_HOST, REDIS_PORT
from service.topology import CAM_TO_INTERSECTION, CAM_TO_DIRECTION

r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=False)

TTL = 20

def cache_latest(cam_id: str, img: bytes):
    inter = CAM_TO_INTERSECTION.get(cam_id)
    direction = CAM_TO_DIRECTION.get(cam_id)

    if not inter or not direction:
        return

    key = f"frame:{inter}:{direction}"
    r.setex(key, TTL, img)
