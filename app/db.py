"""PostgreSQL access layer (works with Neon, Supabase, or any Postgres)."""
import time
from contextlib import contextmanager

import psycopg2
import psycopg2.extras

from app.config import DATABASE_URL, MUNICIPAL_SECTORS

SCHEMA = """
CREATE TABLE IF NOT EXISTS sectors (
    id     TEXT PRIMARY KEY,
    name   TEXT NOT NULL,
    zone   TEXT NOT NULL,
    depot  TEXT NOT NULL,
    lat    DOUBLE PRECISION NOT NULL,
    lng    DOUBLE PRECISION NOT NULL,
    color  TEXT NOT NULL
);

CREATE SEQUENCE IF NOT EXISTS ticket_seq START 1001;

CREATE TABLE IF NOT EXISTS hazards (
    id                      BIGSERIAL PRIMARY KEY,
    ticket_code             TEXT UNIQUE NOT NULL,
    category                TEXT NOT NULL,
    landmark                TEXT NOT NULL,
    sector_id               TEXT NOT NULL REFERENCES sectors(id),
    latitude                DOUBLE PRECISION NOT NULL,
    longitude               DOUBLE PRECISION NOT NULL,
    urgency                 TEXT NOT NULL CHECK (urgency IN ('Low','Medium','Critical')),
    photo_url               TEXT NOT NULL DEFAULT '',
    description             TEXT NOT NULL DEFAULT '',
    citizen_contact         TEXT NOT NULL DEFAULT '',
    status                  TEXT NOT NULL DEFAULT 'REPORTED'
        CHECK (status IN ('REPORTED','ACKNOWLEDGED','DISPATCHED','ON_SITE_VERIFIED','IN_PROGRESS','RESOLVED')),
    assigned_crew_id        TEXT,
    upvotes                 INTEGER NOT NULL DEFAULT 1,
    duplicate_reports_count INTEGER NOT NULL DEFAULT 0,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS resolution_logs (
    id         BIGSERIAL PRIMARY KEY,
    hazard_id  BIGINT NOT NULL REFERENCES hazards(id) ON DELETE CASCADE,
    action     TEXT NOT NULL,
    crew_id    TEXT,
    notes      TEXT NOT NULL,
    metadata   JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS hazard_votes (
    hazard_id BIGINT NOT NULL REFERENCES hazards(id) ON DELETE CASCADE,
    voter     TEXT NOT NULL,
    PRIMARY KEY (hazard_id, voter)
);

CREATE INDEX IF NOT EXISTS idx_hazards_status   ON hazards (status);
CREATE INDEX IF NOT EXISTS idx_hazards_category ON hazards (category) WHERE status <> 'RESOLVED';
CREATE INDEX IF NOT EXISTS idx_hazards_sector   ON hazards (sector_id);
CREATE INDEX IF NOT EXISTS idx_logs_hazard      ON resolution_logs (hazard_id, created_at);
"""


def connect():
    """Open a connection, retrying briefly so a sleeping Neon compute can wake up."""
    last = None
    for attempt in range(4):
        try:
            return psycopg2.connect(
                DATABASE_URL,
                cursor_factory=psycopg2.extras.RealDictCursor,
                connect_timeout=15,
            )
        except psycopg2.OperationalError as exc:
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise last


@contextmanager
def tx():
    """One request = one transaction. Commits on success, rolls back on error."""
    conn = connect()
    try:
        with conn.cursor() as cur:
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Create tables and sync the municipal sector reference data. No demo data."""
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_lock(727274)")  # serialise concurrent worker boots
            cur.execute(SCHEMA)
            for sid, s in MUNICIPAL_SECTORS.items():
                cur.execute(
                    """INSERT INTO sectors (id, name, zone, depot, lat, lng, color)
                       VALUES (%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name, zone=EXCLUDED.zone,
                         depot=EXCLUDED.depot, lat=EXCLUDED.lat, lng=EXCLUDED.lng, color=EXCLUDED.color""",
                    (sid, s["name"], s["zone"], s["depot"], s["center"]["lat"], s["center"]["lng"], s["color"]),
                )
        conn.commit()
    finally:
        conn.close()
