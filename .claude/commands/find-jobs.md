---
description: Search the job sites and show the best new matches
---
1. Run `uv run jobapp poll` (it can take a few minutes; tell the user it's searching politely, a few seconds per page).
   If $ARGUMENTS names a site (linkedin, finn, simplify), add `--source <site>`.
2. Summarise per site in one line: found / matched filters / new. Explain any problem lines in plain English.
3. Run `uv run jobapp list --status new --sort match --limit 15 --json` and show a table:
   match %, company, title, place, id. Mention jobs that have no description ("manual JD").
4. If very few jobs survived, run `uv run jobapp list --hidden --limit 20 --json`, group the reasons, and suggest a
   filter change (ask before editing `config.yaml`).
5. Offer: "Want a tailored resume for any of these? Tell me the number." → `/tailor <id>`.
