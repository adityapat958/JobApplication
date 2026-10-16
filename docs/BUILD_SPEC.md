# JobApplication — Build Spec (v0.1)

Public repo `JobApplication`. A job-search assistant that a **non-technical user on macOS** runs
**through Claude Code or Claude Desktop**. It finds jobs on sites they choose, filters them by their
rules, scores each job against their resume keywords, and builds a tailored PDF resume per job.

Two test users:
- **Test user A (US)** (Linux, this machine): US robotics/ML roles, Simplify GitHub lists + LinkedIn.
- **Test user B (Norway)** (macOS, business-school student, novice): LinkedIn (Norway), FINN.no, BI student portal.

## 0. Hard rules for the builder
- Work ONLY in `~/repos/JobApplication`. `~/career/**` is the old live system: READ-ONLY, copy logic from it, never edit, never stop its cron/server/Mongo.
- Never `git push`. Never create the GitHub repo. Never send emails. Never log into LinkedIn or any site.
- No sudo. Install tools to `~/.local` (pip --user, static binaries) only.
- Network: real HTTP only in `tests/live/` (opt-in, `pytest -m live`) and smoke runs; ≥2 s between requests to one host; identify with a normal browser UA; respect robots.txt rules noted below.
- No personal data in git: no real names/emails/phones/resumes. Test profiles live in `~/.jobapp-test/<name>/` (outside the repo).
- Each phase = branch `feat/<name>` off `main`, merged into `main` with `--no-ff` only when `pytest` (offline) passes and the phase's acceptance checks pass.
- Append progress to `docs/PROGRESS.md` (phase, what was done, test results, open issues). Write `PHASE <n>: DONE` as the last line of a finished phase.
- Hard blocker (needs a decision/credentials) → write `PHASE <n>: BLOCKED — <reason>` in PROGRESS.md, run `~/.synaps-cli/tools/bin/discord-notify --alert "JobApplication: <reason>"`, and stop.

## 1. Stack
- Python ≥3.10, package `jobapp`, `pyproject.toml`, installed with `uv` (`uv sync`; fallback `pip install -e .`).
- CLI: `typer` + `rich`. Config: YAML + `pydantic` v2 models. DB: `sqlite3` (stdlib), WAL mode.
- Web: FastAPI + uvicorn, one-page HTML dashboard (port from `~/career/jobdesk/server.py`), bound to 127.0.0.1.
- HTTP: `httpx` + `selectolax`/`beautifulsoup4`. MCP: official `mcp` Python SDK (FastMCP).
- LaTeX engine abstraction: `tectonic` if present, else `latexmk`/`pdflatex`. `doctor` reports which.
- Secrets: `keyring` (macOS Keychain), fallback `.env` in the profile dir.

## 2. Profile = everything personal (never in git)
`JOBAPP_HOME` env var, default `~/JobApplication-data/`. Contents:
```
config.yaml          # sources, filters, resume, schedule, connectors
resume/resume.tex    # user's resume with SKILLS markers
resume/keywords.yaml # keyword bank (what they can claim) + aliases
jobs.db              # SQLite
output/              # built PDFs: <First>_<Last>_<Company>_<Role>.pdf
logs/
```
`jobapp init` creates it from `examples/profile/` (fake person "Alex Example").

## 3. config.yaml (validated by pydantic; `jobapp config validate` prints friendly errors with "did you mean")
```yaml
profile:
  name: Alex Example
  locale: en            # en | no  (affects default keywords/date parsing)
sources:
  simplify:   {enabled: false, lists: [summer_internships, new_grad, offseason]}
  linkedin:   {enabled: true, searches: [{keywords: "business analyst", location: "Oslo, Norway"}], max_pages: 3}
  finn:       {enabled: false, searches: [{q: "analytiker", location: "Oslo"}]}
  bi_portal:  {enabled: false}   # login-gated, see §5.4
filters:
  title_include: [analyst, consultant]     # any-of, case-insensitive, word-boundary
  title_exclude: [senior, lead, principal]
  locations: [Oslo, Remote]                # any-of substring; empty = all
  job_types: [fulltime, internship, parttime]
  max_age_days: 21
  companies_include: []                    # empty = all
  companies_exclude: []
  languages: []                            # optional: [en, no] — detect JD language
resume:
  tex: resume/resume.tex
  keywords: resume/keywords.yaml
  output_name: "{first}_{last}_{company}_{role}"
schedule: {times: ["09:00", "18:00"]}
connectors:
  obsidian: {enabled: false}               # interface only in v0.1 (see §8)
```

## 4. Database (SQLite, `PRAGMA user_version` migrations in `jobapp/db/migrations/NNN_*.sql`)
- `jobs(id TEXT PK, source, source_id, url, apply_url, company, title, location, job_type, posted_at, first_seen_at, last_seen_at, description, jd_saved_at, language, raw JSON, match_pct REAL, matched JSON, missing JSON, status TEXT DEFAULT 'new', done INTEGER DEFAULT 0, done_at, notes)`
  `status ∈ new|interested|applied|interview|rejected|offer|ignored`. Unique (source, source_id).
