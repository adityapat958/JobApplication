# Adding a job source

1. **Save fixtures first.** Fetch one listing page and one job page by hand (respect the site's robots.txt, wait
   between requests) and store trimmed copies in `tests/fixtures/<source>/`. Remove recruiter names/phones —
   `scripts/privacy_scan.sh` fails on phone numbers.
2. **Write `src/jobapp/sources/<source>.py`:**
   ```python
   class MySource:
       name = "mysource"            # key under `sources:` in config.yaml
       label = "My Site"            # shown to the user
       probe_url = "https://…"      # one URL doctor can HEAD/GET

       def fetch(self, cfg, http):              # yield JobPosting for every listing
           for s in cfg.sources.mysource.searches:
               html = http.get_text(search_url(s.q))
               yield from parse_search(html)

       def fetch_details(self, job, http) -> dict:   # optional: description, job_type, …
           return parse_ad(http.get_text(job_url))

       def fetch_description(self, job, http):  # minimal version of the above
           return self.fetch_details(job, http).get("description")
   ```
   - Keep parsing in pure functions (`parse_search(html)`, `parse_ad(html)`) so they're testable offline.
   - `source_id` must be stable (the site's own id); the DB is unique on (source, source_id).
   - Use `http` (the polite client) for every request — never `httpx` directly. Add a guard to
     `http.guards` if the site's robots.txt forbids certain URL patterns (see `finn.robots_guard`).
   - Raise `HttpError`/`ValueError` with a plain-English message; `NeedsLogin` if a login is required.
   - Use helpers from `jobapp.text`: `clean`, `html_to_text`, `parse_date` (EN/NO), `parse_relative`,
     `guess_job_type`, `normalize_job_type`; `sources.generic.jsonld_jobposting` for JSON-LD pages.
3. **Config:** add a `MySourceCfg` model in `config.py` and a field on `SourcesCfg` (unknown keys are rejected,
   so this is required).
4. **Register** it in `REGISTRY` in `sources/__init__.py`.
5. **Tests:** offline parser tests from fixtures + a fetch test with `tests/helpers.mock_http`; one opt-in live
   test in `tests/live/` marked `@pytest.mark.live`.
6. Document it in README ("What it does") and CLAUDE.md (config primer).
