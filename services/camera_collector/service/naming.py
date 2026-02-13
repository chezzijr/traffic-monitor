import unicodedata

def normalize_road(name: str) -> str:
    name = name.lower().strip()
    name = unicodedata.normalize("NFD", name)
    name = "".join(c for c in name if unicodedata.category(c) != "Mn")
    name = name.replace(" ", "_")
    return name


def make_intersection_id(road_a: str, road_b: str) -> str:
    r1 = normalize_road(road_a)
    r2 = normalize_road(road_b)
    return "__".join(sorted([r1, r2]))
