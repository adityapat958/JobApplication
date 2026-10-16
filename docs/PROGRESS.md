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

## Phase 2 — feat/sources
- `http.py`: polite client (browser UA, ≥2 s per host, retry/backoff on 429/5xx honoring Retry-After, URL guards).
- `filters.py`: pure `apply_filters(job, filters) -> (keep, reason)`. Whole-word matching, abbreviation expansion
  (Sr./Sr→senior, Jr→junior, Mgr→manager…), `word*` prefix and `*word` suffix wildcards (needed for Norwegian
  compounds like "Finansanalytiker"), æøå-safe, soft hyphens removed, unknown values kept. Reasons stored in
  `jobs.hidden_reason` (→ `jobapp list --hidden`). Jobs with a non-`new` status are never hidden.
- Sources (registry in `sources/__init__.py`): simplify (HTML tables, ↳ rows, 🔒 closed rows skipped, multi-location
  `<details>`, emoji badges stripped, age→posted_at, JD via JSON-LD/main text of ATS page), linkedin (guest
  endpoints; pages actually return 10 cards, so paging advances by cards returned; `f_TPR` from max_age_days;
  JD + employment type from jobPosting; failed JD → job kept with description NULL), finn (search cards, ad
  JSON-LD + Norwegian label fallback: Stillingstittel/Arbeidsgiver/Sted/Søknadsfrist, "15. oktober 2026";
  robots guard forbids industry+occupation and abTestKey; only the verified Oslo location code is sent, other
  locations are matched locally), bi_portal stub raising `NeedsLogin` (doctor: "needs login (planned)").
- `poll.py`: fetch → filter → upsert → JD only for kept jobs (budget 200/source) → re-filter → score hook →
  connectors; per-source errors captured in `runs.errors`; re-filter of all jobs after full polls.
- CLI `poll [--source] [--dry-run] [--no-jd]`, `list [--status --min-match --hidden --search --sort --json]`,
  `show`, `mark`. Doctor shows per-source reachability and last-run results.
- Tests: 113 offline passed; `pytest -m live` 3 passed.
- Live smoke (test profiles in ~/.jobapp-test, outside repo):
  - userA (simplify summer_internships+new_grad, linkedin "robotics perception engineer"/United States):
    simplify 2451 fetched / 190 kept (92 with JD), linkedin 30 fetched / 29 kept (29 with JD). ✔ ≥10
  - userB (linkedin analyst/Oslo + graduate/Norway, finn analyst + trainee):
    linkedin 59 fetched / 31 kept (30 with JD), finn 108 fetched / 56 kept (56 with JD). ✔ ≥10
- Note: FINN robots.txt also lists `Disallow: /job/` for AI *training* crawlers (GPTBot, ClaudeBot, CCBot…);
  user-directed agents (ChatGPT-User) are only restricted from /job/salary/. JobApplication is a user-run
  personal tool with low request volume and never touches /job/salary/ — documented in the README.
PHASE 2: DONE

## Phase 3 — feat/resume
- `resume/keywords.py`: bank loader (all groups, any names), alias targets validated, friendly errors.
- `resume/matching.py` (port of swap.py): accent/hyphen-normalised, word-boundary, plural-tolerant, case-sensitive
  for ≤2-char/short acronyms (R, C, SQL…), "(VLMs)" parentheticals match either form, aliases → canonical.
  `missing` = Title-Case/ACRONYM/CamelCase runs not in the bank, minus company/location/geo/stopwords.
  `match_pct = matched / max(matched + missing, 6)` (floor stops 2-keyword JDs scoring 100%); no JD → pct NULL,
  title-only matches kept. Poll scores new/JD-updated jobs; `jobapp rescore` re-scores everything.
- `resume/build.py`: rewrites ONLY the first `\item` between `% <<SKILLS-CORE>>…-END>>` / `% <<SKILLS-TECH>>…-END>>`
  (extra `\item`s in the TECH block untouched; CORE-only resumes supported). Order: JD-matched → user's original
  picks → rest of bank, capped at the original line's character budget (+5%). LaTeX escaping of & % $ # _.
  Byte-identity outside markers is tested on the example resume and a comment-heavy resume.
- `resume/tex.py`: tectonic → latexmk → pdflatex; first-error extraction; page count via pypdf.
- `resume/service.py`: builds in a temp dir (copies .cls/.sty/images), writes
  `output/<First>_<Last>_<Company>_<Role>.pdf` (æøå transliterated), warns if page count differs from the
  untouched resume (cached), records `builds`, notifies connectors. `jobapp build <id>`.
- Acceptance: 3 real PDFs per profile built from live jobs —
  userA: Intelletec / Skydio / Evolution USA (perception.tex, 2 pages each = original);
  userB: DNV / Fremtind / DNV (example resume, 1 page). Byte-identity verified on perception.tex too.
- Tests: 147 offline passed.
PHASE 3: DONE

## Phase 4 — feat/dashboard
- `web/server.py` (FastAPI, 127.0.0.1 only; ported from the old jobdesk server): `/` dashboard, `/job/<id>` JD+notes
  page, `/api/jobs`, `/api/jobs/<id>`, `…/status`, `…/notes`, `…/description` (hand-saved JD → never overwritten,
  rescored), `/api/build/<id>`, `/api/pdf/<id>` (attachment download), `/api/reveal/<id>` (Finder/folder),
  `/api/refresh` (background poll + status), `/api/stats`, `/api/health`.
- Safety: POSTs need `X-JobApp: 1` header; Host must be localhost (blocks cross-site requests / DNS rebinding);
  PDFs only served from `output/`.
