"""MCP server (stdio) for Claude Desktop: `jobapp mcp`."""
from __future__ import annotations

import functools
import json

try:  # mcp ≥ 2
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server

from . import tools

INSTRUCTIONS = (
    "JobApplication helps a non-technical user find jobs and make a tailored PDF resume per job. "
    "Explain results in plain English. Typical flow: doctor → find_jobs → list_jobs → job_details → "
    "build_resume → mark_job(applied). For a Word or PDF resume: import_resume_prepare then "
    "import_resume_submit_tex (max 3 rounds). Cover letter: cover_letter_prepare then cover_letter_submit "
    "(max 3 rounds; only facts from the resume or the ad)."
)


def _wrap(fn):
    @functools.wraps(fn)
    def inner(*a, **kw):
        return json.dumps(fn(*a, **kw), ensure_ascii=False, indent=1, default=str)
    return inner


def create_server():
    server = _Server("jobapplication", instructions=INSTRUCTIONS)
    for fn in tools.ALL:
        server.tool(name=fn.__name__, description=fn.__doc__)(_wrap(fn))
    return server


def main() -> None:
    from ..log import setup
    setup()
    create_server().run("stdio")
