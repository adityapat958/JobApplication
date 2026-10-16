CREATE TABLE jobs (
    id            TEXT PRIMARY KEY,
    source        TEXT NOT NULL,
    source_id     TEXT NOT NULL,
    url           TEXT,
    apply_url     TEXT,
    company       TEXT,
    title         TEXT,
    location      TEXT,
    job_type      TEXT,
    posted_at     TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at  TEXT NOT NULL,
    description   TEXT,
    jd_saved_at   TEXT,
    language      TEXT,
    raw           TEXT,
    match_pct     REAL,
    matched       TEXT,
    missing       TEXT,
    status        TEXT NOT NULL DEFAULT 'new'
                  CHECK (status IN ('new','interested','applied','interview','rejected','offer','ignored')),
    done          INTEGER NOT NULL DEFAULT 0,
    done_at       TEXT,
    notes         TEXT,
    hidden        INTEGER NOT NULL DEFAULT 0,
    hidden_reason TEXT,
    UNIQUE (source, source_id)
);
CREATE INDEX jobs_status ON jobs(status);
CREATE INDEX jobs_first_seen ON jobs(first_seen_at);

CREATE TABLE runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    source      TEXT,
    fetched     INTEGER DEFAULT 0,
    new         INTEGER DEFAULT 0,
    errors      TEXT
);

CREATE TABLE builds (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id     TEXT NOT NULL REFERENCES jobs(id),
    pdf_path   TEXT NOT NULL,
    created_at TEXT NOT NULL,
    keywords   TEXT
);

CREATE VIRTUAL TABLE jobs_fts USING fts5(
    company, title, description, content='jobs', content_rowid='rowid'
);
CREATE TRIGGER jobs_ai AFTER INSERT ON jobs BEGIN
    INSERT INTO jobs_fts(rowid, company, title, description)
    VALUES (new.rowid, new.company, new.title, new.description);
END;
CREATE TRIGGER jobs_ad AFTER DELETE ON jobs BEGIN
    INSERT INTO jobs_fts(jobs_fts, rowid, company, title, description)
    VALUES ('delete', old.rowid, old.company, old.title, old.description);
END;
CREATE TRIGGER jobs_au AFTER UPDATE OF company, title, description ON jobs BEGIN
    INSERT INTO jobs_fts(jobs_fts, rowid, company, title, description)
    VALUES ('delete', old.rowid, old.company, old.title, old.description);
    INSERT INTO jobs_fts(rowid, company, title, description)
    VALUES (new.rowid, new.company, new.title, new.description);
END;
