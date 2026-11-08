"""OpenAid API — Vercel entry point (services mode).

The deployed service root (``api/``) contains this file plus the shared
packages copied in by the service ``buildCommand`` (``openaid_core``,
``openaid_api``). When running from a full repository checkout (local dev,
CI) the packages are found at the repo root instead, so both lookup paths
are on ``sys.path``.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent          # built service root (copied packages)
_REPO = _HERE.parent                             # full repository checkout
for _pkg_dir in (_HERE, _REPO / "backend", _REPO / "apps" / "api"):
    if str(_pkg_dir) not in sys.path:
        sys.path.insert(0, str(_pkg_dir))

from openaid_api.main import app  # noqa: E402
