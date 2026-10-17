# MUNI-DISPATCH: Municipal Hazard & Utility Outage Dispatcher (PS-CIV-04)

Citizens report geotagged infrastructure hazards. Duplicates in the same sector are rejected and merged into the
existing ticket. Municipal crews (PIN-protected) acknowledge, dispatch, verify on site and resolve tickets, and every
step is written to an audit log.

Stack: Flask + gunicorn, PostgreSQL (Neon), vanilla JS frontend with Leaflet/OpenStreetMap (SVG grid fallback offline).

## Environment variables
| Name | Required | Purpose |
|---|---|---|
| DATABASE_URL | yes | Postgres connection string (Neon, with `sslmode=require`) |
| CREW_PIN | yes | Shared PIN for field crews, at least 6 characters |
| PORT | no | Set automatically by Render |
| DUPLICATE_RADIUS_METERS | no | Default 350 |

The server refuses to start without `DATABASE_URL` and a valid `CREW_PIN`. Tables are created on first boot. No demo data is ever inserted.

## Run locally
    pip install -r requirements.txt
    export DATABASE_URL="postgresql://..."  CREW_PIN="583921"
    python3 run.py          # http://localhost:8080

## Tests (use a throwaway database: they TRUNCATE all tables)
    TEST_DATABASE_URL="postgresql://..." python3 -m unittest tests/test_dispatcher.py -v

## API
Public: `GET /api/hazards` `GET /api/hazards/:id` `GET /api/sectors` `GET /api/stats` `GET /api/health`
`POST /api/hazards` (201, or 409 with the existing ticket) `POST /api/hazards/:id/upvote`

Crew (header `X-Crew-Pin`): `POST /api/crew/login`, `POST /api/hazards/:id/{acknowledge|dispatch|verify|resolve}`

Status flow: REPORTED, ACKNOWLEDGED, DISPATCHED, ON_SITE_VERIFIED, RESOLVED. Each transition is atomic and only valid from
the correct previous state.

## Security notes
- Crew actions are enforced on the server (constant-time PIN check, lockout after 10 wrong tries per 10 minutes).
- Citizen contact details are only returned to signed-in crews.
- All user text is escaped in the UI; photo links must be http(s); a Content-Security-Policy is sent.
- Reports are rate limited (10 per 10 minutes per network); one confirmation per network per ticket.
- Duplicate checks run under a per-category database lock, so simultaneous identical reports create one ticket.
