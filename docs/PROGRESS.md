# Build progress

## Phase 1 — feat/core
- Package `jobapp` (src layout, hatchling, `uv sync`), CLI skeleton (typer+rich) with every command from §9
  wired (later phases fill them in). Tracebacks go to `$JOBAPP_HOME/logs/jobapp.log`, console stays plain English.
- `config.py`: pydantic v2 models for §3 (`extra=forbid`), friendly errors with "did you mean" for unknown keys
  and bad enum values, YAML syntax errors with line/column + tab hint.
- `db/`: SQLite WAL, `PRAGMA user_version` migrations (`001_init.sql`: jobs/runs/builds + FTS5 with triggers,
  plus `hidden`/`hidden_reason` for the "why hidden" view). Re-poll upsert never touches status/done/notes/hand-saved JD.
- `jobapp init` copies `examples/profile/` (Alex Example config, 1-page resume.tex with SKILLS markers, business keyword bank).
- `doctor` (partial): python, deps, TeX engine, pandoc, pdftotext, config, resume, DB version, last runs, connectors.
- Connectors (§8): Protocol, NullConnector, jsonl reference; errors captured to logs/connector_errors.json and shown in doctor.
- `scripts/privacy_scan.sh` (+ tests that it detects home paths / phones / tokens). CI workflow (not pushed).
- Tools installed to ~/.local: uv 0.13.1 (pip --user), pandoc 3.5 (static). TeX: system latexmk/pdflatex.
- Tests: 30 passed (offline).
- Acceptance: `jobapp init && jobapp config validate && pytest` ✔
PHASE 1: DONE
