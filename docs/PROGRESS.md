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

## Phase 8 — release
- README (novice, Mac-first: "Install with Claude" one sentence + `/setup`, manual install, everyday commands,
  Word import, Claude Desktop snippet via `jobapp mcp-config`, troubleshooting, good-citizen/robots note,
  screenshot placeholder), docs/ARCHITECTURE.md, docs/ADDING_A_SOURCE.md, CHANGELOG.md, LICENSE (MIT),
  .gitignore (+ .claude/settings.local.json).
- Fresh clone → `uv sync` → `jobapp init` → `config validate` → pytest 187 passed. `uv build` wheel contains
  examples, prompt, dashboard HTML and migrations; wheel installed in a clean venv → `init` + `doctor` OK.
- Privacy scan clean. Branch `stable` created at main, tag `v0.1.0` (local only, nothing pushed).
- Open issues / next steps:
  - BI portal: Playwright persistent-profile login (design note in `sources/bi_portal.py`).
  - Obsidian connector (interface ready).
  - Simplify JDs: ~50% of ATS pages are JS-rendered (Workday etc.) → no JD; user can paste it in the dashboard.
  - LinkedIn guest search returns 10 cards per page (spec said 25); paging handles either.
  - FINN location codes: only Oslo verified; other places are filtered locally by text.
  - Not tested on a real Mac (launchd/Keychain/`open -R` are unit-tested with mocks).
PHASE 8: DONE

## Phase 8 (re-run) — feat/release
- Re-ran phase 8 on branch `feat/release` (the earlier pass used `release`). Every release item from §11 was
  already present: README, docs/ARCHITECTURE.md, docs/ADDING_A_SOURCE.md, CHANGELOG.md, MIT LICENSE, .gitignore.
- New `tests/test_release.py` (21 tests): release files present and non-empty; LICENSE is MIT and matches
  pyproject; version agrees across pyproject, `jobapp.__version__`, `jobapp version` and CHANGELOG; README
  covers the novice path (Install with Claude, manual install, /setup, Claude Desktop snippet, screenshot,
  report-bug); every top-level CLI command is documented (README or CLAUDE.md); relative doc links resolve;
  all 7 slash commands exist; .gitignore covers personal data; no .db/.env/.pdf/.docx/output/__pycache__ is
  tracked; package data that the wheel force-includes exists.
- Gap found and fixed: README did not mention `jobapp version` (added under "Something wrong?").
- Acceptance: fresh clone → `uv sync` → `jobapp init` → `config validate` → pytest 208 passed, 3 deselected (live).
  `uv build` wheel contains examples, prompt, dashboard HTML, migrations; wheel installed in a clean venv →
  `init`, `version` (0.1.0), `doctor` all OK. `scripts/privacy_scan.sh` clean.
- `stable` and local tag `v0.1.0` moved to the new main merge commit (neither had ever been pushed). Nothing pushed.
- Open issues unchanged (see the first phase 8 section): BI portal login, Obsidian connector, JS-rendered JDs,
  LinkedIn 10 jobs/page, FINN location codes beyond Oslo, no test on a real Mac.
PHASE 8: DONE

## feat/pdf-import — resume import from PDF
- `jobapp resume import file.pdf --prepare|--verify|--accept|--api` (new `resume/pdf_extract.py`): layout text
  via `pdftotext -layout` (fallback pypdf) → markdown-ish (`##` headings, `-` bullets with wrapped lines joined,
  wrapped Skills lines joined, `⇥` for wide gaps), links from /Link annotations with anchor text from
  `pdftotext -bbox` (→ `[text](url)`), page count via pypdf, layout facts with `source_format: pdf` and a
  "bold/italic not recoverable" note. Image-only (scanned) PDFs are refused in plain English.
- Gates for PDF sources: token multiset diff (NFKC → ligatures split; bullet glyphs incl. Wingdings `§`/`Ø`/`o`
  stripped only at line starts; `|`/`·` are punctuation), new `content_diff` forgives a line-end hyphen split
  only for that exact pair; URL set, page count, compile, markers unchanged. Gate name says "PDF"/"Word".
- Prompt template made generic (`{{SOURCE_KIND}}`, `{{SOURCE_MARKDOWN}}`, `{{SOURCE_LAYOUT}}`); all rules
  kept; added PDF notes (⇥, emphasis unknown, link exactly what the source links). CLI help, CLAUDE.md,
  `/import-resume`, `/setup`, README, MCP tool descriptions say "Word or PDF".
