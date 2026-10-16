# Changelog

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
