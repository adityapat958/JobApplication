---
description: Record that the user applied (or another status change) for a job
---
Arguments: `$ARGUMENTS` = `<id> [status]` (status defaults to `applied`; others: interested, interview,
rejected, offer, ignored, new).

1. If no id, show `uv run jobapp list --sort newest --limit 10` and ask which one.
2. `uv run jobapp mark <id> <status>`
3. Confirm in one line. If they want, add a note in the dashboard (JD 📝 page → Notes).
4. Optionally show `uv run jobapp list --status applied` as their application tracker.