- `web/index.html`: table (company, title, location, site, posted, match bar, status dropdown), filters (search,
  to-do/tracking/all/hidden-by-filters with reason, site, type, age, min match), sort presets + header sort,
  "Build resume" → downloads `<name>.pdf` + "Show in Finder/folder" button, "Find new jobs" button.
- `platform.py`: reveal (`open -R` on mac, `xdg-open <dir>` on linux).
- Acceptance: `jobapp serve --port 8799` on the userB profile; curl /api/health, /api/stats, / ;
  POST /api/build/<id> → `UserB_Tester_Borregaard_Data-Analyst.pdf`, GET /api/pdf/<id> → application/pdf
  attachment (valid PDF); POST without header → 403. Headless-Chrome screenshot checked.
- Tests: 154 offline passed (TestClient incl. build→PDF download).
PHASE 4: DONE

## Phase 5 — feat/docx-import
- `resume/docx_import.py`: extract (pandoc markdown + plain, fallback python-docx → markdown-ish with bold/italic/
  links/bullets/tables), layout facts (page size, margins, base font, section order, tables, images), page count
  from `docProps/app.xml <Pages>`, hyperlink URLs from the .rels.
- Prompt: `prompts/docx_to_latex.md` SYSTEM+USER sections rendered with the example template, markdown, layout,
  target pages, fix report; agent-mode footer says where to write `import/resume.tex` and how to verify.
- Gates (code): compiles (+ Overfull hbox > 5pt warning), page count == target, token-multiset diff of
  pdftotext/pypdf vs the docx text (NFKC, casefold, punctuation-insensitive, de-hyphenated; allowlist
  github/link/linkedin), URL set equality (\href, \url, \projentry 2nd arg; macro params ignored),
  marker pairs + tailoring dry-run with the user's bank. Failure → `import/fix_report.md`; rounds counted (max 3).
  Fenced ```latex answers are unwrapped automatically.
- CLI: `jobapp resume import <docx> --prepare | --verify | --accept | --api`. `--accept` backs up the old resume.
- API mode: ANTHROPIC_API_KEY / GEMINI_API_KEY from env → keychain → profile .env (`secrets.py`); loop up to 3
  rounds feeding the fix report + previous output. Tested with a fake caller (no real API call made).
- Tests: python-docx-generated resume; hand-written correct .tex passes; reworded .tex fails listing exactly
  missing ["12","built"] / extra ["developed","twelve"]; link/page/marker/compile failures; fallback without pandoc.
- Manual agent-mode run (builder as agent): generated "Ingrid Eksempel" .docx (Norwegian chars, smart quote,
  3 skills lines, a table, 3 links) → `--prepare` → wrote resume.tex from prompt.md → `--verify` all 5 gates
  passed on round 1 → `--accept` → tailored build OK (1 page).
- Tests: 169 offline passed.
PHASE 5: DONE

## Phase 6 — feat/agent
- `CLAUDE.md`: audience (non-technical), tone rules (no raw tracebacks), edit scope (`$JOBAPP_HOME/**` only),
  command cheat-sheet, config primer, keyword honesty rule, per-`doctor`-check fix table, Word import agent loop.
- `.claude/commands/`: setup, find-jobs, tailor, import-resume, applied, update (stable + `uv sync` + migrate),
  report-bug. `.claude/settings.json`: deny Edit/Write on src/**, jobapp/** (+ tests/**, scripts/**), deny
  `git push`, `rm -rf`; allow `uv run jobapp:*`.
- MCP server `jobapp mcp` (stdio): find_jobs (background poll, waits ≤45 s, call again to collect), list_jobs,
  job_details, build_resume, mark_job, import_resume_prepare, import_resume_submit_tex, doctor,
  update_config_filters (validated, backup `config.yaml.bak`, re-filters saved jobs). Errors returned as plain
  `{ok:false, error, hint}`. Works with mcp 2.x (`MCPServer`) and 1.x (`FastMCP`) — installed SDK is mcp 2.3.0,
  where FastMCP was renamed.
- `jobapp mcp-config` prints the exact claude_desktop_config.json snippet with the user's real paths.
- `jobapp report-bug` (`bugreport.py`): zip with system info, doctor, redacted config, redacted logs, DB stats;
  redacts profile name parts, emails, phones (keeps dates/versions), API keys/tokens/passwords, home path;
  never includes `.env`.
- Tests: MCP stdio client lists all 9 tools + calls list_jobs; tool functions; report-bug redaction + zip contents.
  177 offline passed.
PHASE 6: DONE

## Phase 7 — feat/macos
- `schedule.py`: macOS → writes `~/Library/LaunchAgents/com.jobapplication.poll.plist` (StartCalendarInterval per
  time, sorted/deduped; ProgramArguments = venv python `-m jobapp.cli_entry poll`; JOBAPP_HOME + PATH incl.
  /opt/homebrew/bin and /Library/TeX/texbin; log to logs/schedule.log) and `launchctl load -w` (unload first on
  reinstall); `remove`, `status` (launchctl list). Linux → prints crontab lines tagged `# jobapplication-poll`,
  never edits the crontab.
- `secrets.py`: env → keyring (macOS Keychain) → `$JOBAPP_HOME/.env` (chmod 600). CLI `jobapp key set|status`.
- `platform.py`: reveal = `open -R` (mac) / `xdg-open <dir>` (linux) / explorer (windows); dashboard + `build --reveal`.
- CLI output no longer hard-wraps (paths and crontab lines stay copy-pastable).
- Tests: plist generation (plistlib round-trip), crontab lines, mac install/reinstall/status/remove with mocked
  launchctl, linux install never calls subprocess, reveal commands, keyring + .env fallback. 187 offline passed.
PHASE 7: DONE
