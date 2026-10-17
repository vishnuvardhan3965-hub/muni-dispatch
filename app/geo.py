"""
Geospatial utilities: Haversine distance calculation and municipal sector mapping.
"""
import math
import re
from typing import Dict, Any, Tuple
from app.config import MUNICIPAL_SECTORS

def haversine_distance_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate the great circle distance in meters between two points 
    on the earth (specified in decimal degrees).
    """
    # Convert decimal degrees to radians 
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    # Earth's radius in meters
    R = 6371000.0

    a = (math.sin(delta_phi / 2.0) ** 2 +
         math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2)
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))

    return R * c

def resolve_sector_from_coords(lat: float, lng: float) -> str:
    """
    Find the closest municipal sector given latitude and longitude coordinates.
    """
    closest_sector_id = "SEC-CENTRAL"
    min_dist = float("inf")

    for sec_id, sec_data in MUNICIPAL_SECTORS.items():
        center = sec_data["center"]
        dist = haversine_distance_meters(lat, lng, center["lat"], center["lng"])
        if dist < min_dist:
            min_dist = dist
            closest_sector_id = sec_id

    return closest_sector_id

_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = {"near", "opposite", "at", "the", "corner", "of", "and", "gate", "road",
         "street", "avenue", "in", "front", "behind", "next", "to", "by", "main"}


def normalize_text(text: str) -> str:
    """Lowercase and strip everything except letters and digits."""
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def is_similar_landmark(landmark1: str, landmark2: str) -> bool:
    """
    True when two landmark descriptions very likely name the same place:
    identical text, one fully contained in the other (min 10 chars), or at
    least two shared descriptive words covering most of the shorter text.
    """
    n1, n2 = normalize_text(landmark1), normalize_text(landmark2)
    if not n1 or not n2:
        return False
    if n1 == n2:
        return True
    short, long_ = sorted((n1, n2), key=len)
    if len(short) >= 10 and short in long_:
        return True
    w1 = set(_TOKEN.findall(landmark1.lower())) - _STOP
    w2 = set(_TOKEN.findall(landmark2.lower())) - _STOP
    if not w1 or not w2:
        return False
    common = w1 & w2
    return len(common) >= 2 and len(common) >= 0.6 * min(len(w1), len(w2))
