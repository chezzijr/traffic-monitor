import aiohttp
import asyncio
import os
from daytime import datetime
from PIL import Image
import imagehash
import io
from service.config import CAMERA_IDS, POLL_INTERVAL, DATASET_DIR
from service.hcm_gov import build_url, HEADERS
from service.storage import cache_latest
from service.topology import CAM_TO_INTERSECTION, CAM_TO_NUMBER


last_hash = {}

os.makedirs(DATASET_DIR, exist_ok=True)

BASE_PAGE = "https://giaothong.hochiminhcity.gov.vn/map.aspx"

async def init_session(session, max_retries: int = 10, base_delay: float = 5.0):
    """Initialize session by hitting the base page to obtain cookies.
    
    Retries with exponential backoff if the server is temporarily unavailable.
    """
    for attempt in range(1, max_retries + 1):
        try:
            async with session.get(BASE_PAGE) as resp:
                await resp.text()
                print(f"Session initialized (attempt {attempt})")
                return
        except Exception as e:
            delay = min(base_delay * attempt, 60.0)  # cap at 60s
            print(f"init_session failed (attempt {attempt}/{max_retries}): {e} — retrying in {delay:.0f}s")
            await asyncio.sleep(delay)
    print("init_session: all retries exhausted — continuing without session cookie")

def write_file(path, data):
    with open(path, "wb") as f:
        f.write(data)

def is_jpeg(data: bytes) -> bool:
    return len(data) > 10 and data[0] == 0xFF and data[1] == 0xD8


def is_new_frame(cam_id, img_bytes):
    try:
        img = Image.open(io.BytesIO(img_bytes))
    except Exception:
        return False

    ph = imagehash.phash(img)

    if cam_id not in last_hash:
        last_hash[cam_id] = ph
        return True

    if ph - last_hash[cam_id] > 3:
        last_hash[cam_id] = ph
        return True

    return False


async def fetch_camera(session, cam_id):
    if not cam_id:
        return
    
    url = build_url(cam_id)
    timeout = aiohttp.ClientTimeout(total=10)

    try:
        async with session.get(url, timeout=timeout, headers=HEADERS) as resp:
            if resp.status != 200:
                print("fail", cam_id, resp.status)
                await asyncio.sleep(10)
                return

            img = await resp.read()
            
            if not is_jpeg(img):
                print("not image", cam_id)
                return

            if not is_new_frame(cam_id, img):
                return

            # cache realtime
            cache_latest(cam_id, img)

            # save dataset async
            inter = CAM_TO_INTERSECTION.get(cam_id)
            number = CAM_TO_NUMBER.get(cam_id)

            if inter and number:
                inter_dir = os.path.join(DATASET_DIR, inter, str(number))
                os.makedirs(inter_dir, exist_ok=True)

                # ts = f'{inter}_{number}_{datetime.datetime.now().strftime("%Y%m%d_%H%M%S")}'

                # 1) lưu lịch sử
                # history_path = os.path.join(inter_dir, f"{ts}.jpg")
                # await asyncio.to_thread(write_file, history_path, img)

                # 2) update latest (atomic)
                tmp_path = os.path.join(inter_dir, "latest.tmp")
                latest_path = os.path.join(inter_dir, "latest.jpg")

                await asyncio.to_thread(write_file, tmp_path, img)
                await asyncio.to_thread(os.replace, tmp_path, latest_path)

                print("ok", inter_dir)

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