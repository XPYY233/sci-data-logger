"""Generate docs/schema.html — a self-contained interactive viewer of all
pydantic models in sci_data_logger.schemas, plus a Mermaid relationship graph.

Run from the repo root:
    PYTHONPATH=src python scripts/generate_schema_html.py
"""

from __future__ import annotations

import html
import inspect
import sys
import typing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, get_args, get_origin

# Ensure we import from the worktree source, not a stale editable install.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from pydantic import BaseModel  # noqa: E402
from pydantic_core import PydanticUndefined  # noqa: E402

from sci_data_logger import schemas as schemas_module  # noqa: E402


def _is_model(obj: Any) -> bool:
    return inspect.isclass(obj) and issubclass(obj, BaseModel) and obj is not BaseModel


def _render_type(annotation: Any) -> str:
    """Pretty-print a type annotation in a way that's robust to | unions and generics."""
    import types as _types

    if annotation is type(None):
        return "None"
    if isinstance(annotation, type):
        return annotation.__name__
    origin = get_origin(annotation)
    args = get_args(annotation)
    # PEP 604 `int | None` => origin is types.UnionType; typing.Optional => origin is typing.Union.
    if origin is typing.Union or origin is getattr(_types, "UnionType", typing.Union):
        return " | ".join(_render_type(a) for a in args)
    if origin is None:
        s = str(annotation)
        return s.replace("typing.", "")
    origin_name = getattr(origin, "__name__", str(origin))
    if args:
        return f"{origin_name}[{', '.join(_render_type(a) for a in args)}]"
    return origin_name


def _render_default(field) -> str:
    if field.default is not PydanticUndefined:
        return repr(field.default)
    if field.default_factory is None:
        return "—"
    # Stable string for noisy id factories so docs/schema.html doesn't churn per run.
    factory_name = getattr(field.default_factory, "__qualname__", "") or getattr(
        field.default_factory, "__name__", ""
    )
    factory_src = ""
    try:
        factory_src = inspect.getsource(field.default_factory).strip()
    except (OSError, TypeError):
        pass
    if "new_id" in factory_src or "uuid" in factory_src.lower() or "datetime.now" in factory_src:
        return "factory (auto-generated)"
    if factory_name in {"list", "dict", "set", "tuple"}:
        return f"{factory_name}()"
    try:
        sample = field.default_factory()
        return f"factory → {sample!r}"
    except Exception:
        return "factory"


def _related_models(annotation: Any, all_models: dict[str, type]) -> set[str]:
    """Walk a type annotation, return any referenced model class names."""
    found: set[str] = set()

    def walk(t):
        if isinstance(t, type) and t.__name__ in all_models:
            found.add(t.__name__)
            return
        for arg in get_args(t):
            walk(arg)

    walk(annotation)
    return found


def _enum_values(enum_cls: type) -> list[str]:
    return [str(member.value) for member in enum_cls]  # type: ignore[attr-defined]


def _section_for_model(model_cls: type, all_models: dict[str, type]) -> str:
    fields = model_cls.model_fields
    rows = []
    for name, f in fields.items():
        type_str = _render_type(f.annotation)
        default_str = _render_default(f)
        desc = html.escape(f.description or "")
        related = _related_models(f.annotation, all_models)
        related_html = "".join(
            f'<a class="ref" href="#{name}">{name}</a>' for name in sorted(related)
        )
        rows.append(
            f"<tr><td class='fname'><code>{html.escape(name)}</code></td>"
            f"<td class='ftype'><code>{html.escape(type_str)}</code>{related_html}</td>"
            f"<td class='fdefault'><code>{html.escape(default_str)}</code></td>"
            f"<td class='fdesc'>{desc}</td></tr>"
        )
    doc = inspect.getdoc(model_cls) or ""
    rows_html = "\n".join(rows) or "<tr><td colspan=4><em>(no fields)</em></td></tr>"
    return f"""
    <section id="{model_cls.__name__}" class="model">
      <h2>{model_cls.__name__}</h2>
      <p class="docstring">{html.escape(doc)}</p>
      <table>
        <thead><tr><th>Field</th><th>Type</th><th>Default</th><th>Description</th></tr></thead>
        <tbody>{rows_html}</tbody>
      </table>
    </section>
    """


