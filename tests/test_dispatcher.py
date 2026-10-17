"""
Integration tests against a real PostgreSQL database.

    TEST_DATABASE_URL=postgresql://user:pass@localhost:5432/testdb python3 -m unittest tests/test_dispatcher.py -v

WARNING: these tests TRUNCATE all tables. Only ever point TEST_DATABASE_URL at a throwaway database.
"""
import os
import sys
import threading
import unittest

TEST_URL = os.environ.get("TEST_DATABASE_URL")
if not TEST_URL:
    raise SystemExit("Set TEST_DATABASE_URL to a throwaway Postgres database.")
os.environ["DATABASE_URL"] = TEST_URL
os.environ["CREW_PIN"] = "246810"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import tx          # noqa: E402
from app.server import app     # noqa: E402

PIN = {"X-Crew-Pin": "246810"}
_ip = [0]


def fresh_ip():
    _ip[0] += 1
    return f"10.1.{_ip[0] // 250}.{_ip[0] % 250 + 1}"


def post(client, path, data=None, headers=None, ip=None):
    h = {"X-Forwarded-For": ip or fresh_ip(), **(headers or {})}
    return client.post(path, json=data or {}, headers=h)


def report(**kw):
    base = {"category": "ELECTRICAL", "landmark": "Opposite Central Metro Station Gate 2",
            "urgency": "Critical", "sector_id": "SEC-CENTRAL", "latitude": 12.9722,
            "longitude": 77.5951, "photo_url": "https://example.com/wire.jpg",
            "description": "Downed wire sparking.", "citizen_contact": "citizen@example.com"}
    base.update(kw)
    return base


