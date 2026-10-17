"""REST API for the Municipal Infrastructure Hazard & Utility Outage Dispatcher."""
import math
import re
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request
from psycopg2.extras import Json

from app import security as sec
from app.config import (CREW_UNITS, HAZARD_CATEGORIES, INCIDENT_STATUSES,
                        MUNICIPAL_SECTORS, URGENCY_LEVELS)
from app.db import tx
from app.duplicate_engine import find_duplicate_hazard, record_duplicate
from app.geo import resolve_sector_from_coords

api = Blueprint("api", __name__)

CATEGORY_IDS = [c["id"] for c in HAZARD_CATEGORIES]
URL_RE = re.compile(r"^https?://[^\s<>\"']{4,480}$", re.I)
PUBLIC_COLS = ("h.id, h.ticket_code, h.category, h.landmark, h.sector_id, h.latitude, h.longitude, "
               "h.urgency, h.photo_url, h.description, h.status, h.assigned_crew_id, h.upvotes, "
               "h.duplicate_reports_count, h.created_at, h.updated_at")


# ---------- helpers ----------
def err(status, code, message, **extra):
    return jsonify({"error": code, "message": message, **extra}), status


def body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def line(value, limit):
    """Single-line text: collapse whitespace and cap the length."""
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def para(value, limit):
    return str(value or "").strip()[:limit]


def _select(contact):
    extra = ", h.citizen_contact" if contact else ""
    return (f"SELECT {PUBLIC_COLS}{extra}, s.name AS sector_name, s.depot AS sector_depot, "
            "s.color AS sector_color, "
            "(SELECT COUNT(*) FROM resolution_logs l WHERE l.hazard_id = h.id)::int AS log_count "
            "FROM hazards h JOIN sectors s ON s.id = h.sector_id")


def fetch_detail(cur, hid, contact=False):
    cur.execute(_select(contact) + " WHERE h.id = %s", (hid,))
    hazard = cur.fetchone()
    if not hazard:
        return None
    cur.execute("SELECT id, action, crew_id, notes, metadata, created_at FROM resolution_logs "
                "WHERE hazard_id = %s ORDER BY created_at, id", (hid,))
    hazard["logs"] = cur.fetchall()
    return hazard


# ---------- public endpoints ----------
@api.get("/health")
def health():
    with tx() as cur:
        cur.execute("SELECT 1")
    return jsonify(ok=True)


@api.get("/hazards")
def list_hazards():
    crew = sec.crew_state()
    conds, params = [], []
    q = request.args
    if q.get("urgency", "all").lower() != "all":
        conds.append("LOWER(h.urgency) = LOWER(%s)"); params.append(q["urgency"])
    if q.get("status", "all").lower() != "all":
        conds.append("h.status = %s"); params.append(q["status"].upper())
    if q.get("category", "all").lower() != "all":
        conds.append("h.category = %s"); params.append(q["category"].upper())
    if q.get("sector", "all").lower() != "all":
        conds.append("h.sector_id = %s"); params.append(q["sector"])
    if q.get("search"):
        like = f"%{q['search'].strip()[:80]}%"
        conds.append("(h.ticket_code ILIKE %s OR h.landmark ILIKE %s OR h.description ILIKE %s)")
        params += [like, like, like]
    where = ("WHERE " + " AND ".join(conds)) if conds else ""
    sql = (_select(crew) + f" {where} ORDER BY (h.status = 'RESOLVED'), "
           "CASE WHEN h.status = 'RESOLVED' THEN 0 ELSE "
           "CASE h.urgency WHEN 'Critical' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END END, "
           "CASE WHEN h.status = 'RESOLVED' THEN -EXTRACT(EPOCH FROM h.updated_at) "
           "ELSE EXTRACT(EPOCH FROM h.created_at) END LIMIT 300")
    with tx() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    return jsonify(count=len(rows), hazards=rows)


