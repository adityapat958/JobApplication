---
description: Update JobApplication to the latest stable version
---
1. Tell the user you'll update the app; their jobs, settings and resume are in their profile folder and are not touched.
2. `git status --porcelain` — if there are local changes to the code, stop and ask (don't discard them).
3. `git fetch origin && git checkout stable && git pull --ff-only origin stable`
4. `uv sync`
5. `uv run jobapp migrate`
6. `uv run jobapp doctor` and summarise. If the CHANGELOG.md has a new section, summarise what changed in 2–3 bullets.
