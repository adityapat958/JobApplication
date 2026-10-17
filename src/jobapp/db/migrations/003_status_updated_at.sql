-- When the status was last changed in JobApplication (two-way connectors compare it with the note's
-- modification time: the newer side wins).
ALTER TABLE jobs ADD COLUMN status_updated_at TEXT;
UPDATE jobs SET status_updated_at = COALESCE(done_at, first_seen_at);
