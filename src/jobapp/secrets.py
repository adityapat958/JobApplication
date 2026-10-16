"""Secrets: environment → system keychain (macOS Keychain via keyring) → $JOBAPP_HOME/.env."""
from __future__ import annotations

import os

from . import paths

SERVICE = "JobApplication"


def _dotenv() -> dict[str, str]:
    f = paths.home() / ".env"
    out: dict[str, str] = {}
    if not f.exists():
        return out
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip().removeprefix("export ").strip()] = v.strip().strip('"').strip("'")
    return out


def get(name: str) -> str | None:
    if os.environ.get(name):
        return os.environ[name]
    try:
        import keyring
        v = keyring.get_password(SERVICE, name)
        if v:
            return v
    except Exception:  # noqa: BLE001  (no keyring backend on this machine)
        pass
    return _dotenv().get(name) or None


def set(name: str, value: str) -> str:  # noqa: A001
    """Store in the keychain if possible, else in $JOBAPP_HOME/.env (chmod 600). Returns where."""
    try:
        import keyring
        keyring.set_password(SERVICE, name, value)
        return "keychain"
    except Exception:  # noqa: BLE001
        pass
    f = paths.home() / ".env"
    data = _dotenv()
    data[name] = value
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("".join(f"{k}={v}\n" for k, v in data.items()), encoding="utf-8")
    try:
        f.chmod(0o600)
    except OSError:
        pass
    return str(f)


def names() -> list[str]:
    return ["ANTHROPIC_API_KEY", "GEMINI_API_KEY"]
