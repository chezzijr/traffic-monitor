import unicodedata
from pathlib import Path
from app.config import settings
import requests
import time
import math
import json
from collections import defaultdict

def make_intersection_id(road_a: str, road_b: str) -> str:
    r1 = normalize_road(road_a)
    r2 = normalize_road(road_b)
    return "__".join(sorted([r1, r2]))


def intersection_exists(intersection_id: str) -> bool:
    return (settings.dataset_dir / intersection_id).exists()


def resolve_intersection(roads: list[str]) -> str | None:
    if len(roads) < 2:
        return None
    iid = make_intersection_id(roads[0], roads[1])
    if intersection_exists(iid):
        return iid
    else:
        iid_2 = make_intersection_id(roads[1], roads[0])
        if intersection_exists(iid_2):
            return iid_2
        else:
            return None


# Get 2 closest roads from lat/lon
# =========================================================
CACHE_DIR = Path(__file__).parent.parent.parent / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

OVERPASS_SERVERS = [
    "https://overpass-api.de/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://z.overpass-api.de/api/interpreter"
]

# runtime RAM
NODE_COORDS = {}
INTERSECTION_ROADS = {}
CURRENT_REGION = None


def region_key(lat, lon, radius):
    return f"{round(lat,3)}_{round(lon,3)}_r{radius}"

def cache_path(key):
    return CACHE_DIR / f"{key}.json"

def dist2(a, b, c, d):
    return (a-c)**2 + (b-d)**2

def point_to_bbox(lat, lon, radius):
    dlat = radius / 111320
    dlon = radius / (111320 * math.cos(math.radians(lat)))
    return lat-dlat, lon-dlon, lat+dlat, lon+dlon


def overpass(query, retry=5):
    for i in range(retry):
        server = OVERPASS_SERVERS[i % len(OVERPASS_SERVERS)]
        try:
            print(f"[Overpass] try {i+1} @ {server}")

            r = requests.post(
                server,
                data=query,
                headers={"User-Agent": "ITS-MultiRegion/1.0"},
                timeout=180
            )

            if r.status_code != 200:
                raise Exception(f"HTTP {r.status_code}")

            if not r.text.strip():
                raise Exception("empty response")

            return r.json()

        except Exception as e:
            wait = 2**i
            print("retry in", wait, "because", e)
            time.sleep(wait)

    raise RuntimeError("Overpass failed")


def build_region(lat, lon, radius):

    global NODE_COORDS, INTERSECTION_ROADS

    south, west, north, east = point_to_bbox(lat, lon, radius)

    query = f"""
    [out:json][timeout:120];
    (
      way({south},{west},{north},{east})["highway"]["area"!~"yes"];
      node(w);
    );
    out body;
    """

    print("Downloading region from OSM...")

    data = overpass(query)

    NODE_COORDS.clear()
    INTERSECTION_ROADS.clear()

    degree = defaultdict(int)
    roads = defaultdict(set)

    # nodes
    for el in data["elements"]:
        if el["type"] == "node":
            NODE_COORDS[el["id"]] = (el["lat"], el["lon"])

    # topology
    for el in data["elements"]:
        if el["type"] != "way":
            continue

        name = el.get("tags", {}).get("name")
        if not name:
            continue

        for n in el["nodes"]:
            degree[n]+=1
            roads[n].add(name)

    # intersections
    for node, names in roads.items():
        if degree[node] >= 2:   # allow >=2 first, filter later
            INTERSECTION_ROADS[node] = list(names)

    print("Intersections in region:", len(INTERSECTION_ROADS))


# SAVE / LOAD cache
def save_region(key):
    data = {"coords": NODE_COORDS, "roads": INTERSECTION_ROADS}
    with open(cache_path(key),"w",encoding="utf8") as f:
        json.dump(data,f,ensure_ascii=False)
    print("Saved region cache:",key)

def load_region(key):
    global NODE_COORDS, INTERSECTION_ROADS

    p = cache_path(key)
    if not p.exists():
        return False

    with open(p,"r",encoding="utf8") as f:
        data=json.load(f)

    NODE_COORDS={int(k):tuple(v) for k,v in data["coords"].items()}
    INTERSECTION_ROADS={int(k):v for k,v in data["roads"].items()}

    print("Loaded region cache:",key)
    return True


def ensure_region(lat, lon, radius):

    global CURRENT_REGION

    key=region_key(lat,lon,radius)

    if CURRENT_REGION==key:
        return

    if load_region(key):
        CURRENT_REGION=key
        return

    build_region(lat,lon,radius)
    save_region(key)
    CURRENT_REGION=key


# ROAD FILTER
def normalize_road(name: str) -> str:
    name = name.lower().strip()

    # remove vietnamese accents
    name = unicodedata.normalize("NFD", name)
    name = "".join(c for c in name if unicodedata.category(c) != "Mn")

    # replace spaces
    name = name.replace(" ", "_")

    return name

def is_parent_child(a,b):
    a=normalize_road(a)
    b=normalize_road(b)
    return a in b or b in a


def valid_road_pair(roads):
    unique=[]
    for r in roads:
        ok=True
        for u in unique:
            if is_parent_child(r,u):
                ok=False
                break
        if ok:
            unique.append(r)
    return unique


def find_best_intersection(lat,lon):

    candidates=[]

    for node,(nlat,nlon) in NODE_COORDS.items():
        if node not in INTERSECTION_ROADS:
            continue

        roads=valid_road_pair(INTERSECTION_ROADS[node])

        if len(roads)>=2:
            d=dist2(lat,lon,nlat,nlon)
            candidates.append((d,node,roads))

    if not candidates:
        return None,[]

    candidates.sort()
    _,node,roads=candidates[0]
    return node,roads


def roads_from_traffic_light(lat,lon,radius=700):
    ensure_region(lat,lon,radius)
    iid,roads=find_best_intersection(lat,lon)
    return {
        "intersection_id":iid,
        "roads":roads
    }

