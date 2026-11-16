"""XDG Base Directory compliant paths.

Why this exists
---------------
Reconciler state (ledgers, alert marks, plan files) must live somewhere
predictable on every machine — and *never* under a hardcoded home path.
The XDG Base Directory spec is the portable answer:

- ``state_dir()``  -> ``$XDG_STATE_HOME/<app>``   (default ``~/.local/state/<app>``)
- ``config_dir()`` -> ``$XDG_CONFIG_HOME/<app>`` (default ``~/.config/<app>``)
- ``data_dir()``   -> ``$XDG_DATA_HOME/<app>``   (default ``~/.local/share/<app>``)
- ``cache_dir()``  -> ``$XDG_CACHE_HOME/<app>``  (default ``~/.cache/<app>``)
- ``runtime_dir()``-> ``$XDG_RUNTIME_DIR/<app>`` (default ``/tmp/<app>-<uid>``)

``<app>`` is the application name — one ecosystem, one app id, so all
scripts agree on the same directories. Override per-process with the
``*_APP`` env vars or pass ``app=`` explicitly.

Linux parity note: on Windows, ``%LOCALAPPDATA%``/``%APPDATA%`` fulfil
the same role; callers that need Windows support should resolve through
``platform_dirs()`` or their own helper — this module targets POSIX
(XDG) systems, which is where the reconcilers run (systemd --user).
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

APP = os.environ.get("APP_NAME", "devin-ecosystem")


def _app(app: str | None) -> str:
    return app or os.environ.get("APP_NAME", APP)


def state_dir(app: str | None = None,
              *, create: bool = False) -> Path:
    """``$XDG_STATE_HOME/<app>`` — ledgers, alert state, drift output."""
    base = os.environ.get("XDG_STATE_HOME")
    root = Path(base) if base else Path.home() / ".local" / "state"
    p = root / _app(app)
    if create:
        p.mkdir(parents=True, exist_ok=True)
    return p


def config_dir(app: str | None = None,
               *, create: bool = False) -> Path:
    """``$XDG_CONFIG_HOME/<app>`` — YAML manifests, user config."""
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    p = root / _app(app)
    if create:
        p.mkdir(parents=True, exist_ok=True)
    return p


def data_dir(app: str | None = None,
             *, create: bool = False) -> Path:
    """``$XDG_DATA_HOME/<app>`` — installed state, non-config data."""
    base = os.environ.get("XDG_DATA_HOME")
    root = Path(base) if base else Path.home() / ".local" / "share"
    p = root / _app(app)
    if create:
        p.mkdir(parents=True, exist_ok=True)
    return p


def cache_dir(app: str | None = None,
              *, create: bool = False) -> Path:
    """``$XDG_CACHE_HOME/<app>`` — regenerable caches only."""
    base = os.environ.get("XDG_CACHE_HOME")
    root = Path(base) if base else Path.home() / ".cache"
    p = root / _app(app)
    if create:
        p.mkdir(parents=True, exist_ok=True)
    return p


def runtime_dir(app: str | None = None,
                *, create: bool = False) -> Path:
    """``$XDG_RUNTIME_DIR/<app>`` — sockets, pid files, ephemeral state.

    ``XDG_RUNTIME_DIR`` is usually ``/run/user/<uid>`` and may be absent
    (e.g. over SSH without pam_systemd); fall back to a per-user tmpdir.
    """
    base = os.environ.get("XDG_RUNTIME_DIR")
    root = Path(base) if base else Path(tempfile.gettempdir()) / f"{_app(app)}-{os.getuid()}"
    p = root / _app(app) if base else root
    if create:
        p.mkdir(parents=True, exist_ok=True)
    return p


def platform_dirs(app: str | None = None) -> dict[str, Path]:
    """All five dirs at once — handy for --help text or diagnostics."""
    return {
        "state": state_dir(app),
        "config": config_dir(app),
        "data": data_dir(app),
        "cache": cache_dir(app),
        "runtime": runtime_dir(app),
    }


# Convenience constants resolved lazily at call time is safer than at
# import time (env may be set after import in tests); provide functions.
def drift_state_dir(app: str | None = None,
                    env_override: str = "DRIFT_STATE_DIR") -> Path:
    """State dir honouring a script-specific override first.

    Convention across reconcilers: ``DRIFT_STATE_DIR`` (or the script's
    own ``*_STATE_DIR``) wins over the XDG default so tests and one-off
    runs can redirect output without touching the real ledger.
    """
    override = os.environ.get(env_override)
    if override:
        return Path(override).expanduser()
    return state_dir(app, create=True)
