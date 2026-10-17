"""Re-score saved jobs (after keywords.yaml / the skills vocabulary / a job's resume variant changed)."""
from __future__ import annotations

import json


def rescore_all(cfg, conn, *, ids: list[str] | None = None) -> dict:
    """Recompute match/matched/missing. Returns {"jobs": n, "changed": k}. Only changed rows are written."""
    from .. import db
    from .matching import Matcher
    m = Matcher.from_config(cfg)
    q = "SELECT id, title, company, location, description, variant, match_pct, matched, missing FROM jobs"
    rows = [dict(r) for r in conn.execute(q)]
    if ids is not None:
        want = set(ids)
        rows = [r for r in rows if r["id"] in want]
    changed = 0
    for r in rows:
        res = m.score_job(r)
        new = (res.pct, json.dumps(res.matched, ensure_ascii=False), json.dumps(res.missing, ensure_ascii=False))
        if new != (r["match_pct"], r["matched"] or "[]", r["missing"] or "[]"):
            db.set_match(conn, r["id"], res.pct, res.matched, res.missing)
            changed += 1
    return {"jobs": len(rows), "changed": changed}
