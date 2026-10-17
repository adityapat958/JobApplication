-- Resume variant chosen by the user for a job (NULL = pick automatically from resume.variants.prefer_if).
ALTER TABLE jobs ADD COLUMN variant TEXT;
-- Jobs imported from an older tracker: its id, the note it already had, and a normalised apply URL so a
-- re-poll of the same listing finds the imported row instead of adding a copy.
ALTER TABLE jobs ADD COLUMN legacy_id TEXT;
ALTER TABLE jobs ADD COLUMN note_path TEXT;
ALTER TABLE jobs ADD COLUMN legacy_url_key TEXT;
CREATE UNIQUE INDEX jobs_legacy_id ON jobs(legacy_id) WHERE legacy_id IS NOT NULL;
CREATE INDEX jobs_legacy_url_key ON jobs(legacy_url_key) WHERE legacy_url_key IS NOT NULL;
