"""Flask application: REST API plus the static dispatch board."""
import os
from datetime import date, datetime
from decimal import Decimal

from flask import Flask, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from app import config
from app.db import init_db
from app.routes import api
from app.security import ApiError

STATIC_DIR = os.path.join(config.BASE_DIR, "static")

CSP = ("default-src 'self'; script-src 'self' https://unpkg.com; "
       "style-src 'self' 'unsafe-inline' https://unpkg.com; img-src 'self' data: https:; "
       "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")


def _json_default(o):
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    if isinstance(o, Decimal):
        return float(o)
    raise TypeError(f"Not serialisable: {type(o)}")


def create_app():
    if not config.DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set.")
    if len(config.CREW_PIN) < 6:
        raise RuntimeError("CREW_PIN must be set and at least 6 characters.")

    app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="")
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)  # real client IP behind Render's proxy
    app.config.update(SEND_FILE_MAX_AGE_DEFAULT=0, MAX_CONTENT_LENGTH=64 * 1024)
    app.json.sort_keys = False
    app.json.default = _json_default

    init_db()
    app.register_blueprint(api, url_prefix="/api")

    @app.errorhandler(ApiError)
    def on_api_error(e):
        return jsonify(error=e.code, message=e.message), e.status

    @app.errorhandler(404)
    def on_404(_e):
        if request.path.startswith("/api/"):
            return jsonify(error="NOT_FOUND", message="No such endpoint."), 404
        return send_from_directory(STATIC_DIR, "index.html")

    @app.errorhandler(413)
    def on_413(_e):
        return jsonify(error="TOO_LARGE", message="Request is too large."), 413

    @app.errorhandler(Exception)
    def on_error(e):
        if isinstance(e, HTTPException):
            return jsonify(error=e.name.upper().replace(" ", "_"), message=e.description), e.code
        app.logger.exception(e)
        return jsonify(error="SERVER_ERROR", message="Something went wrong on our side. Try again in a moment."), 500

    @app.after_request
    def headers(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Content-Security-Policy"] = CSP
        if request.path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.get("/")
    def index():
        return send_from_directory(STATIC_DIR, "index.html")

    return app


app = create_app()