- Real-world test (one real 2-page LaTeX-made PDF resume, data kept in `~/.jobapp-test/`, not in the repo;
  1068 tokens, 9 links, 6 skills lines):
  - Run 1 (original prompt): passed on round 1 (all 5 gates).
  - Weaknesses found and fixed: (a) rule 4.4 ("other skills lines go inside the TECH block") conflicted with
    4.1 (keep order) when the domain line isn't first → rewritten; (b) no rule for paper size (template is A4,
    source Letter) → added; (c) re-import with the new rules failed round 1 on words: `pdftotext`'s default
    mode dehyphenates, gluing "fail-"+"closed" / "end-to-"+"end" at line ends — a false failure an agent can't
    fix by editing words → switched the gate to `pdftotext -raw`; round 2 passed with the unchanged .tex.
    (d) tailoring with 6 skills lines repeated keywords already on unmarked lines and split "AWS (ECS, IAM)"
    at inner commas → fixed in `build.choose`/`parse_items`.
  - Visual check (page 1 + 2 side by side): same structure, order and links; template look differs as expected.
  - Poll (simplify new_grad + 2 LinkedIn searches): 576 jobs, 20 kept by filters; tailored PDF built for the
    top match (47% match, 2 pages = original page count).
- Tests: 226 passed, 3 deselected (live). New: `tests/test_pdf_import.py` (16, fake PDF compiled from LaTeX:
  extract, links, pypdf fallback, scan/bad file, prompt, ligatures/bullets/separators, hyphenation, pass,
  reworded fail with tokens listed, page count, CLI, API mode, line-end hyphens in a built PDF) + 2 build tests.
- Open issues: two-column PDFs (layout text interleaves columns; diff still works, prompt markdown is harder
  to read); PDFs without a ToUnicode map extract garbage → word gate fails (message could say so);
  `stable`/`v0.1.0` untouched.

## fix/docx-real-world — real Word resume (resume-builder .docx)
- Real-world test #2 as the user's agent on a real 3-page Word resume made with an online resume builder
  (data only in `~/.jobapp-test/`, nothing in the repo): skills in a 1-cell table (4 lines), 4 spacer
  paragraphs, U+2011 hyphens, CO₂ subscript, a professional-summary section, custom heading styles,
  dates like "10/2026 - Present", no hyperlinks.
  - Round 1: ✘ words — 6 "missing" tokens were an invisible tracking code (`#XXX#<uuid>`, white text in a
    1pt-high paragraph) the builder appends. Not resume content; an agent can't fix it by editing the
    .tex → code bug. Fix: `strip_invisible()` removes `w:vanish` runs and white-on-white runs (white text
    with no dark run/paragraph/cell shading) from a temp copy before pandoc/python-docx; layout facts say
    `hidden_text_removed: N`. Re-prepare → same .tex passed all 5 gates on round 1.
  - Table, U+2011 (→ `-`), CO\textsubscript{2}, summary, spacers: all fine for the gates; the prompt had no
    explicit rule for them (an agent hits "Unicode character not set up" compile errors) → added rules.
  - `section_order` was empty (style `div_document_div_heading`) → any style containing "heading" counts.
  - Skills markers: rule 4.4 "first conceptual/domain line" made the agent put CORE on the "Domain:" line;
    tailoring then filled "Domain:" with generic competencies. Rule rewritten (CORE = first methods/
    competencies line; narrow lines like Domain/Languages are poor CORE/TECH). Markers moved, re-verified.
  - Page fit: content fits 2 pages even at 12pt; 3 pages reached via spacing knobs only. Prompt now asks
    for a few lines of slack on the last page.
- Build: keyword lines were hyphenated ("statis-"/"tics" = two words to an ATS). Tailored Skills items now
  start with `\language=255 ` (no patterns, local to the item group) → no hyphenation there; output stays
  parseable/idempotent.
- Poll (4 LinkedIn + 4 FINN searches, Norway data/optimization roles): linkedin 99 fetched / 46 kept,
  finn 229 / 18 kept (3 LinkedIn 429s, retried OK). Top 3 match 67% / 62% / 50%; tailored PDFs 3 pages
  each (= original), Skills lines correct.
- Tests: 230 passed, 3 deselected (live). New: fake resume-builder .docx (`builder_resume`: table skills,
  U+2011, CO₂, spacers, white-on-dark heading kept, vanish + white-on-white tracker dropped) — extraction
  with and without pandoc, no-op copy, full verify pass; build: no hyphenation in keyword lines.
