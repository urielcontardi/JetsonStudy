from __future__ import annotations

import os


def index_db_path() -> str:
    return os.environ.get("ORWELL_INDEX_DB", "/var/lib/orwell/data/index.sqlite")


def data_dir() -> str:
    return os.environ.get("ORWELL_DATA_DIR", "/var/lib/orwell/data")