class Dispatcher(unittest.TestCase):
    def setUp(self):
        with tx() as cur:
            cur.execute("TRUNCATE hazards, resolution_logs, hazard_votes RESTART IDENTITY CASCADE")
        self.c = app.test_client()

    def create(self, **kw):
        r = post(self.c, "/api/hazards", report(**kw))
        self.assertEqual(r.status_code, 201, r.get_json())
        return r.get_json()["hazard"]

    # ----- intake -----
    def test_create_and_no_pii_in_public_api(self):
        h = self.create()
        self.assertTrue(h["ticket_code"].startswith("HZ-"))
        self.assertNotIn("citizen_contact", h)
        pub = self.c.get("/api/hazards").get_json()["hazards"][0]
        self.assertNotIn("citizen_contact", pub)
        crew = self.c.get("/api/hazards", headers=PIN).get_json()["hazards"][0]
        self.assertEqual(crew["citizen_contact"], "citizen@example.com")

    def test_validation(self):
        for bad in ({"category": "NOPE"}, {"landmark": ""}, {"urgency": "Huge"},
                    {"photo_url": "javascript:alert(1)"}, {"latitude": None}, {"latitude": 999}):
            r = post(self.c, "/api/hazards", report(**bad))
            self.assertEqual(r.status_code, 400, bad)

    # ----- duplicate engine -----
    def test_duplicate_rejected_and_counters(self):
        first = self.create()
        r = post(self.c, "/api/hazards", report(landmark="Gate 2 of Central Metro", latitude=12.9724))
        self.assertEqual(r.status_code, 409)
        j = r.get_json()
        self.assertTrue(j["duplicate_rejected"])
        self.assertEqual(j["existing_ticket"]["ticket_code"], first["ticket_code"])
        self.assertEqual(j["existing_ticket"]["duplicate_reports_count"], 1)
        self.assertEqual(j["existing_ticket"]["upvotes"], 2)

    def test_same_network_cannot_inflate_counters(self):
        ip = "10.9.9.9"
        post(self.c, "/api/hazards", report(), ip=ip)
        for _ in range(3):
            r = post(self.c, "/api/hazards", report(), ip=ip)
            self.assertEqual(r.status_code, 409)
        self.assertEqual(r.get_json()["existing_ticket"]["upvotes"], 1)

    def test_no_false_duplicates(self):
        self.create()
        self.create(category="WATER_DRAINAGE")                                        # other category, same spot
        self.create(landmark="Whitefield Main Rd", sector_id="SEC-EAST",
                    latitude=12.9780, longitude=77.6400)                              # same category, far away
        self.assertEqual(len(self.c.get("/api/hazards").get_json()["hazards"]), 3)

    def test_concurrent_identical_reports_create_one_ticket(self):
        codes = []
        def go():
            codes.append(post(self.c, "/api/hazards", report()).status_code)
        threads = [threading.Thread(target=go) for _ in range(8)]
        [t.start() for t in threads]; [t.join() for t in threads]
        self.assertEqual(sorted(codes).count(201), 1, codes)
        self.assertEqual(self.c.get("/api/stats").get_json()["total_reported"], 1)

    # ----- crew auth + workflow -----
    def test_crew_endpoints_require_pin(self):
        h = self.create()
        url = f"/api/hazards/{h['id']}/dispatch"
        self.assertEqual(post(self.c, url, {"crew_id": "CREW-ELEC-09"}).status_code, 401)
        self.assertEqual(post(self.c, url, {"crew_id": "CREW-ELEC-09"}, {"X-Crew-Pin": "000000"}).status_code, 401)
        self.assertEqual(self.c.post("/api/crew/login", headers=PIN).status_code, 200)
        self.assertEqual(self.c.get("/api/hazards", headers={"X-Crew-Pin": "bad"}).status_code, 401)

    def test_pin_brute_force_lockout(self):
        ip = "10.7.7.7"
        codes = [self.c.post("/api/crew/login", headers={"X-Crew-Pin": f"bad{i}", "X-Forwarded-For": ip}).status_code
                 for i in range(12)]
        self.assertEqual(codes[:10], [401] * 10)
        self.assertEqual(codes[10], 429)

    def test_full_lifecycle_and_guards(self):
        h = self.create(); base = f"/api/hazards/{h['id']}"
        self.assertEqual(post(self.c, f"{base}/resolve", {"crew_id": "X", "notes": "too early!!"}, PIN).status_code, 409)
        self.assertEqual(post(self.c, f"{base}/acknowledge", {}, PIN).status_code, 200)
        self.assertEqual(post(self.c, f"{base}/acknowledge", {}, PIN).status_code, 409)
        self.assertEqual(post(self.c, f"{base}/dispatch", {"crew_id": "NOT-A-CREW"}, PIN).status_code, 400)
        r = post(self.c, f"{base}/dispatch", {"crew_id": "CREW-ELEC-09", "notes": "Truck out"}, PIN)
        self.assertEqual(r.get_json()["hazard"]["status"], "DISPATCHED")
        self.assertEqual(post(self.c, f"{base}/verify", {"crew_id": "CREW-ELEC-09", "notes": "x"}, PIN).status_code, 400)
        r = post(self.c, f"{base}/verify", {"crew_id": "CREW-ELEC-09", "verified_severity": "Medium",
                 "safety_perimeter": True, "estimated_hours": 2.5, "notes": "Line isolated, 15 m cordon."}, PIN)
        self.assertEqual(r.get_json()["hazard"]["urgency"], "Medium")
        r = post(self.c, f"{base}/resolve", {"crew_id": "CREW-ELEC-09", "notes": "Wire re-spliced and tested.",
                 "parts_replaced": "50 m cable"}, PIN)
        self.assertEqual(r.get_json()["hazard"]["status"], "RESOLVED")
        actions = [l["action"] for l in self.c.get(base).get_json()["logs"]]
        self.assertEqual(actions, ["TICKET_CREATED", "ACKNOWLEDGED", "CREW_DISPATCHED", "ON_SITE_VERIFIED", "RESOLVED"])
        # resolved fault can be reported again as a new ticket
        self.create()

    # ----- misc -----
    def test_upvote_once_per_network(self):
        h = self.create()
        r1 = post(self.c, f"/api/hazards/{h['id']}/upvote", ip="10.5.5.5").get_json()
        r2 = post(self.c, f"/api/hazards/{h['id']}/upvote", ip="10.5.5.5").get_json()
        self.assertEqual((r1["upvotes"], r1["already_voted"]), (2, False))
        self.assertEqual((r2["upvotes"], r2["already_voted"]), (2, True))

    def test_feed_sort_filters_stats_sectors(self):
        self.create(category="GAS_PIPELINE", urgency="Low", landmark="University Ave 4th Cross",
                    sector_id="SEC-WEST", latitude=12.9560, longitude=77.5412)
        self.create(urgency="Critical")
        order = [x["urgency"] for x in self.c.get("/api/hazards").get_json()["hazards"]]
        self.assertEqual(order, ["Critical", "Low"])
        self.assertEqual(self.c.get("/api/hazards?urgency=Low").get_json()["count"], 1)
        self.assertEqual(self.c.get("/api/hazards?search=university").get_json()["count"], 1)
        st = self.c.get("/api/stats").get_json()
        self.assertEqual((st["total_reported"], st["critical_active"]), (2, 1))
        secs = {s["id"]: s for s in self.c.get("/api/sectors").get_json()["sectors"]}
        self.assertEqual(secs["SEC-CENTRAL"]["active_hazards"], 1)

    def test_no_demo_endpoints_and_headers(self):
        self.create()
        self.assertIn(self.c.post("/api/reset-demo", headers=PIN).status_code, (404, 405))
        self.assertEqual(self.c.get("/api/stats").get_json()["total_reported"], 1)
        r = self.c.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Content-Security-Policy", r.headers)


if __name__ == "__main__":
    unittest.main()
