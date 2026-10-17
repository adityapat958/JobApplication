---
description: Write a tailored cover letter for one job (you write, the app checks every fact)
---
Job id (and optional language `en` / `no`): $ARGUMENTS. If empty, ask which job — show
`uv run jobapp list --sort match --limit 10`.

1. `uv run jobapp letter <id> --prepare` (add `--language no` for Norwegian). If it says the cover letter
   settings are missing, run `uv run jobapp coverletter init` first and tell the user in one line.
2. Read the prompt file it prints and follow it exactly. You are a **transcriber of facts**: only things the
   resume says, mapped to what the ad asks for. No invented numbers, employers, tools or company facts.
3. Write ONLY the letter body (plain paragraphs, no "Dear …", no sign-off) to the `body.md` path in the prompt.
4. `uv run jobapp letter <id> --verify`. If something fails, read `fix_report.md` next to it, fix ONLY those
   problems (remove or rephrase anything flagged as "not found" — never swap in another made-up fact) and
   verify again. **Maximum 3 rounds**; then stop and tell the user in plain words what the checks found.
5. When everything passes: `uv run jobapp letter <id> --accept`. Tell the user where the PDF is and that the
   `.txt` next to it is for pasting into application forms. Ask them to read it once before sending.
