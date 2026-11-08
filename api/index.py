"""Vercel serverless entry point for the OpenAid API.

Vercel Python functions look for ``app`` (ASGI) in ``api/index.py``. The
domain packages live outside this directory, so their source roots are put
on ``sys.path`` explicitly (editable installs do not exist on the platform).
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _pkg_dir in (_ROOT / "backend", _ROOT / "apps" / "api"):
    if str(_pkg_dir) not in sys.path:
        sys.path.insert(0, str(_pkg_dir))

from openaid_api.main import app  # noqa: E402

# Vercel ASGI entry point
app = app
