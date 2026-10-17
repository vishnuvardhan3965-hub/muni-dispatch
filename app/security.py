"""Crew authentication (shared PIN), brute-force protection and rate limiting."""
import hashlib
import hmac
import threading
import time
from functools import wraps

from flask import request

from app.config import CREW_PIN

_lock = threading.Lock()
_hits = {}


class ApiError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def client_ip() -> str:
    return request.remote_addr or "unknown"


def _recent(bucket, ip, window):
    now = time.time()
    arr = [t for t in _hits.get((bucket, ip), []) if now - t < window]
    _hits[(bucket, ip)] = arr
    if len(_hits) > 5000:  # opportunistic cleanup
        for k in [k for k, v in _hits.items() if not v]:
            _hits.pop(k, None)
    return arr, now


def rate_limited(bucket: str, limit: int, window: int) -> bool:
    """Record a hit; return True if the caller is over the limit."""
    with _lock:
        arr, now = _recent(bucket, client_ip(), window)
        if len(arr) >= limit:
            return True
        arr.append(now)
        return False


def voter_id() -> str:
    """Anonymous, salted per-network identifier used to dedupe upvotes."""
    return hashlib.sha256(f"{client_ip()}|{CREW_PIN}".encode()).hexdigest()[:32]


def crew_state() -> bool:
    """
    False  -> no PIN header (public caller)
    True   -> valid PIN
    raises -> 401 for a wrong PIN, 429 after 10 failures in 10 minutes
    """
    given = request.headers.get("X-Crew-Pin", "")
    if not given:
        return False
    ip = client_ip()
    with _lock:
        if len(_recent("pinfail", ip, 600)[0]) >= 10:
            raise ApiError(429, "TOO_MANY_ATTEMPTS", "Too many failed PIN attempts. Try again in 10 minutes.")
    if hmac.compare_digest(given.encode(), CREW_PIN.encode()):
        return True
    with _lock:
        arr, now = _recent("pinfail", ip, 600)
        arr.append(now)
    raise ApiError(401, "INVALID_PIN", "Crew PIN is incorrect.")


def crew_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not crew_state():
            raise ApiError(401, "CREW_AUTH_REQUIRED", "Crew sign-in is required for this action.")
        return fn(*args, **kwargs)
    return wrapper
