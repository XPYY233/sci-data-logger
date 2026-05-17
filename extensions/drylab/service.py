from __future__ import annotations

from pathlib import Path

from .lammps import import_lammps_directory
from .models import ResearchCase, ResearchLink, SimulationRun
from .repository import DEFAULT_DB_PATH, create_case, get_case, link_target, query_runs, save_run


def create_research_case(
    case_id: str,
    title: str,
    description: str = "",
    *,
    db_path: Path = DEFAULT_DB_PATH,
) -> ResearchCase:
    return create_case(ResearchCase(case_id=case_id, title=title, description=description), db_path)


def link_wet_experiment(
    case_id: str,
    experiment_id: str,
    *,
    db_path: Path = DEFAULT_DB_PATH,
) -> ResearchLink:
    return link_target(
        ResearchLink(case_id=case_id, target_type="wet_experiment", target_id=experiment_id),
        db_path,
    )


def import_lammps_run(
    source_root: Path,
    *,
    case_id: str | None = None,
    db_path: Path = DEFAULT_DB_PATH,
) -> SimulationRun:
    run = import_lammps_directory(source_root, case_id=case_id)
    return save_run(run, db_path)


__all__ = [
    "create_research_case",
    "get_case",
    "import_lammps_run",
    "link_wet_experiment",
    "query_runs",
]
