import aiohttp
import asyncio
import os
import time
from PIL import Image
import imagehash
import io
from service.config import CAMERA_IDS, POLL_INTERVAL, DATASET_DIR
from service.hcm_gov import build_url, HEADERS
from service.storage import cache_latest


last_hash = {}

os.makedirs(DATASET_DIR, exist_ok=True)

BASE_PAGE = "https://giaothong.hochiminhcity.gov.vn/map.aspx"

async def init_session(session):
    async with session.get(BASE_PAGE) as resp:
        await resp.text()  # nhận cookie
        print("session initialized")

def write_file(path, data):
    with open(path, "wb") as f:
        f.write(data)


def is_new_frame(cam_id, img_bytes):
    img = Image.open(io.BytesIO(img_bytes))
    ph = imagehash.phash(img)

    if cam_id not in last_hash:
        last_hash[cam_id] = ph
        return True

    if ph - last_hash[cam_id] > 3:  # threshold
        last_hash[cam_id] = ph
        return True

    return False


async def fetch_camera(session, cam_id):
    url = build_url(cam_id)
    timeout = aiohttp.ClientTimeout(total=10)

    try:
        async with session.get(url, timeout=timeout, headers=HEADERS) as resp:
            if resp.status != 200:
                print("fail", cam_id, resp.status)
                await asyncio.sleep(10)
                return

            img = await resp.read()
            
            if not is_new_frame(cam_id, img):
                return

            # cache realtime
            cache_latest(cam_id, img)

            # save dataset async
            cam_dir = os.path.join(DATASET_DIR, cam_id)
            os.makedirs(cam_dir, exist_ok=True)

            filename = f"{cam_dir}/{int(time.time())}.jpg"
            await asyncio.to_thread(write_file, filename, img)

            print("ok", cam_id)

    except Exception as e:
        print("error", cam_id, e)


async def run_loop():
    connector = aiohttp.TCPConnector(limit=20)
    timeout = aiohttp.ClientTimeout(total=15)

    async with aiohttp.ClientSession(
        connector=connector,
        timeout=timeout,
        headers=HEADERS
    ) as session:

        await init_session(session)

        while True:
            await asyncio.gather(*(fetch_camera(session, cid) for cid in CAMERA_IDS))
            await asyncio.sleep(POLL_INTERVAL)