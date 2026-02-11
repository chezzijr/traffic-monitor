import time

BASE_URL = "https://giaothong.hochiminhcity.gov.vn:8007/Render/CameraHandler.ashx"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
    "Referer": "https://giaothong.hochiminhcity.gov.vn/map.aspx",
    "Origin": "https://giaothong.hochiminhcity.gov.vn",
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive"
}

def build_url(cam_id: str) -> str:
    ts = int(time.time() * 1000)
    return f"{BASE_URL}?id={cam_id}&t={ts}"