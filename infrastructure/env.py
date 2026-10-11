"""Reading the repository's .env file, for local runs.

On Cloud Run there is no .env -- settings arrive as environment variables and
secrets -- and this does nothing.
"""

from __future__ import annotations

import os
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


def load_dotenv(path: Path = ENV_FILE) -> None:
    """Set each KEY=value line as an environment variable.

    Real environment variables win, so a value exported in the shell or set by
    Cloud Run is never overridden by the file.
    """
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())