def _mermaid_graph(all_models: dict[str, type]) -> str:
    """Build a Mermaid flowchart of model → model references."""
    edges: list[tuple[str, str, str]] = []
    for model_name, model_cls in all_models.items():
        for fname, f in model_cls.model_fields.items():
            for related in _related_models(f.annotation, all_models):
                if related == model_name:
                    continue
                edges.append((model_name, related, fname))
    edges = sorted(set(edges))
    lines = ["flowchart LR"]
    nodes = sorted(set([e[0] for e in edges] + [e[1] for e in edges]))
    for n in nodes:
        lines.append(f"  {n}[{n}]")
    for a, b, label in edges:
        lines.append(f"  {a} -- {label} --> {b}")
    return "\n".join(lines)


def main() -> None:
    all_models: dict[str, type] = {}
    enums: dict[str, type] = {}
    for name in dir(schemas_module):
        obj = getattr(schemas_module, name)
        if _is_model(obj):
            all_models[name] = obj
        elif inspect.isclass(obj) and hasattr(obj, "__members__"):
            # StrEnum / Enum classes
            if obj.__module__ == "sci_data_logger.schemas":
                enums[name] = obj

    # Sort models by a natural grouping: catalogs first, then leaf models, then top-level.
    grouping_order = [
        "ExperimentRecord",
        "ExperimentSummary",
        "ExperimentEvent",
        "PagePacket",
        "MeasurementPacket",
        "Material",
        "Instrument",
        "Sample",
        "MaterialInput",
        "InstrumentProfile",
        "ProtocolStep",
        "EventIO",
        "EventOutput",
        "FieldValue",
        "EvidenceRef",
        "DataAsset",
        "ReviewIssue",
        "DraftExperimentRequest",
        "DraftExperimentMetadataRequest",
    ]
    sorted_models = sorted(
        all_models.items(),
        key=lambda kv: (
            grouping_order.index(kv[0]) if kv[0] in grouping_order else 999,
            kv[0],
        ),
    )

    sidebar_links = "\n".join(
        f'<li><a href="#{name}">{name}</a></li>' for name, _ in sorted_models
    )
    sections = "\n".join(_section_for_model(cls, all_models) for _, cls in sorted_models)

    enum_sections = []
    for name, enum_cls in sorted(enums.items()):
        values = _enum_values(enum_cls)
        items = "".join(f"<li><code>{html.escape(v)}</code></li>" for v in values)
        enum_sections.append(
            f'<section id="{name}" class="enum"><h2>{name}</h2>'
            f'<p class="docstring">{html.escape(inspect.getdoc(enum_cls) or "")}</p>'
            f'<ul class="enum-values">{items}</ul></section>'
        )

    mermaid = _mermaid_graph(all_models)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    html_out = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>sci_data_logger schema</title>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
