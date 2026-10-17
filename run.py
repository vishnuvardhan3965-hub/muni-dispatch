#!/usr/bin/env python3
"""Local development entry point. Production uses gunicorn (see render.yaml)."""
from app import config
from app.server import app

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=config.PORT, threaded=True)