@api.get("/hazards/<int:hid>")
def hazard_detail(hid):
    crew = sec.crew_state()
    with tx() as cur:
        hazard = fetch_detail(cur, hid, crew)
    if not hazard:
        return err(404, "NOT_FOUND", f"Hazard ticket #{hid} not found.")
    return jsonify(hazard)


@api.get("/sectors")
def sectors():
    with tx() as cur:
        cur.execute(
            """SELECT s.id, s.name, s.zone, s.depot, s.lat, s.lng, s.color,
                      COUNT(h.id)::int AS total_hazards,
                      (COUNT(h.id) FILTER (WHERE h.status <> 'RESOLVED'))::int AS active_hazards,
                      (COUNT(h.id) FILTER (WHERE h.status <> 'RESOLVED' AND h.urgency = 'Critical'))::int AS critical_hazards
                 FROM sectors s LEFT JOIN hazards h ON h.sector_id = s.id
                GROUP BY s.id ORDER BY s.id""")
        rows = cur.fetchall()
    return jsonify(sectors=rows)


@api.get("/stats")
def stats():
    with tx() as cur:
        cur.execute(
            """SELECT COUNT(*)::int AS total,
                      (COUNT(*) FILTER (WHERE status <> 'RESOLVED'))::int AS active,
                      (COUNT(*) FILTER (WHERE status <> 'RESOLVED' AND urgency = 'Critical'))::int AS critical,
                      (COUNT(*) FILTER (WHERE status = 'DISPATCHED'))::int AS dispatched,
                      (COUNT(*) FILTER (WHERE status = 'ON_SITE_VERIFIED'))::int AS verified,
                      (COUNT(*) FILTER (WHERE status = 'RESOLVED'))::int AS resolved,
                      COALESCE(SUM(duplicate_reports_count), 0)::int AS dups
                 FROM hazards""")
        r = cur.fetchone()
    return jsonify(total_reported=r["total"], active_outages=r["active"], critical_active=r["critical"],
                   dispatched_crews=r["dispatched"], on_site_verified=r["verified"],
                   resolved_tickets=r["resolved"], duplicates_prevented=r["dups"],
                   categories=HAZARD_CATEGORIES)