<style>
  :root {{ color-scheme: light dark; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", sans-serif;
    margin: 0;
    background: #fafafa;
    color: #222;
  }}
  @media (prefers-color-scheme: dark) {{
    body {{ background: #1a1a1a; color: #ddd; }}
    .sidebar {{ background: #222; border-right: 1px solid #333; }}
    .sidebar a {{ color: #88c0d0; }}
    table {{ background: #2a2a2a; }}
    th, td {{ border-color: #444; }}
    th {{ background: #333; }}
    code {{ background: #333; color: #f0c0a0; }}
    a.ref {{ background: #2a4a5a; color: #88c0d0; }}
    .docstring {{ color: #999; }}
    h2 {{ border-bottom: 2px solid #4a90d9; }}
    .mermaid-wrap {{ background: #2a2a2a; }}
  }}
  .layout {{ display: flex; min-height: 100vh; }}
  .sidebar {{
    width: 240px; flex: none;
    background: #fff;
    border-right: 1px solid #ddd;
    padding: 16px;
    overflow-y: auto;
    position: sticky; top: 0; height: 100vh;
  }}
  .sidebar h1 {{ font-size: 14px; margin: 0 0 12px; color: #888; text-transform: uppercase; letter-spacing: 0.05em; }}
  .sidebar ul {{ list-style: none; padding: 0; margin: 0 0 16px; }}
  .sidebar li a {{ display: block; padding: 4px 6px; font-size: 13px; text-decoration: none; color: #2a6ed6; border-radius: 3px; }}
  .sidebar li a:hover {{ background: rgba(42,110,214,0.1); }}
  main {{ flex: 1; padding: 24px 32px; max-width: 1100px; }}
  h1.title {{ font-size: 26px; margin-top: 0; }}
  h2 {{ font-size: 20px; margin-top: 32px; padding-bottom: 4px; border-bottom: 2px solid #4a90d9; }}
  .mermaid-wrap {{
    background: #fff; border-radius: 6px; padding: 16px;
    border: 1px solid #ddd; overflow-x: auto; margin-bottom: 32px;
  }}
  table {{
    border-collapse: collapse; width: 100%; background: #fff;
    font-size: 13px; margin-bottom: 8px;
  }}
  th, td {{ border: 1px solid #e0e0e0; padding: 6px 10px; text-align: left; vertical-align: top; }}
  th {{ background: #f0f4f8; font-weight: 600; }}
  td.fname {{ width: 22%; }}
  td.ftype {{ width: 30%; }}
  td.fdefault {{ width: 18%; }}
  td.fdesc {{ width: 30%; color: #555; }}
  code {{
    background: #f0f0f0; padding: 1px 4px; border-radius: 3px;
    font-family: ui-monospace, "SF Mono", Menlo, monospace;
    font-size: 12px;
  }}
  a.ref {{
    display: inline-block; margin-left: 4px; padding: 0 4px;
    background: #e8f1fd; color: #2a6ed6; border-radius: 3px;
    text-decoration: none; font-size: 11px;
  }}
  a.ref:hover {{ background: #c8e0fd; }}
  .docstring {{ color: #666; font-size: 13px; font-style: italic; }}
  .meta {{ color: #888; font-size: 12px; margin-bottom: 24px; }}
  .enum ul {{ list-style: none; padding: 0; display: flex; flex-wrap: wrap; gap: 6px; }}
  .enum li {{ background: #fff7ed; padding: 4px 8px; border-radius: 3px; border: 1px solid #fed7aa; }}
  section {{ margin-bottom: 28px; }}
</style>
</head>
<body>
<div class="layout">
  <aside class="sidebar">
    <h1>Models</h1>
    <ul>{sidebar_links}</ul>
    <h1>Enums</h1>
    <ul>{"".join(f'<li><a href="#{n}">{n}</a></li>' for n in sorted(enums))}</ul>
    <h1>Sections</h1>
    <ul><li><a href="#graph">Relationship graph</a></li></ul>
  </aside>
  <main>
    <h1 class="title">sci_data_logger · schema</h1>
    <p class="meta">Generated {now} · {len(all_models)} models · {len(enums)} enums · auto-generated from <code>sci_data_logger.schemas</code></p>

    <section id="graph">
      <h2>Relationship graph</h2>
      <div class="mermaid-wrap"><pre class="mermaid">{mermaid}</pre></div>
    </section>

    {sections}
    {"".join(enum_sections)}
  </main>
</div>
<script>mermaid.initialize({{ startOnLoad: true, theme: window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'default' }});</script>
</body>
</html>
"""

    out_path = ROOT / "docs" / "schema.html"
    out_path.write_text(html_out, encoding="utf-8")
    print(f"Wrote {out_path} ({len(html_out):,} bytes, {len(all_models)} models, {len(enums)} enums)")


if __name__ == "__main__":
    main()
