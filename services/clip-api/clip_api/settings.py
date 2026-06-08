from __future__ import annotations

import os


def index_db_path() -> str:
    return os.environ.get("ORWELL_INDEX_DB", "/var/lib/orwell/data/index.sqlite")


def data_dir() -> str:
    return os.environ.get("ORWELL_DATA_DIR", "/var/lib/orwell/data")


def events_dir() -> str:
    return os.environ.get("ORWELL_EVENTS_DIR", "/var/lib/orwell/events")


def config_path() -> str:
    return os.environ.get("ORWELL_CONFIG", "/app/config/orwell.yaml")
