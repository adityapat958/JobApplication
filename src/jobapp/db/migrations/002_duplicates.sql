-- Cross-source duplicates: the same job seen on FINN and LinkedIn (etc.). The duplicate row is kept
-- (its URL is shown as "also on") but hidden from lists. dedupe_key = normalised company|title.
ALTER TABLE jobs ADD COLUMN duplicate_of TEXT REFERENCES jobs(id) ON DELETE SET NULL;
ALTER TABLE jobs ADD COLUMN dedupe_key TEXT;
CREATE INDEX jobs_duplicate_of ON jobs(duplicate_of);
CREATE INDEX jobs_dedupe_key ON jobs(dedupe_key);
