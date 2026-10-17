# JobApplication

**Find jobs on the sites you choose, hide the ones you don't want, see how well each one matches your
skills, and get a tailored PDF resume for each job — in one click.**

Made for people who don't code. You use it by talking to **Claude** (Claude Code or Claude Desktop);
Claude runs the tool, explains things in plain English, and fixes settings for you.

> 📸 *Screenshot of the dashboard goes here* (`docs/screenshots/dashboard.png`)

## What it does
- **Searches** LinkedIn (public job pages, no login), FINN.no (Norway) and the Simplify GitHub lists (US students).
  The BI Norwegian Business School portal needs a login and is planned for a later version.
- **Filters** by job title words, words to avoid (e.g. "senior"), places, job type, age of the ad, companies
  and ad language. Hidden jobs are kept with the reason, so nothing disappears silently.
- **Scores** each job: which of *your* skills the ad mentions, and which skills in the ad you didn't list.
- **Builds a tailored resume**: only the two Skills lines change per job (the ad's matching keywords go first);
  every other letter of your resume stays exactly as you wrote it. The PDF is named
  `First_Last_Company_Role.pdf`.
- **Tracks** what you did: interested → applied → interview → offer.
- **Imports your Word or PDF resume** into the PDF template. Claude types it; the tool checks every word, link and
  the page count against your original file.
- Runs **on your computer only**. Your jobs, resume and settings stay in a private folder
  (`~/JobApplication-data`), never in this repository.

## Install with Claude (easiest)
1. Install [Claude Code](https://claude.com/claude-code) (or use Claude Desktop, see below).
2. Download this folder (green **Code** button → *Download ZIP*, then unzip it, or `git clone`).
3. Open Claude Code in that folder and paste this sentence:

   > **Set up JobApplication for me on this computer, step by step, and ask me what jobs I'm looking for.**

   (or type `/setup`). Claude installs what's needed, creates your private folder, asks about the jobs you want,
   and runs a first check.

Then just ask things like *"find new jobs"*, *"make a resume for the DNV one"*, *"I applied to it"*,
or use the shortcuts `/find-jobs`, `/tailor`, `/applied`, `/import-resume`, `/report-bug`, `/update`.

## Manual install (Mac)
```bash
# 1. tools (Homebrew from https://brew.sh first, if you don't have it)
brew install uv tectonic pandoc
# 2. the app (in this folder)
uv sync
# 3. your private folder with example settings and an example resume
uv run jobapp init
# 4. check everything
uv run jobapp doctor
```
Linux works the same (`curl -LsSf https://astral.sh/uv/install.sh | sh`; TeX Live or tectonic; pandoc).

## Everyday use
```bash
uv run jobapp poll                     # search the job sites now
uv run jobapp list --sort match        # best matches first
uv run jobapp show <id>                # one job in detail
uv run jobapp build <id> --reveal      # tailored PDF, shown in Finder
uv run jobapp mark <id> applied        # keep track
uv run jobapp serve                    # dashboard in your browser (http://127.0.0.1:8765)
uv run jobapp schedule install         # search automatically at the times in config.yaml
uv run jobapp connectors sync obsidian # optional: one note per job in Obsidian (see below)
uv run jobapp rescore                  # after editing keywords.yaml
```
Your settings are in `~/JobApplication-data/config.yaml`; after editing run `uv run jobapp config validate` —
it explains mistakes and suggests the right spelling. Filter words match whole words; add `*` for
word beginnings/endings (`robot*` → robotics, `*analytiker` → Finansanalytiker).

## Word or PDF resume import
```bash
uv run jobapp resume import ~/Desktop/resume.docx --prepare   # or resume.pdf; Claude follows import/prompt.md
uv run jobapp resume import --verify                          # checks words, links, pages, markers
uv run jobapp resume import --accept                          # use it (old resume is backed up)
```
With your own API key (`uv run jobapp key set ANTHROPIC_API_KEY`, stored in the Mac Keychain) the whole
loop runs automatically: `uv run jobapp resume import resume.docx --api` (or `resume.pdf`).
A Word file gives the best result (bold/italic are kept); a PDF works too as long as its text can be selected
(not a scan).

## Obsidian (optional)
If you keep notes in [Obsidian](https://obsidian.md), JobApplication can write one note per job into your
vault — same layout as a hand-made job note: details table, Apply link, a Status checklist and room for your
own notes. It is **off** until you switch it on in `config.yaml`:
```yaml
connectors:
  obsidian:
    enabled: true
    vault: ~/Documents/Obsidian Vault   # the folder you opened as a vault in Obsidian
    folder: Jobs                        # notes go in Jobs/Full-Time, Jobs/Internships, Jobs/Part-Time
```
Then `uv run jobapp connectors sync obsidian` writes notes for the jobs you already have (`--dry-run` shows
what it would do first). After that every search adds notes for new jobs and keeps `_Dashboard.md` and
`_New Today.md` up to date. Your own writing in a note is never changed — only the status, match and link
fields at the top and the "Applied" tick box. You can rename or move notes; they are found by `job_id`.
Extras: `two_way: true` lets you change a job's status in the note (or tick "Applied") and have it show up
here at the next search; `git_push: true` commits the Jobs folder (and pushes it) if your vault uses git;
`min_match: 40` only writes notes for good matches. The two generated notes can have other names
(`dashboard_file: "_JobApplication Dashboard.md"`, `new_today_file: ...`); an existing file at that name that
JobApplication didn't make is never overwritten (`doctor` says so; `connectors sync obsidian --adopt-dashboards`
replaces it on purpose).

## Several resumes (optional)
Have two versions of your resume (say one for robotics jobs and one for ML jobs)? List them in `config.yaml`:
```yaml
resume:
  variants:
    perception: {tex: resume/perception.tex, keywords: resume/keywords.yaml, prefer_if: [perception, vision, slam, "robot*"]}
    mle:        {tex: resume/mle.tex,        keywords: resume/keywords.yaml, prefer_if: [machine learning, ml, llm]}
  default_variant: perception
```
Each job uses the resume whose `prefer_if` words best fit its title (then its description), else the default.
Choose yourself with `uv run jobapp build <id> --variant mle` (remembered for that job; `--variant auto` goes
back to automatic) or the "Resume" drop-down on the dashboard. `list`/`show` show which one a job uses.

## Keyword match
`matched` = words from your `keywords.yaml` found in the ad. `missing` = skills from a built-in vocabulary
(`src/jobapp/resume/skills_vocab.yaml`: tech, business/analytics, Norwegian equivalents) that the ad mentions
and your list doesn't have — never names, slogans or "About us" text. Add your own terms to it in
`keywords.yaml`:
```yaml
extra_vocab:
  Foxglove: []
  Isaac ROS: [isaac-ros]
```
After editing keywords run `uv run jobapp rescore`.

## Moving from the older jobdesk tracker
`uv sync --extra mongo`, then `uv run jobapp migrate --from-mongo --dry-run` (and without `--dry-run`) copies the
jobs from its Mongo database (read-only; safe to run again). Status, applied date, saved job descriptions, the
resume variant, the date found and each job's existing Obsidian note are kept; the next search recognises the
same LinkedIn/Simplify jobs instead of adding copies. Contacts and messages stay in the old system.

## Claude Desktop
JobApplication includes an MCP server, so Claude Desktop can use it too. Print your personal config snippet:
```bash
uv run jobapp mcp-config
```
and paste it into `~/Library/Application Support/Claude/claude_desktop_config.json`
(Claude Desktop → Settings → Developer → Edit Config), then restart Claude Desktop. It looks like:
```json
{
  "mcpServers": {
    "jobapplication": {
      "command": "<HOME>/.local/bin/uv",
      "args": ["--directory", "<HOME>/JobApplication", "run", "jobapp", "mcp"],
      "env": { "JOBAPP_HOME": "<HOME>/JobApplication-data" }
    }
  }
}
```
Tools: `find_jobs`, `list_jobs`, `job_details`, `build_resume`, `mark_job`, `import_resume_prepare`,
`import_resume_submit_tex`, `doctor`, `update_config_filters`.

## Something wrong?
`uv run jobapp doctor` explains each problem with a fix. `uv run jobapp report-bug` makes a zip of logs and
diagnostics with your name, email, phone numbers and passwords removed — send that to the developer.
`uv run jobapp version` shows which version you have (mention it when you ask for help).

## Being a good citizen
JobApplication is a personal tool, not a crawler: it waits at least 2 seconds between requests to the same
site, slows down when a site asks it to (HTTP 429), uses only public pages, never logs in for you, and follows
the site rules we know about (e.g. FINN.no: no `abTestKey`, never `industry` + `occupation` together, nothing
under `/job/salary/`). Note that FINN.no's robots.txt asks AI *training crawlers* to stay away from `/job/`;
JobApplication doesn't train anything, but if you want to be extra careful, leave the FINN source switched off.
It never applies or sends emails for you.

## For developers
`docs/ARCHITECTURE.md`, `docs/ADDING_A_SOURCE.md`, `CHANGELOG.md`. Tests: `uv run pytest` (offline);
real network checks: `uv run pytest -m live`. `scripts/privacy_scan.sh` keeps personal data out of the repo.

MIT licensed.
