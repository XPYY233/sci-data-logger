from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from sci_data_logger.config import get_settings
from sci_data_logger.schemas import DraftExperimentRequest
from sci_data_logger.services.orchestrator import ExperimentOrchestrator

app = typer.Typer(help="Materials experiment record processing commands.")
console = Console()


@app.command()
def doctor() -> None:
    """Show runtime configuration without printing secrets."""

    settings = get_settings()
    console.print(
        {
            "app": settings.app_name,
            "version": settings.app_version,
            "qwen_base_url": settings.qwen_base_url,
            "qwen_vlm_model": settings.qwen_vlm_model,
            "dashscope_configured": bool(settings.dashscope_api_key),
            "instrument_registry": str(settings.instrument_registry),
        }
    )


@app.command()
def draft(
    experiment_id: Annotated[str, typer.Option(help="Experiment identifier.")],
    image: Annotated[
        list[Path],
        typer.Option("--image", "-i", help="Notebook image or text page path."),
    ] = None,
    instrument_file: Annotated[
        list[Path],
        typer.Option("--instrument-file", "-f", help="Instrument file or report path."),
    ] = None,
    operator: Annotated[str | None, typer.Option(help="Operator name.")] = None,
    project_id: Annotated[str | None, typer.Option(help="Project identifier.")] = None,
    group_id: Annotated[str | None, typer.Option(help="Group identifier.")] = None,
) -> None:
    """Create an experiment draft from local files."""

    request = DraftExperimentRequest(
        experiment_id=experiment_id,
        image_paths=image or [],
        instrument_file_paths=instrument_file or [],
        operator=operator,
        project_id=project_id,
        group_id=group_id,
    )
    record = ExperimentOrchestrator().create_draft(request)
    console.print_json(record.model_dump_json(indent=2))


if __name__ == "__main__":
    app()
