---
description: Turn the user's Word resume into the PDF template (you type, the tool checks)
---
File: $ARGUMENTS (ask for the .docx path if empty; on a Mac they can drag the file into the chat).

1. `uv run jobapp resume import "<file>" --prepare`
2. Read `$JOBAPP_HOME/import/prompt.md` completely and follow it. You are a transcriber: copy every word
   exactly; never improve wording.
3. Write ONLY the LaTeX to `$JOBAPP_HOME/import/resume.tex`, and the mapping notes to `import/mapping_notes.yaml`.
4. `uv run jobapp resume import --verify`
   - Failed → read `import/fix_report.md`, fix only those items, verify again. Max 3 rounds, then stop and
     explain to the user; suggest `/report-bug`.
5. Passed → tell the user to look at `import/build/resume.pdf`. If they're happy:
   `uv run jobapp resume import --accept`.
6. Mention anything listed under `dropped` in the mapping notes (pictures, icons, columns).
7. Offer to review `resume/keywords.yaml` together so it matches their real skills.