- Open issues: same job on FINN and LinkedIn is listed twice (no cross-source dedup); one FINN ad parsed
  the title into the company field; "missing keywords" can include a contact person's name; match % depends
  on bank granularity (aliases onto one keyword count once) — a `match_only` keyword section would help;
  summary paragraphs keep the template's paragraph indent.

## fix/v0.1.1 — real-world fixes + release 0.1.1
1. Import page gate: passes when converted pages <= source pages (fails only when more; detail says
   "N page(s), source has M — K page(s) too many: tighten the spacing knobs"). Prompt rule 4.5 rewritten:
   page budget = at most the source count, start from the template's default spacing, never pad spacing to
   reach the source count, tighten marked knobs only if it would exceed. Tests: fewer-pages pass, more-pages
   fail + fix-report wording, prompt wording.
2. Cross-source dedupe: migration 002 adds `duplicate_of` (nullable FK, ON DELETE SET NULL) and `dedupe_key`.
   `db/dedupe.py` normalises company (fold/casefold, A/S, legal forms, Norge/Norway, Bank/Group, punctuation)
   and title (gender tags like (m/f/d)/(m/k), punctuation, whitespace); same key from different sources within
   45 days → one group. Primary = tracked by the user, else not filter-hidden, else has a description, else
   first seen; copies are kept (URL) but hidden from list/dashboard/MCP and shown as "also on: <source>"
   (list column, `show`, dashboard row + JD page, MCP `also_on`). Only `duplicate_of` is written; status/done/
   notes never touched; two tracked copies both stay visible. `migrate()` gained `_post_migrate` (Python data
   step in the migration's transaction) → existing DBs deduped once. On copies of the test DBs: user B
   (Norway) 5 and 13 FINN/LinkedIn copies linked (e.g. "DNB Bank ASA" ↔ "DNB", "NOBA BANK GROUP" ↔ "NOBA Bank
   Group"); user A (US) / user C 0. Duplicates are not sent to connectors as "added".
3. FINN: (a) card company only from `.text-caption` (a bare `<strong>` only outside the title link); ad page
   company = JSON-LD hiringOrganization.name, then "Arbeidsgiver"; any company equal to the title is rejected;
   the ad page's company now overrides the card's in poll. Anonymised fixtures `search_title_in_company.html`,
   `ad_title_as_company.html`. (b) `text.strip_contact` removes Kontaktperson/Kontakt/Contact/"Spørsmål om
   stillingen" blocks and phone/e-mail lines before keyword extraction; names found there are blanked
   everywhere in the ad. Re-score of a copy of the user B (Norway) real-data DB: 44 junk "missing" terms gone
   (contact names, recruiter titles, "Søknadsfrist …"). Fixture `ad_contact_section.html` (fake people).
4. Ranking: `filters.title_score` (best title_include hit: words + length/20; generic graduate/trainee/junior/
   intern* = 0.25; extra specific hits +10%). `list --sort match`, MCP `list_jobs`, dashboard (default sort is
   now "best match") order by match_pct → title_score → posted. `show` prints title_score. On the user B data a
   "Graduate 2027 - Subsea, Risers and Pipelines Engineer" (0.25) now ranks below "Data Scientist" (1.57) at 50%.
5. Privacy: docs use "test user A (US)" / "test user B (Norway)" / "test user C" (userA/userB/userC); no
   school-specific identification. `privacy_scan.sh` also fails on the test users' first/last names and handles
   (patterns split so the script doesn't match itself; BUILD_SPEC no longer allow-listed). History rewritten
   with `git filter-repo --replace-text` (+ `--mailmap`: commit author/committer/tagger → neutral
   "JobApplication Maintainer", repo-local git identity set to the same) — nothing had ever been pushed (no
   remote). `stable` and `v0.1.0` were carried to the rewritten release commit. `git log -p --all | grep -iE
   "<test-user names>"` → no output. Full-history scan: only fake e-mails (example.com/.no/.invalid), fake
   555 / +47 numbers in tests, no home paths or tokens.
- Tests: 269 passed, 3 deselected offline (+39: tests/test_dedupe.py 26, tests/test_ranking.py 5, FINN 3,
  contact 2, import 2, privacy 1); `pytest -m live` 3 passed. Version 0.1.1 (pyproject, `__version__`,
  CHANGELOG, uv.lock).
- Open issues: dedupe needs equal normalised names ("If Forsikring (If Skadeforsikring)" vs "If Insurance" stay
  separate); a same-site repost isn't merged; `list` default sort is still newest (`--sort match` opt-in).
PHASE fix/v0.1.1: DONE

## feat/obsidian — Obsidian connector + release 0.1.2
- `connectors/obsidian.py` (off by default; config `connectors.obsidian`: vault, folder, subfolders, only_visible,
  min_match, dashboard_note, two_way, git_push — extra=forbid, folder/subfolders must be relative, min_match 0–100;
  a missing vault is reported by `config validate`/`doctor` and as a connector error, never at config parse, so a
  poll still runs). Note = old exporter layout (frontmatter company…tags; Location/Source/Found table; Apply link;
  Status checklist; Notes; Why This Role) + `job_id`, `match`, `matched`, `missing`, `url`, `also_on`; no tier
  unless the job's raw data has one. File name `Company — Title.md` via the old `safe_name` (+ NFC, control chars),
  collision → ` (<6-char id>)`. Lookup: frontmatter `job_id` (folder indexed once per run; stale entry → rescan),
  else file name for notes without an id (adopted; a non-"new" status in such a note is taken over once by `sync`,
  never silently reset). Updates change only managed keys (semantic compare, so Obsidian's block-list/quoting
  style doesn't trigger rewrites; a user-edited date_applied is kept) and the Applied box; atomic temp+rename.
- Core hooks: `connectors.pull_all` at poll start (two-way connectors; note wins only if its mtime is newer than the
  new `jobs.status_updated_at` — migration 003 — else DB wins, note rewritten, conflict in
  `logs/connector_state.json`, shown by `doctor`); `connectors.after_poll` at poll end (refresh existing notes,
  create notes missed since the connector was switched on, dashboards, git). `db.mark` = set status + un-hide,
  now used by CLI/dashboard/MCP/pulls. `jobapp connectors sync obsidian [--dry-run]`. Connector instances cached
  per config object (one vault index per poll).
- Dashboard notes: `_Dashboard.md` (counts by status, top 20 by match with [[links]]) and `_New Today.md`, with a
  "generated — edits are overwritten" header; date-only stamps so same-day reruns write nothing.
- git_push: `git add -A -- <folder>`, commit "jobs: update YYYY-MM-DD" only with staged changes (other staged/
  unstaged files untouched), push only with a remote (and only if ahead); no prompts (GIT_TERMINAL_PROMPT=0).
- Real-data check (copies only; real vault untouched — verified no file newer than the run): copy of the real
  Jobs folder (≈4 000 old notes) + copy of the test user A (US) profile: dry-run = real run = 120 created,
  99 updated (old notes adopted by file name), 2 dashboards; 2nd run 0 changes (~1 s). All 99 adopted notes
  differ from the originals only by the appended `job_id/match/matched/missing/url/also_on` lines. New notes vs
  the closest old notes: same layout; differences = no `tier` (field, tag, table row), new fields, Source is the
  source label ("LinkedIn", "Simplify lists (GitHub)" instead of "SimplifyJobs"/"simplify_github"), generic
  "Why This Role" placeholder, footer "Auto-generated by JobApplication". Test user B (Norway) copy, empty git
  vault, two_way + git_push: 58 notes (æ/ø/å in names and text fine), commit made, 2nd run nothing to commit;
  ticking "Applied" in a note → pull set the job to applied, note got date_applied, second commit.
- Tests: 303 passed, 3 deselected offline (+34 in tests/test_obsidian.py: golden note, tier, folders, idempotent
  sync + dry-run, CLI sync, update keeps user text/unknown keys/order, renamed+moved note, adoption + status
  take-over, collisions + unsafe chars (/ : æøå emoji, NFD), quoting, hidden/duplicate/min_match, two-way pull
  (status, box tick/untick), conflict (pull and mark), poll-start pull, catch-up since enable, git with/without
  remote + failing push isolated, not a repo, disabled = zero writes, unwritable vault doesn't fail the poll,
  missing vault, no .obsidian warning, config errors); `pytest -m live` 3 passed; privacy scan clean.
- Open issues: `missing` keywords still include ad boilerplate and, for some LinkedIn ads, contact names (matching,
  not the connector — they now also land in notes); a note title is cut at 60 characters like the old exporter;
  notes are never moved when a job's type changes; notes for deleted DB jobs are left alone.
PHASE feat/obsidian: DONE
