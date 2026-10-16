"""`python -m jobapp.cli_entry …` — same as the `jobapp` command (used by tests and launchd)."""
from .cli import main

if __name__ == "__main__":
    main()
