# Changelog

## Unreleased
- Resume import now accepts a **PDF** as well as a Word file (`jobapp resume import resume.pdf --prepare`):
  text via `pdftotext -layout` (fallback pypdf) turned into headings/bullets, links from the PDF's link
  annotations, page count from the PDF. Scanned (image-only) PDFs are refused with a plain-English message.
- Word-check now handles ligatures (ﬁ ﬂ ﬀ), bullet glyphs and words hyphenated at a line end (only that
  exact split is forgiven, so rewording is still caught).
- Prompt template, CLI help, CLAUDE.md, `/import-resume`, README and MCP tool descriptions say "Word or PDF".
- Word-check reads PDFs with `pdftotext -raw`: the default mode silently glued compounds broken at a line
  end ("fail-" / "closed" → "failclosed") and failed correct imports.
- Prompt: keep the source order of all Skills lines (CORE = first domain line, TECH = broadest tools line,
  other lines unmarked); match the source's paper size (letter/A4).
- Tailoring with several Skills lines: no repeats of keywords already on another Skills line or inside the
  user's own "AWS (ECS, IAM)"-style item; commas inside brackets no longer split an item.

## v0.1.0 — first release
- Job sources: LinkedIn (public guest pages), FINN.no, Simplify GitHub lists; BI portal placeholder (needs login, planned).
- Filters with reasons ("why hidden"), whole-word matching, `*` wildcards for Norwegian compound words, Sr./Jr. abbreviations.
- Keyword matching against your own keyword list (aliases, plurals, hyphens, accents) with match % and missing skills.
- Tailored PDF resume per job: only the Skills lines change; page-count check; `First_Last_Company_Role.pdf`.
- Dashboard (`jobapp serve`): filter, sort, status, paste job descriptions, build + download, show in Finder.
- Word resume import with automatic checks (agent mode via Claude, or API mode with your key).
- Claude integration: CLAUDE.md, slash commands, MCP server for Claude Desktop (`jobapp mcp`, `jobapp mcp-config`).
- Automatic searches (launchd on macOS, crontab line on Linux), keychain storage for API keys.
- `jobapp doctor` with fix hints; `jobapp report-bug` with personal details removed.
