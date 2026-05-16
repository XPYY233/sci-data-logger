# Project Conventions — sci_data_logger

This file is read by Claude Code at session start. Keep it short and authoritative.

## GitHub

- github: **yes** (private)
- Remote: `https://github.com/yinliang420/sci-data-logger`
- Default branch on remote: `claude/elated-bohr-f98b74` (initial push branch; will migrate to `main` once a PR lands)
- Rule: never `git push` to `main` / `master` directly. All work goes via feature branch + `gh pr create`.
- Per-round workflow (defined in `~/.claude/projects/-Users-ylll/memory/feedback_new_project_workflow.md`):
  1. Feature branch off the active default.
  2. After implementation, run a `code-reviewer` Agent over the diff; relay verdict to user.
  3. Write a private report to `reports/report_YYYY-MM-DD_<title>.md` (gitignored).
  4. Open PR via `gh pr create`.

## Code

- Python 3.11+, pydantic v2, FastAPI, SQLModel, openai SDK, tenacity, pypdfium2, Pillow.
- Tests: `PYTHONPATH=src python -m pytest tests/ -q`. Baseline as of feat branch creation: **57 passing**.
- Editable install at repo root: `pip install -e ".[dev]"`. The root `conftest.py` prepends `src/` to sys.path so worktrees don't get shadowed by the outer editable install.
- Domain entry points to know:
  - `src/sci_data_logger/services/orchestrator.py` — cross-page catalog merge + event resolve + reconcile.
  - `src/sci_data_logger/services/document.py` — VLM dispatch (image / PDF / text) → `PagePacket`.
  - `src/sci_data_logger/db/repository.py` — SQLite upsert; record stored as JSON blob.
  - `src/sci_data_logger/schemas.py` — pydantic models (single source of truth).

## Data

- `tests/test_data/` (106 MB): real lab notebook photos. Private-repo only. Never copy to public branches / public Gists.
- `reports/` is gitignored. Local-only.

## Do-not-do

- Don't add OpenCV (kept the deskew path Pillow-only intentionally).
- Don't add Alembic / migrations yet — schema still evolving in Phase 1/2.
- Don't widen pyproject deps without a clear reason; current set is intentionally tight.
