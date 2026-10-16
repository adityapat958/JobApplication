"""`jobapp report-bug`: zip logs + doctor + config with personal details and secrets removed."""
from __future__ import annotations

import json
import platform
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path

import yaml

from . import __version__, paths

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE = re.compile(r"(?<![\w.])\+?\d[\d ()./-]{6,}\d(?![\w.])")
SECRET_VALUE = re.compile(r"\b(sk-ant-[\w-]{8,}|sk-[A-Za-z0-9]{16,}|AIza[\w-]{20,}|gh[pousr]_[A-Za-z0-9]{16,}|"
                          r"xox[abp]-[\w-]{10,})\b")
SECRET_KEY = re.compile(r"(?i)\b([\w-]*(?:api[_-]?key|token|password|passwd|secret|cookie|session)[\w-]*)"
                        r"(\s*[:=]\s*)(\"[^\"]*\"|'[^']*'|\S+)")
DATE_LIKE = re.compile(r"^\d{4}-\d{2}-\d{2}")


def _name_terms(name: str | None) -> list[str]:
    if not name:
        return []
    parts = [p for p in re.split(r"\s+", name.strip()) if len(p) >= 2]
    return sorted({name.strip(), *parts}, key=len, reverse=True)


def redact(text: str, name: str | None = None) -> str:
    out = SECRET_VALUE.sub("[REDACTED-SECRET]", text)
    out = SECRET_KEY.sub(lambda m: f"{m[1]}{m[2]}[REDACTED-SECRET]", out)
    out = EMAIL.sub("[REDACTED-EMAIL]", out)

    def phone(m):
        s = m.group(0)
        digits = re.sub(r"\D", "", s)
        if DATE_LIKE.match(s) or len(digits) < 8 or re.fullmatch(r"\d{4}[-/.]\d{2}[-/.]\d{2}.*", s):
            return s
        if re.fullmatch(r"[\d.]+", s) and s.count(".") >= 1:  # version numbers / decimals
            return s
        return "[REDACTED-PHONE]"
    out = PHONE.sub(phone, out)
    for term in _name_terms(name):
        out = re.sub(re.escape(term), "[REDACTED-NAME]", out, flags=re.I)
    home = str(Path.home())
    out = out.replace(home, "~")
    return out


def _profile_name() -> str | None:
    p = paths.config_path()
    if not p.exists():
        return None
    try:
        return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("profile", {}).get("name")
    except Exception:  # noqa: BLE001
        m = re.search(r"name:\s*(.+)", p.read_text(encoding="utf-8", errors="replace"))
        return m[1].strip() if m else None


def make_report(network: bool = True) -> Path:
    from . import doctor as d
    name = _profile_name()
    out_dir = paths.output_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"bug-report-{datetime.now().strftime('%Y-%m-%d-%H%M')}.zip"
    try:
        checks = d.run(network=network)
        doc = "\n".join(f"[{c.status}] {c.name}: {c.detail}" + (f"\n    hint: {c.hint}" if c.hint else "")
                        for c in checks) + "\n\n" + d.summary(checks)
    except Exception as e:  # noqa: BLE001
        doc = f"doctor crashed: {e!r}"
    info = {"jobapp": __version__, "python": sys.version, "platform": platform.platform(),
            "created": datetime.now().isoformat(timespec="seconds")}
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("system.json", json.dumps(info, indent=2))
        z.writestr("doctor.txt", redact(doc, name))
        cfgp = paths.config_path()
        if cfgp.exists():
            z.writestr("config.yaml", redact(cfgp.read_text(encoding="utf-8", errors="replace"), name))
        logs = paths.logs_dir()
        if logs.exists():
            for f in sorted(logs.iterdir()):
                if f.is_file() and f.stat().st_size < 5_000_000:
                    z.writestr(f"logs/{f.name}", redact(f.read_text(encoding="utf-8", errors="replace"), name))
        try:
            from . import db
            if paths.db_path().exists():
                conn = db.connect()
                stats = {"counts": db.counts(conn), "schema": db.schema_version(conn), "runs": db.last_runs(conn, 20)}
                z.writestr("db_stats.json", redact(json.dumps(stats, indent=2, default=str), name))
        except Exception as e:  # noqa: BLE001
            z.writestr("db_stats.json", json.dumps({"error": repr(e)}))
    return dest
