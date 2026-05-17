from __future__ import annotations

from pathlib import Path

from extensions.drylab.lammps import import_lammps_directory, parse_lammps_input
from extensions.drylab.repository import get_case, query_runs
from extensions.drylab.service import create_research_case, import_lammps_run, link_wet_experiment


LAMMPS_INPUT = """
variable lat_cont equal 3.183
variable env_temp equal 300
variable E_PKA equal 150
variable TS equal 0.001
variable box_r equal 65
variable d_x equal 0
variable d_y equal 0
variable d_z equal -1
lattice bcc ${lat_cont}
labelmap atom 1 Mo 2 Nb 3 Ta 4 V 5 W
pair_style mlip mlip.ini
timestep ${TS}
velocity        CENTER set ${vx} ${vy} ${vz} sum yes units box
""".strip()


def _make_run_dir(tmp_path: Path) -> Path:
    root = tmp_path / "run"
    root.mkdir()
    (root / "input.lmp").write_text(LAMMPS_INPUT, encoding="utf-8")
    (root / "log.lammps").write_text(
        "LAMMPS (22 Jul 2025)\nStep Temp TotEng\n0 300 -10\n100 301 -9\n", encoding="utf-8"
    )
    (root / "folder_name.csv").write_text(
        "DumpFolderName\n300K_150KeV_[00-1]_1\n", encoding="utf-8"
    )
    dump_dir = root / "dump" / "300K_150KeV_[00-1]_1"
    dump_dir.mkdir(parents=True)
    (dump_dir / "ref.dump").write_text("", encoding="utf-8")
    return root


def test_lammps_parser_extracts_cascade_metadata(tmp_path: Path) -> None:
    input_path = tmp_path / "input.lmp"
    input_path.write_text(LAMMPS_INPUT, encoding="utf-8")

    metadata, warnings = parse_lammps_input(input_path)

    assert metadata["material_system"] == "MoNbTaVW"
    assert metadata["task_type"] == "cascade"
    assert metadata["temperature_k"] == 300.0
    assert metadata["pka_energy_kev"] == 150.0
    assert metadata["pka_direction"] == [0.0, 0.0, -1.0]
    assert metadata["potential_type"] == "mlip"
    assert warnings == []


def test_drylab_sidecar_links_wet_and_dry_records(tmp_path: Path) -> None:
    db_path = tmp_path / "drylab.db"
    run_dir = _make_run_dir(tmp_path)

    create_research_case("CASE-001", "MoNbTaVW irradiation", db_path=db_path)
    link_wet_experiment("CASE-001", "EXP-001", db_path=db_path)
    run = import_lammps_run(run_dir, case_id="CASE-001", db_path=db_path)

    case = get_case("CASE-001", db_path=db_path)
    results = query_runs(
        material_system="MoNbTaVW",
        task_type="cascade",
        temperature_k=300.0,
        pka_energy_kev=150.0,
        potential_type="mlip",
        case_id="CASE-001",
        db_path=db_path,
    )

    assert run.material_system == "MoNbTaVW"
    assert any(link["target_type"] == "wet_experiment" for link in case["links"])
    assert any(link["target_type"] == "simulation_run" for link in case["links"])
    assert len(results) == 1
    assert results[0]["run_id"] == run.run_id


def test_import_lammps_directory_indexes_assets(tmp_path: Path) -> None:
    run = import_lammps_directory(_make_run_dir(tmp_path))
    asset_types = {asset.asset_type for asset in run.assets}

    assert {"lammps_input", "lammps_log", "folder_index", "dump"}.issubset(asset_types)
