from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import uuid4


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


@dataclass(slots=True)
class SimulationAsset:
    source_path: str
    asset_type: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SimulationRun:
    run_id: str = field(default_factory=lambda: new_id("sim"))
    case_id: str | None = None
    code: str = "LAMMPS"
    task_type: str = "other"
    material_system: str | None = None
    potential_type: str | None = None
    lattice_type: str | None = None
    temperature_k: float | None = None
    pka_energy_kev: float | None = None
    pka_direction: list[float] | None = None
    timestep_ps: float | None = None
    box_size: float | None = None
    source_root: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    assets: list[SimulationAsset] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["assets"] = [asset.to_dict() for asset in self.assets]
        return payload


@dataclass(slots=True)
class ResearchCase:
    case_id: str
    title: str
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ResearchLink:
    case_id: str
    target_type: str
    target_id: str
    relation: str = "related"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
