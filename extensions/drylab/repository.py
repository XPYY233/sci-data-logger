from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import ResearchCase, ResearchLink, SimulationRun

DEFAULT_DB_PATH = Path(".local_data/extensions/drylab/drylab.db")


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
        CREATE TABLE IF NOT EXISTS research_cases (
            case_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS research_links (
            case_id TEXT NOT NULL,
            target_type TEXT NOT NULL,
            target_id TEXT NOT NULL,
            relation TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (case_id, target_type, target_id, relation)
        );
        CREATE TABLE IF NOT EXISTS simulation_runs (
            run_id TEXT PRIMARY KEY,
            case_id TEXT,
            code TEXT NOT NULL,
            task_type TEXT NOT NULL,
            material_system TEXT,
            potential_type TEXT,
            lattice_type TEXT,
            temperature_k REAL,
            pka_energy_kev REAL,
            pka_direction_json TEXT,
            timestep_ps REAL,
            box_size REAL,
            source_root TEXT,
            parameters_json TEXT NOT NULL,
            warnings_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS simulation_assets (
            run_id TEXT NOT NULL,
            source_path TEXT NOT NULL,
            asset_type TEXT NOT NULL,
            PRIMARY KEY (run_id, source_path)
        );
        """
    )
    conn.commit()


def create_case(case: ResearchCase, db_path: Path = DEFAULT_DB_PATH) -> ResearchCase:
    now = _utcnow()
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO research_cases(case_id, title, description, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(case_id)
            DO UPDATE SET title=excluded.title, description=excluded.description, updated_at=excluded.updated_at
            """,
            (case.case_id, case.title, case.description, now, now),
        )
        conn.commit()
    return case


def list_cases(db_path: Path = DEFAULT_DB_PATH) -> list[dict[str, Any]]:
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                c.*,
                COUNT(DISTINCT CASE WHEN l.target_type = 'simulation_run' THEN l.target_id END) AS simulation_run_count,
                COUNT(DISTINCT CASE WHEN l.target_type = 'wet_experiment' THEN l.target_id END) AS wet_experiment_count
            FROM research_cases c
            LEFT JOIN research_links l ON l.case_id = c.case_id
            GROUP BY c.case_id
            ORDER BY c.updated_at DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def get_case(case_id: str, db_path: Path = DEFAULT_DB_PATH) -> dict[str, Any] | None:
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM research_cases WHERE case_id = ?", (case_id,)).fetchone()
        if row is None:
            return None
        links = conn.execute(
            "SELECT target_type, target_id, relation FROM research_links WHERE case_id = ? ORDER BY target_type, target_id",
            (case_id,),
        ).fetchall()
    payload = dict(row)
    payload["links"] = [dict(link) for link in links]
    return payload


def save_run(run: SimulationRun, db_path: Path = DEFAULT_DB_PATH) -> SimulationRun:
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO simulation_runs(
                run_id, case_id, code, task_type, material_system, potential_type,
                lattice_type, temperature_k, pka_energy_kev, pka_direction_json,
                timestep_ps, box_size, source_root, parameters_json, warnings_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run.run_id,
                run.case_id,
                run.code,
                run.task_type,
                run.material_system,
                run.potential_type,
                run.lattice_type,
                run.temperature_k,
                run.pka_energy_kev,
                json.dumps(run.pka_direction),
                run.timestep_ps,
                run.box_size,
                run.source_root,
                json.dumps(run.parameters, ensure_ascii=False),
                json.dumps(run.warnings, ensure_ascii=False),
                _utcnow(),
            ),
        )
        conn.executemany(
            "INSERT INTO simulation_assets(run_id, source_path, asset_type) VALUES (?, ?, ?)",
            [(run.run_id, asset.source_path, asset.asset_type) for asset in run.assets],
        )
        if run.case_id:
            conn.execute(
                """
                INSERT OR IGNORE INTO research_links(case_id, target_type, target_id, relation, created_at)
                VALUES (?, 'simulation_run', ?, 'contains', ?)
                """,
                (run.case_id, run.run_id, _utcnow()),
            )
        conn.commit()
    return run


def link_target(link: ResearchLink, db_path: Path = DEFAULT_DB_PATH) -> ResearchLink:
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO research_links(case_id, target_type, target_id, relation, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (link.case_id, link.target_type, link.target_id, link.relation, _utcnow()),
        )
        conn.commit()
    return link


def get_run(run_id: str, db_path: Path = DEFAULT_DB_PATH) -> dict[str, Any] | None:
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM simulation_runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        assets = conn.execute(
            "SELECT source_path, asset_type FROM simulation_assets WHERE run_id = ? ORDER BY asset_type, source_path",
            (run_id,),
        ).fetchall()
    payload = _hydrate_run_row(row)
    payload["assets"] = [dict(asset) for asset in assets]
    return payload


def query_runs(
    *,
    material_system: str | None = None,
    task_type: str | None = None,
    temperature_k: float | None = None,
    pka_energy_kev: float | None = None,
    potential_type: str | None = None,
    case_id: str | None = None,
    db_path: Path = DEFAULT_DB_PATH,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    values: list[Any] = []
    filters = {
        "material_system": material_system,
        "task_type": task_type,
        "temperature_k": temperature_k,
        "pka_energy_kev": pka_energy_kev,
        "potential_type": potential_type,
        "case_id": case_id,
    }
    for key, value in filters.items():
        if value is not None:
            clauses.append(f"{key} = ?")
            values.append(value)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    with connect(db_path) as conn:
        rows = conn.execute(f"SELECT * FROM simulation_runs{where} ORDER BY created_at DESC", values).fetchall()
    return [_hydrate_run_row(row) for row in rows]


def _hydrate_run_row(row: sqlite3.Row) -> dict[str, Any]:
    payload = dict(row)
    payload["pka_direction"] = json.loads(payload.pop("pka_direction_json"))
    payload["parameters"] = json.loads(payload.pop("parameters_json"))
    payload["warnings"] = json.loads(payload.pop("warnings_json"))
    return payload
