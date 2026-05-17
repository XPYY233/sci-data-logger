from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any

from .models import SimulationAsset, SimulationRun

_VAR_RE = re.compile(r"^\s*variable\s+(\w+)\s+(?:equal|index)\s+(.+?)\s*(?:#.*)?$")
_VAR_REF_RE = re.compile(r"\$\{(\w+)\}")


def import_lammps_directory(source_root: Path, case_id: str | None = None) -> SimulationRun:
    input_path = _find_first(source_root, ["input.lmp", "in.lmp", "in", "in.txt"])
    if input_path is None:
        raise FileNotFoundError(f"No LAMMPS input file found under {source_root}")
    log_path = _find_first(source_root, ["log.lammps"])
    folder_index = _find_first(source_root, ["folder_name.csv"])
    metadata, warnings = parse_lammps_input(input_path)
    if log_path:
        metadata["log_metadata"] = parse_lammps_log(log_path)
    if folder_index:
        metadata["folder_index"] = parse_folder_index(folder_index)
    assets = [SimulationAsset(str(input_path), "lammps_input")]
    if log_path:
        assets.append(SimulationAsset(str(log_path), "lammps_log"))
    if folder_index:
        assets.append(SimulationAsset(str(folder_index), "folder_index"))
    for path in sorted(source_root.rglob("*.dump")):
        assets.append(SimulationAsset(str(path), "dump"))
    return SimulationRun(
        case_id=case_id,
        task_type=metadata.get("task_type", "other"),
        material_system=metadata.get("material_system"),
        potential_type=metadata.get("potential_type"),
        lattice_type=metadata.get("lattice_type"),
        temperature_k=metadata.get("temperature_k"),
        pka_energy_kev=metadata.get("pka_energy_kev"),
        pka_direction=metadata.get("pka_direction"),
        timestep_ps=metadata.get("timestep_ps"),
        box_size=metadata.get("box_size"),
        source_root=str(source_root),
        parameters=metadata,
        assets=assets,
        warnings=warnings,
    )


def _find_first(root: Path, names: list[str]) -> Path | None:
    for name in names:
        path = root / name
        if path.exists():
            return path
    return None


def parse_lammps_input(path: Path) -> tuple[dict[str, Any], list[str]]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    variables = _parse_variables(text)
    lattice_type, lattice_constant = _parse_lattice(text, variables)
    potential_type, potential_file = _parse_pair_style(text)
    material_system = _parse_material_system(text)
    task_type = _infer_task_type(text, variables)
    timestep = _parse_timestep(text, variables)
    direction = _numbers_from_variables(variables, ["d_x", "d_y", "d_z"])
    warnings: list[str] = []
    if not material_system:
        warnings.append("未识别材料体系。")
    if task_type == "other":
        warnings.append("未能可靠判断模拟任务类型。")
    metadata: dict[str, Any] = {
        "variables": variables,
        "task_type": task_type,
        "material_system": material_system,
        "potential_type": potential_type,
        "potential_file": potential_file,
        "lattice_type": lattice_type,
        "lattice_constant": lattice_constant,
        "temperature_k": _as_number(variables.get("env_temp") or variables.get("T")),
        "pka_energy_kev": _as_number(variables.get("E_PKA")),
        "pka_direction": direction,
        "timestep_ps": timestep,
        "box_size": _as_number(variables.get("box_r")),
    }
    return metadata, warnings


def _parse_variables(text: str) -> dict[str, Any]:
    variables: dict[str, Any] = {}
    for line in text.splitlines():
        match = _VAR_RE.match(line)
        if not match:
            continue
        name, raw = match.groups()
        first = raw.split()[0]
        variables[name] = _as_number(first) if _as_number(first) is not None else first
    return variables


def _resolve_token(token: str, variables: dict[str, Any]) -> Any:
    match = _VAR_REF_RE.fullmatch(token)
    if match:
        return variables.get(match.group(1))
    return _as_number(token) if _as_number(token) is not None else token


def _parse_lattice(text: str, variables: dict[str, Any]) -> tuple[str | None, Any]:
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) >= 3 and parts[0] == "lattice":
            return parts[1], _resolve_token(parts[2], variables)
    return None, None


def _parse_pair_style(text: str) -> tuple[str | None, str | None]:
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and parts[0] == "pair_style":
            return parts[1], parts[2] if len(parts) >= 3 else None
    return None, None


def _parse_material_system(text: str) -> str | None:
    for line in text.splitlines():
        parts = line.strip().split()
        if parts[:2] == ["labelmap", "atom"]:
            labels = [parts[i] for i in range(3, len(parts), 2) if i < len(parts)]
            if labels:
                return "".join(labels)
    masses = re.findall(r"variable\s+([A-Z][a-z]?)_mass\b", text)
    return "".join(masses) if masses else None


def _infer_task_type(text: str, variables: dict[str, Any]) -> str:
    lower = text.lower()
    if "e_pka" in {name.lower() for name in variables} or "velocity        center set" in lower:
        return "cascade"
    if "deform" in lower or "strain" in lower:
        return "tensile"
    return "other"


def _parse_timestep(text: str, variables: dict[str, Any]) -> float | None:
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and parts[0] == "timestep":
            value = _resolve_token(parts[1], variables)
            return _as_number(value)
    return None


def _numbers_from_variables(variables: dict[str, Any], keys: list[str]) -> list[float] | None:
    values = [_as_number(variables.get(key)) for key in keys]
    if any(value is None for value in values):
        return None
    return [float(value) for value in values if value is not None]


def _as_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except ValueError:
        return None


def parse_lammps_log(path: Path) -> dict[str, Any]:
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    metadata: dict[str, Any] = {}
    for line in lines:
        if line.startswith("LAMMPS"):
            metadata["lammps_version"] = line.replace("LAMMPS", "", 1).strip()
            break
    header: list[str] | None = None
    last_values: list[float] | None = None
    for line in lines:
        if line.strip().startswith("Step"):
            header = line.split()
            continue
        if header:
            try:
                values = [float(part) for part in line.split()]
            except ValueError:
                continue
            if len(values) == len(header):
                last_values = values
    if header and last_values:
        metadata["final_thermo"] = dict(zip(header, last_values, strict=False))
    return metadata


def parse_folder_index(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
        rows = [row for row in csv.reader(handle) if row]
    return [row[0] for row in rows[1:]] if rows and rows[0][0] == "DumpFolderName" else [row[0] for row in rows]
