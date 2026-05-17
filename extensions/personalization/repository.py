from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

DEFAULT_DB_PATH = Path(".local_data/extensions/personalization/personalization.db")


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS profiles (
            profile_type TEXT NOT NULL,
            profile_id TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (profile_type, profile_id)
        );
        CREATE TABLE IF NOT EXISTS analysis_runs (
            run_id TEXT PRIMARY KEY,
            experiment_id TEXT,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )
    conn.commit()


def upsert_profile(
    profile_type: str,
    profile_id: str,
    payload: dict,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO profiles(profile_type, profile_id, payload_json, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(profile_type, profile_id)
            DO UPDATE SET payload_json=excluded.payload_json, updated_at=excluded.updated_at
            """,
            (profile_type, profile_id, json.dumps(payload, ensure_ascii=False), _utcnow()),
        )
        conn.commit()


def save_analysis_run(
    payload: dict,
    experiment_id: str | None = None,
    db_path: Path = DEFAULT_DB_PATH,
) -> str:
    run_id = f"wet_{uuid4().hex[:12]}"
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO analysis_runs(run_id, experiment_id, payload_json, created_at) VALUES (?, ?, ?, ?)",
            (run_id, experiment_id, json.dumps(payload, ensure_ascii=False), _utcnow()),
        )
        conn.commit()
    return run_id
