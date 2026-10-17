"""Duplicate detection and sector rejection engine."""
from typing import Any, Dict, Optional, Tuple

from app.config import DUPLICATE_RADIUS_METERS
from app.geo import haversine_distance_meters, is_similar_landmark


def find_duplicate_hazard(cur, category: str, sector_id: str, lat: float, lng: float,
                          landmark: str) -> Optional[Dict[str, Any]]:
    """
    Look for an active (unresolved) ticket of the same category that matches by
    (1) same sector within the radius, (2) same sector with a similar landmark,
    or (3) immediate proximity (<150 m) even across a sector border.

    Takes a transaction-scoped advisory lock per category so two simultaneous
    submissions of the same fault cannot both pass the check.
    """
    cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("hazard:" + category,))
    cur.execute(
        """SELECT id, ticket_code, category, landmark, sector_id, latitude, longitude,
                  status, assigned_crew_id
             FROM hazards WHERE status <> 'RESOLVED' AND category = %s""",
        (category,),
    )
    for ex in cur.fetchall():
        dist = haversine_distance_meters(lat, lng, ex["latitude"], ex["longitude"])
        same_sector = ex["sector_id"] == sector_id
        reason = None
        if same_sector and dist <= DUPLICATE_RADIUS_METERS:
            reason = f"same sector and within {int(dist)} m of an existing report"
        elif same_sector and is_similar_landmark(landmark, ex["landmark"]):
            reason = "same sector and matching landmark"
        elif dist < 150.0:
            reason = f"immediate proximity ({int(dist)} m) to an existing report"
        if reason:
            ex["match_reason"] = reason
            ex["distance_meters"] = round(dist, 1)
            return ex
    return None


def record_duplicate(cur, hazard_id: int, landmark: str, voter: str) -> Tuple[bool, Dict[str, Any]]:
    """
    Reinforce the existing ticket. Each network address can reinforce a ticket
    once, so repeat submissions cannot inflate the counters.
    Returns (counted, {upvotes, duplicate_reports_count}).
    """
    cur.execute(
        "INSERT INTO hazard_votes (hazard_id, voter) VALUES (%s,%s) ON CONFLICT DO NOTHING RETURNING 1",
        (hazard_id, voter),
    )
    counted = cur.fetchone() is not None
    if counted:
        cur.execute(
            """UPDATE hazards SET upvotes = upvotes + 1,
                      duplicate_reports_count = duplicate_reports_count + 1,
                      updated_at = now() WHERE id = %s""",
            (hazard_id,),
        )
        cur.execute(
            """INSERT INTO resolution_logs (hazard_id, action, crew_id, notes)
               VALUES (%s, 'DUPLICATE_REPORT_REINFORCED', 'CITIZEN_PORTAL', %s)""",
            (hazard_id, f"Duplicate report merged into this ticket. Citizen reference: '{landmark}'."),
        )
    cur.execute("SELECT upvotes, duplicate_reports_count FROM hazards WHERE id = %s", (hazard_id,))
    return counted, cur.fetchone()