- `runs(id, started_at, finished_at, source, fetched, new, errors)`; `builds(id, job_id, pdf_path, created_at, keywords JSON)`.
- FTS5 virtual table on company/title/description.
- Re-polling never overwrites `status`, `done`, `notes`, or a hand-saved description (`jd_saved_at`).

## 5. Sources (plugin interface)
```python
class Source(Protocol):
    name: str
    def fetch(self, cfg, http) -> Iterable[JobPosting]: ...      # listings
    def fetch_description(self, job, http) -> str | None: ...    # optional JD body
```
Registered via entry in `jobapp/sources/__init__.py`. Each source has offline tests using saved HTML/JSON fixtures in `tests/fixtures/<source>/`.

### 5.1 simplify — port `~/career/industry/watch_jobs.py` (README markdown tables of SimplifyJobs repos). Lists configurable by name → URL map.
### 5.2 linkedin — public guest endpoint, NO login:
`https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords=<kw>&location=<loc>&start=<n>` (25/page), JD via `https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/<id>`. Port parsing from `~/career/fulltime/poll_jobs.py`. Backoff on 429; max_pages cap; ≥2 s spacing. If JD fetch fails, keep the job, mark `description=None` ("manual JD").
### 5.3 finn — `https://www.finn.no/job/search?q=<q>&location=...` listing; ads at `/job/ad/<id>`. robots.txt: do NOT combine `industry=` and `occupation=` params; never send `abTestKey`. Norwegian text: parse "Søknadsfrist", "Stillingstittel", "Arbeidsgiver", "Sted", dates like "15. oktober 2026".
### 5.4 bi_portal — `https://portal.bi.no/en/services/vacant-positions/` redirects to Azure B2C student login. v0.1: stub that raises `NeedsLogin` with a friendly message; `doctor` shows "BI portal: needs login (planned)". Design note only for later: Playwright persistent browser profile, user logs in once.

### Filters — pure function `apply_filters(job, cfg.filters) -> (keep: bool, reason: str)`; reasons stored for the dashboard's "why hidden" view. Unit-tested heavily (edge cases: Norwegian chars æøå, "Sr." vs "senior", empty lists).

## 6. Matching + resume build — port from `~/career/resume/keywords/{swap.py,apply.py}`
- `keywords.yaml`: `core_competencies: {group: [..]}`, `technical_skills: {group: [..]}`, `aliases: {jd_term: canonical}`.
- match: normalised, alias-aware, word-boundary; `match_pct`, `matched`, `missing`.
- build: copy resume.tex → temp, rewrite ONLY between `% <<SKILLS-CORE>>…% <<SKILLS-CORE-END>>` and `% <<SKILLS-TECH>>…% <<SKILLS-TECH-END>>` (JD-matched keywords first, then fill from the bank to the original line length budget), compile, write PDF to `output/`. Every other byte of the .tex must be identical (test this).
- `examples/profile/resume/resume.tex`: generic one-column template (same macros as `~/career/resume/variants/perception/perception.tex`: \expentry \projentry \projnolink \eduentry) filled with fake "Alex Example" business-student content. `examples/profile/resume/keywords.yaml`: business/finance bank.

## 7. Word import (`jobapp resume import <file.docx>`)
- Extract: `pandoc -t markdown --wrap=none` (fallback: `python-docx` → markdown-ish text); layout facts via python-docx; page count from `docProps/app.xml` `<Pages>`.
- Prompt: `prompts/docx_to_latex.md` rendered with the template + extracted content.
- Two modes, no API key needed in the default:
  - **agent mode (default)**: `jobapp resume import x.docx --prepare` writes `import/prompt.md`; the Claude agent (Code or Desktop) writes `import/resume.tex`; `jobapp resume import --verify` runs the gates and on failure writes `import/fix_report.md` for the agent to retry (max 3).
  - **api mode**: if `ANTHROPIC_API_KEY` or `GEMINI_API_KEY` in keyring/env, do the loop automatically.
- Verification gates (code): compiles; page count <= source (fewer is fine); token-multiset diff of `pdftotext` (or `pypdf`) vs docx text is empty modulo allowlist; URL set equal; marker pairs present and build dry-run OK.
- Test: generate a fake .docx with python-docx in tests; run agent-mode verify against a hand-written correct .tex fixture (pass) and a reworded one (fail with the reworded tokens listed).

## 8. Connectors (interface only in v0.1)
```python
class Connector(Protocol):
    def on_job_added(self, job): ...
    def on_job_updated(self, job, changes: dict): ...
    def pull(self) -> list[dict]: ...
```
Called after DB writes; exceptions are caught, logged, shown in `doctor`, never fail a poll. Ship a `NullConnector` and a `jsonl` connector (appends events to `output/events.jsonl`) as the reference. Obsidian connector is NOT built in v0.1.

