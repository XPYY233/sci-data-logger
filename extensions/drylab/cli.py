from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from .repository import DEFAULT_DB_PATH, get_case, get_run, list_cases, query_runs
from .service import create_research_case, import_lammps_run, link_wet_experiment


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Dry-lab record add-on CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create-case", help="Create or update a research case")
    create.add_argument("--case-id", required=True)
    create.add_argument("--title", required=True)
    create.add_argument("--description", default="")
    create.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)

    link = sub.add_parser("link-experiment", help="Link a wet experiment to a research case")
    link.add_argument("--case-id", required=True)
    link.add_argument("--experiment-id", required=True)
    link.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)

    import_cmd = sub.add_parser("import-lammps", help="Import one LAMMPS directory")
    import_cmd.add_argument("--source-root", type=Path, required=True)
    import_cmd.add_argument("--case-id")
    import_cmd.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)

    query = sub.add_parser("query-runs", help="Search imported simulation runs")
    query.add_argument("--material-system")
    query.add_argument("--task-type")
    query.add_argument("--temperature-k", type=float)
    query.add_argument("--pka-energy-kev", type=float)
    query.add_argument("--potential-type")
    query.add_argument("--case-id")
    query.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)

    cases = sub.add_parser("list-cases", help="List stored research cases")
    cases.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)

    show = sub.add_parser("show-case", help="Show a research case with links")
    show.add_argument("--case-id", required=True)
    show.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)

    run = sub.add_parser("show-run", help="Show one simulation run with assets")
    run.add_argument("--run-id", required=True)
    run.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)

    export = sub.add_parser("export-runs", help="Export filtered simulation runs as CSV")
    export.add_argument("--material-system")
    export.add_argument("--task-type")
    export.add_argument("--temperature-k", type=float)
    export.add_argument("--pka-energy-kev", type=float)
    export.add_argument("--potential-type")
    export.add_argument("--case-id")
    export.add_argument("--output", type=Path, required=True)
    export.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "create-case":
        payload = create_research_case(
            args.case_id, args.title, args.description, db_path=args.db_path
        ).to_dict()
    elif args.command == "link-experiment":
        payload = link_wet_experiment(
            args.case_id, args.experiment_id, db_path=args.db_path
        ).to_dict()
    elif args.command == "import-lammps":
        payload = import_lammps_run(
            args.source_root, case_id=args.case_id, db_path=args.db_path
        ).to_dict()
    elif args.command == "list-cases":
        payload = list_cases(db_path=args.db_path)
    elif args.command == "show-case":
        payload = get_case(args.case_id, db_path=args.db_path)
    elif args.command == "show-run":
        payload = get_run(args.run_id, db_path=args.db_path)
    else:
        payload = query_runs(
            material_system=args.material_system,
            task_type=args.task_type,
            temperature_k=args.temperature_k,
            pka_energy_kev=args.pka_energy_kev,
            potential_type=args.potential_type,
            case_id=args.case_id,
            db_path=args.db_path,
        )
        if args.command == "export-runs":
            _export_runs_csv(payload, args.output)
            payload = {"exported": len(payload), "output": str(args.output)}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _export_runs_csv(rows: list[dict], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "run_id",
        "case_id",
        "code",
        "task_type",
        "material_system",
        "potential_type",
        "lattice_type",
        "temperature_k",
        "pka_energy_kev",
        "timestep_ps",
        "box_size",
        "source_root",
        "created_at",
    ]
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in fields})


if __name__ == "__main__":
    raise SystemExit(main())
