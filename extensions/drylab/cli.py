from __future__ import annotations

import argparse
import json
from pathlib import Path

from .repository import DEFAULT_DB_PATH, get_case, query_runs
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

    show = sub.add_parser("show-case", help="Show a research case with links")
    show.add_argument("--case-id", required=True)
    show.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
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
    elif args.command == "show-case":
        payload = get_case(args.case_id, db_path=args.db_path)
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
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
