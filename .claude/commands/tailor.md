---
description: Build a tailored resume PDF for one job
---
Job id: $ARGUMENTS (if empty, ask which job — show `uv run jobapp list --sort match --limit 10`).

1. `uv run jobapp show <id>`. If there is no job description, ask the user to paste the ad text; save it in the
   dashboard (JD 📝) or tell them the match uses only the title.
2. `uv run jobapp build <id> --reveal`.
3. Tell them where the PDF is, which keywords were matched, and any warnings (e.g. page count changed).
4. Show "in the ad but not in your keywords". Ask which of those they honestly have; only for confirmed ones,
   add them to the right group in `resume/keywords.yaml`, then `uv run jobapp rescore` and build again.
5. Remind them to open the PDF and read it once before sending. Offer `/applied <id>` afterwards.