## 9. CLI
`jobapp init | config validate | config show | poll [--source X] [--dry-run] | list [--status new --min-match 40] | show <id> | mark <id> <status> | build <id> | serve | resume import ... | schedule install|remove|status | doctor | report-bug | version`
- `schedule install`: macOS → write `~/Library/LaunchAgents/com.jobapplication.poll.plist` (StartCalendarInterval per time) + `launchctl load`; Linux → print the crontab line (don't edit crontab). Unit-test plist generation.
- `doctor`: python, deps, tex engine, pandoc, config valid, DB version, each source reachable (HEAD, 1 req), last run errors, connectors. Plain-English output with a fix hint per failure.
- `report-bug`: zip of logs + `doctor` + config with secrets/name/email/phone redacted → `output/bug-report-<date>.zip`.
- Dashboard: table (company, title, location, source, posted, match%, status), filters, sort presets, "Build resume" → downloads `<name>.pdf` + "Show in Finder/Folder" button, status dropdown, "why hidden" toggle for filtered-out jobs, "Refresh" button runs poll.

## 10. Agent layer
- `CLAUDE.md`: what the tool is, the user is non-technical → explain in plain English, never show stack traces raw; allowed to edit only `$JOBAPP_HOME/**`; command cheat-sheet; how to handle each `doctor` failure; how to do the Word import (agent mode loop).
- `.claude/commands/`: `setup.md` (install brew/uv/tectonic/pandoc on macOS step by step, `jobapp init`, ask the user their target roles/locations and write config, `doctor`), `find-jobs.md`, `tailor.md`, `import-resume.md`, `applied.md`, `update.md` (git pull on `stable` + `jobapp migrate`), `report-bug.md`.
- `.claude/settings.json`: permissions deny `Edit/Write` on `src/**`/`jobapp/**`, deny `git push`, deny `rm -rf`.
- MCP server `jobapp mcp` (stdio) for Claude Desktop with tools: `find_jobs`, `list_jobs`, `job_details`, `build_resume`, `mark_job`, `import_resume_prepare`, `import_resume_submit_tex`, `doctor`, `update_config_filters`. README snippet for `claude_desktop_config.json`.

## 11. Docs
- `README.md`: for a novice, Mac-first; "Install with Claude" (paste one sentence into Claude Code) and manual install; screenshots placeholder.
- `docs/ARCHITECTURE.md`, `docs/ADDING_A_SOURCE.md`, `CHANGELOG.md`, `LICENSE` (MIT), `.gitignore`.
- Privacy check script `scripts/privacy_scan.sh`: fails if repo contains the owner's or test users' names/handles (listed, split, in the script), phone patterns, GitHub tokens or home-directory paths. Run in tests.

## 12. Phases (branch → acceptance)
1. `feat/core` — package, CLI skeleton, config models+validate, DB+migrations, `init`, `doctor` (partial), privacy scan, CI-able `pytest`. ✔ `jobapp init && jobapp config validate && pytest`.
2. `feat/sources` — Source interface, filters, simplify, linkedin, finn, bi_portal stub, `poll`, `list`. ✔ offline tests; live smoke: test user A (US) profile (simplify+linkedin US robotics) and test user B (Norway) profile (linkedin "Oslo" + finn) each insert ≥10 jobs; record counts in PROGRESS.md.
3. `feat/resume` — keywords, matching, enrich step in poll, build with marker rewrite, tex engine abstraction, example resume. ✔ build a PDF for 3 real jobs per test profile; byte-identity test outside markers.
4. `feat/dashboard` — FastAPI dashboard. ✔ `jobapp serve` up, curl endpoints, build via HTTP returns a PDF.
5. `feat/docx-import` — §7. ✔ tests pass; manual run on generated docx in agent mode (the builder acts as the agent).
6. `feat/agent` — CLAUDE.md, commands, settings, MCP server. ✔ MCP server lists tools via an `mcp` client test; `report-bug` redaction test.
7. `feat/macos` — schedule (launchd plist + linux crontab print), keyring, Finder reveal (`open -R` on mac, `xdg-open` dir on linux). ✔ unit tests.
8. `release` — README, docs, CHANGELOG, privacy scan clean, create branch `stable` at main, tag `v0.1.0` (local only). Final `discord-notify --done`.

Test profiles to create before phase 2 (outside repo):
- `~/.jobapp-test/userA/` — simplify on (internships+new grad), linkedin `{keywords: "robotics perception engineer", location: "United States"}`; filters from `~/career/fulltime/poll_jobs.py` TITLE_KWS/BLOCK_KWS and `~/career/industry/watch_jobs.py` KEYWORDS; resume = copy of `~/career/resume/variants/perception/perception.tex`, keywords = copy of `~/career/resume/keywords/master_keywords.yaml`.
- `~/.jobapp-test/userB/` — linkedin `{keywords: "analyst", location: "Oslo, Norway"}` + `{keywords: "graduate", location: "Norway"}`, finn `{q: "analyst"}` `{q: "trainee"}`; filters title_include [analyst, analytiker, consultant, konsulent, trainee, graduate, associate, finance, økonomi], exclude [senior, lead, manager, leder]; example resume (their real one not available yet).