@api.post("/hazards")
def create_hazard():
    if sec.rate_limited("create", 10, 600):
        return err(429, "RATE_LIMITED", "Too many reports from this network. Try again in a few minutes.")
    d = body()

    category = line(d.get("category"), 40).upper()
    if category not in CATEGORY_IDS:
        return err(400, "INVALID_CATEGORY", "Choose a hazard category.")
    landmark = line(d.get("landmark"), 160)
    if len(landmark) < 3:
        return err(400, "MISSING_LANDMARK", "Add a location landmark so crews can find the hazard.")
    urgency = line(d.get("urgency"), 10).capitalize()
    if urgency not in URGENCY_LEVELS:
        return err(400, "INVALID_URGENCY", "Urgency must be Low, Medium or Critical.")
    try:
        lat, lng = float(d["latitude"]), float(d["longitude"])
    except (KeyError, TypeError, ValueError):
        return err(400, "INVALID_COORDINATES", "Drop a pin on the map or use GPS to geotag the hazard.")
    if not (math.isfinite(lat) and math.isfinite(lng) and -90 <= lat <= 90 and -180 <= lng <= 180):
        return err(400, "INVALID_COORDINATES", "The pin location is not valid. Drop it again.")
    sector_id = line(d.get("sector_id"), 30)
    if sector_id not in MUNICIPAL_SECTORS:
        sector_id = resolve_sector_from_coords(lat, lng)
    photo = line(d.get("photo_url"), 500)
    if photo and not URL_RE.match(photo):
        return err(400, "INVALID_PHOTO_URL", "Photo link must start with http:// or https://.")
    description = para(d.get("description"), 1000)
    contact = line(d.get("citizen_contact"), 120)
    voter = sec.voter_id()

    with tx() as cur:
        dup = find_duplicate_hazard(cur, category, sector_id, lat, lng, landmark)
        if dup:
            _, counts = record_duplicate(cur, dup["id"], landmark, voter)
            return err(
                409, "DUPLICATE_HAZARD_REJECTED",
                f"This hazard is already on the board as ticket #{dup['ticket_code']} ({dup['match_reason']}). "
                "City crews can already see it.",
                duplicate_rejected=True,
                existing_ticket={
                    "id": dup["id"], "ticket_code": dup["ticket_code"], "category": dup["category"],
                    "landmark": dup["landmark"], "sector_id": dup["sector_id"], "status": dup["status"],
                    "upvotes": counts["upvotes"], "duplicate_reports_count": counts["duplicate_reports_count"],
                    "assigned_crew_id": dup["assigned_crew_id"], "distance_meters": dup["distance_meters"],
                })
        cur.execute("SELECT nextval('ticket_seq') AS n")
        code = f"HZ-{datetime.now(timezone.utc):%y%m}-{cur.fetchone()['n']}"
        cur.execute(
            """INSERT INTO hazards (ticket_code, category, landmark, sector_id, latitude, longitude,
                                    urgency, photo_url, description, citizen_contact)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (code, category, landmark, sector_id, lat, lng, urgency, photo, description, contact))
        hid = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO resolution_logs (hazard_id, action, crew_id, notes, metadata) VALUES (%s,'TICKET_CREATED','CITIZEN_PORTAL',%s,%s)",
            (hid, f"Report registered at '{landmark}'. Sector assigned: {sector_id}.",
             Json({"initial_urgency": urgency, "geotag": {"lat": lat, "lng": lng}})))
        cur.execute("INSERT INTO hazard_votes (hazard_id, voter) VALUES (%s,%s)", (hid, voter))
        hazard = fetch_detail(cur, hid, False)
    return jsonify(success=True, message=f"Hazard ticket #{code} created.", hazard=hazard), 201


@api.post("/hazards/<int:hid>/upvote")
def upvote(hid):
    if sec.rate_limited("vote", 60, 600):
        return err(429, "RATE_LIMITED", "Too many confirmations. Try again shortly.")
    with tx() as cur:
        cur.execute("SELECT 1 FROM hazards WHERE id = %s", (hid,))
        if not cur.fetchone():
            return err(404, "NOT_FOUND", f"Hazard ticket #{hid} not found.")
        cur.execute("INSERT INTO hazard_votes (hazard_id, voter) VALUES (%s,%s) ON CONFLICT DO NOTHING RETURNING 1",
                    (hid, sec.voter_id()))
        counted = cur.fetchone() is not None
        if counted:
            cur.execute("UPDATE hazards SET upvotes = upvotes + 1 WHERE id = %s", (hid,))
        cur.execute("SELECT upvotes FROM hazards WHERE id = %s", (hid,))
        votes = cur.fetchone()["upvotes"]
    return jsonify(success=True, hazard_id=hid, upvotes=votes, already_voted=not counted)


# ---------- crew endpoints (PIN required) ----------
@api.post("/crew/login")
def crew_login():
    if not sec.crew_state():
        raise sec.ApiError(401, "CREW_AUTH_REQUIRED", "Enter the crew PIN.")
    return jsonify(success=True)


def move(hid, allowed_from, to, action, crew, notes, meta=None, sets=None):
    """Atomic state transition: only applies if the ticket is still in an allowed state."""
    sets = sets or {}
    extra = "".join(f", {col} = %s" for col in sets)  # column names are internal constants
    with tx() as cur:
        cur.execute(f"UPDATE hazards SET status = %s, updated_at = now(){extra} "
                    "WHERE id = %s AND status = ANY(%s) RETURNING id",
                    (to, *sets.values(), hid, list(allowed_from)))
        if not cur.fetchone():
            cur.execute("SELECT status FROM hazards WHERE id = %s", (hid,))
            row = cur.fetchone()
            if not row:
                return err(404, "NOT_FOUND", f"Hazard ticket #{hid} not found.")
            return err(409, "INVALID_TRANSITION",
                       f"This ticket is already {row['status']}. Refresh the board and check its status.")
        cur.execute("INSERT INTO resolution_logs (hazard_id, action, crew_id, notes, metadata) VALUES (%s,%s,%s,%s,%s)",
                    (hid, action, crew, notes, Json(meta) if meta else None))
        hazard = fetch_detail(cur, hid, True)
    return jsonify(success=True, message=f"Ticket #{hazard['ticket_code']} is now {to}.", hazard=hazard)


def crew_id_field(d):
    crew = line(d.get("crew_id"), 60)
    if not crew:
        raise sec.ApiError(400, "MISSING_CREW", "Crew ID is required.")
    return crew


@api.post("/hazards/<int:hid>/acknowledge")
@sec.crew_required
def acknowledge(hid):
    d = body()
    notes = para(d.get("notes"), 500) or "Ticket triaged by the control room."
    return move(hid, ["REPORTED"], "ACKNOWLEDGED", "ACKNOWLEDGED", "DISPATCH-CTL", notes)


@api.post("/hazards/<int:hid>/dispatch")
@sec.crew_required
def dispatch(hid):
    d = body()
    crew = line(d.get("crew_id"), 60)
    if crew not in CREW_UNITS:
        return err(400, "INVALID_CREW", "Choose a crew unit from the list.")
    notes = para(d.get("notes"), 500) or f"Crew {crew} dispatched to site."
    return move(hid, ["REPORTED", "ACKNOWLEDGED"], "DISPATCHED", "CREW_DISPATCHED", crew, notes,
                {"dispatched_at": datetime.now(timezone.utc).isoformat()}, {"assigned_crew_id": crew})


@api.post("/hazards/<int:hid>/verify")
@sec.crew_required
def verify(hid):
    d = body()
    crew = crew_id_field(d)
    notes = para(d.get("notes"), 1000)
    if len(notes) < 5:
        return err(400, "MISSING_NOTES", "Describe what the crew found on site.")
    severity = line(d.get("verified_severity"), 10).capitalize()
    hours = d.get("estimated_hours")
    try:
        hours = None if hours in (None, "") else float(hours)
        if hours is not None and not (0 <= hours <= 240):
            raise ValueError
    except (TypeError, ValueError):
        return err(400, "INVALID_HOURS", "Estimated repair time must be between 0 and 240 hours.")
    sets = {"assigned_crew_id": crew}
    if severity in URGENCY_LEVELS:
        sets["urgency"] = severity
    meta = {"safety_perimeter": bool(d.get("safety_perimeter")), "verified_severity": severity or None,
            "estimated_hours": hours, "verified_at": datetime.now(timezone.utc).isoformat()}
    return move(hid, ["DISPATCHED"], "ON_SITE_VERIFIED", "ON_SITE_VERIFIED", crew,
                f"On-site verification: {notes}", meta, sets)


@api.post("/hazards/<int:hid>/resolve")
@sec.crew_required
def resolve(hid):
    d = body()
    crew = crew_id_field(d)
    notes = para(d.get("notes"), 1000)
    if len(notes) < 5:
        return err(400, "MISSING_NOTES", "Describe the repair and how safety was verified.")
    parts = line(d.get("parts_replaced"), 300)
    return move(hid, ["ON_SITE_VERIFIED", "IN_PROGRESS"], "RESOLVED", "RESOLVED", crew,
                f"Hazard resolved: {notes}" + (f" Parts: {parts}." if parts else ""),
                {"parts_replaced": parts, "resolved_at": datetime.now(timezone.utc).isoformat()})
