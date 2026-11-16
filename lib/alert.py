"""Notification cascade with dedup, quiet hours and known-debt expiry.

Why this exists
---------------
Reconcilers run on a timer and re-detect the *same* violation every day.
Naive alerting pages the owner daily about an issue they already saw —
alert fatigue kills the signal. The PAS alerting layer solved this with
three small mechanisms, generalized here:

1. **Latest-per-key dedup state** — a JSON state file maps
   ``alert_key -> last_notified_iso``. A key re-alerts only after
   ``dedup_hours``; resolved keys stop mattering because the caller only
   feeds *current* violations.
2. **Quiet hours** — a ``"HH:MM-HH:MM"`` UTC window (overnight wrap
   supported). During quiet hours ``notify()`` defers: it does NOT mark
   the key as sent, so the next non-quiet run delivers it.
3. **known_debt expiry** — violations can be acknowledged with a
   ``{"reason": ..., "expires": "YYYY-MM-DD"}`` entry. While unexpired the
   violation is suppressed *in the check*; the day after ``expires`` it
   resurfaces automatically. Entries without ``expires`` never expire
   (explicit permanent waiver) — use sparingly.

Sinks are pluggable: ``sink`` is any callable ``(level, message) -> bool``
or an object with ``.send(level, message)``. Built-ins: ``PrintSink``
(default, stderr), ``WebhookSink`` (generic JSON POST), ``CommandSink``
(run an external notifier script).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Protocol

LEVELS = ("debug", "info", "warn", "critical")


# ---------------------------------------------------------------- sinks

class Sink(Protocol):
    def send(self, level: str, message: str) -> bool: ...


class PrintSink:
    """Default sink: writes to stderr. Returns True (delivery = logged)."""

    def send(self, level: str, message: str) -> bool:
        print(f"[{level.upper()}] {message}", file=sys.stderr)
        return True


class WebhookSink:
    """POST ``{"text": message, "level": level}`` to a generic webhook.

    Works with Slack-compatible incoming webhooks out of the box; any
    endpoint accepting a JSON body works. URL comes from ``env_var``
    (default ``ALERT_WEBHOOK``) — never hardcode endpoints or tokens.
    """

    def __init__(self, env_var: str = "ALERT_WEBHOOK", timeout: int = 15):
        self.env_var = env_var
        self.timeout = timeout

    def send(self, level: str, message: str) -> bool:
        url = os.environ.get(self.env_var)
        if not url:
            return False
        payload = json.dumps({"text": message, "level": level})
        try:
            r = subprocess.run(
                ["curl", "-sS", "-X", "POST",
                 "-H", "Content-Type: application/json",
                 "--data", payload, url],
                capture_output=True, text=True, timeout=self.timeout)
            return r.returncode == 0
        except Exception:
            return False


class CommandSink:
    """Run an external notifier: ``<cmd> <level> <message>`` via argv.

    The command receives the message as a single argv element (no shell
    interpolation — safe for arbitrary violation text).
    """

    def __init__(self, argv: list[str], timeout: int = 20):
        self.argv = argv
        self.timeout = timeout

    def send(self, level: str, message: str) -> bool:
        try:
            r = subprocess.run([*self.argv, level, message],
                               capture_output=True, text=True,
                               timeout=self.timeout)
            return r.returncode == 0
        except Exception:
            return False


def _coerce_sink(sink) -> Sink:
    if sink is None:
        return PrintSink()
    if hasattr(sink, "send"):
        return sink
    if callable(sink):
        class _Fn:
            def send(self, level, message):
                return bool(sink(level, message))
        return _Fn()
    raise TypeError(f"unsupported sink: {type(sink)!r}")


# ------------------------------------------------------- quiet hours

def parse_quiet_hours(spec: str) -> tuple[int, int] | None:
    """``"23:00-07:00"`` -> ``(1380, 420)`` minutes-of-day, or None.

    Overnight windows (start > end) are supported: 23:00-07:00 means
    23:00→24:00 and 00:00→07:00. Returns None for malformed input.
    """
    try:
        start, end = spec.split("-", 1)
        sh, sm = (int(x) for x in start.split(":"))
        eh, em = (int(x) for x in end.split(":"))
        if not (0 <= sh < 24 and 0 <= eh < 24 and 0 <= sm < 60 and 0 <= em < 60):
            return None
        return sh * 60 + sm, eh * 60 + em
    except Exception:
        return None


def in_quiet_hours(now: datetime, window: tuple[int, int] | None,
                   tz=timezone.utc) -> bool:
    """True if ``now`` (converted to ``tz``) falls inside the window."""
    if window is None:
        return False
    start, end = window
    local = now.astimezone(tz)
    minute = local.hour * 60 + local.minute
    if start == end:
        return False
    if start < end:
        return start <= minute < end
    return minute >= start or minute < end  # overnight wrap


# ------------------------------------------------------- known debt

def _parse_expires(value) -> datetime | None:
    """Parse ``expires`` (``YYYY-MM-DD`` or ISO datetime) to aware UTC."""
    if value is None:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def active_debts(entries: Iterable[dict], now: datetime | None = None,
                 match: dict | None = None) -> list[dict]:
    """Filter ``known_debt`` entries to those still suppressing alerts.

    An entry suppresses while ``expires`` is in the future (or absent —
    a documented permanent waiver). Once ``expires`` passes, the entry is
    dropped and the underlying violation resurfaces on the next run.
    ``match`` optionally restricts to entries whose fields equal the
    given values (e.g. ``{"repo": name}`` or ``{"repo": name, "pr": 42}``).
    """
    now = now or datetime.now(timezone.utc)
    out = []
    for d in entries or []:
        if not isinstance(d, dict):
            continue
        if match:
            if any(d.get(k) != v for k, v in match.items()):
                continue
        exp = _parse_expires(d.get("expires"))
        if exp is not None and exp < now:
            continue  # debt expired -> violation is live again
        out.append(d)
    return out


def debt_reason(entries: Iterable[dict], **match) -> str:
    """First matching active debt's ``reason`` (for embedding in reports)."""
    for d in active_debts(entries, match=match):
        return str(d.get("reason") or "known debt")
    return ""


# ------------------------------------------------------- alerter

class Alerter:
    """Dedup + quiet-hours + pluggable-sink notifier.

    Args:
        state_path: JSON file ``{alert_key: last_sent_iso}``. Under the
                    XDG state dir by default (``<state_dir>/alert-state.json``).
        sink:       Sink/callable; default prints to stderr.
        dedup_hours: minimum interval between notifications for the same key.
        quiet_hours: ``"HH:MM-HH:MM"`` UTC window; deferred sends are NOT
                     marked, so they retry on the next non-quiet run.
        state_dir:  base dir for the default state path and log.
    """

    def __init__(self, state_path: str | os.PathLike[str] | None = None,
                 sink=None, dedup_hours: float = 1.0,
                 quiet_hours: str | None = None,
                 state_dir: str | os.PathLike[str] | None = None):
        if state_path is None:
            base = Path(state_dir) if state_dir else _default_state_dir()
            state_path = base / "alert-state.json"
        self.state_path = Path(state_path)
        self.sink = _coerce_sink(sink)
        self.dedup_hours = float(dedup_hours)
        self.quiet_window = parse_quiet_hours(quiet_hours) if quiet_hours else None
        self._state: dict[str, str] | None = None

    # -- state ------------------------------------------------------

    def _load(self) -> dict[str, str]:
        if self._state is not None:
            return self._state
        try:
            self._state = json.loads(self.state_path.read_text())
            if not isinstance(self._state, dict):
                self._state = {}
        except Exception:
            self._state = {}
        return self._state

    def _save(self) -> None:
        state = self._load()
        # prune entries older than 24h — dedup windows are hours, not days
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        kept = {}
        for k, v in state.items():
            t = _parse_expires(v)
            if t is not None and t >= cutoff:
                kept[k] = v
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(kept, indent=0))
        self._state = kept

    # -- public API ---------------------------------------------------

    def is_quiet(self, now: datetime | None = None) -> bool:
        return in_quiet_hours(now or datetime.now(timezone.utc),
                              self.quiet_window)

    def recently_sent(self, key: str,
                      now: datetime | None = None) -> bool:
        last = _parse_expires(self._load().get(key))
        if last is None:
            return False
        now = now or datetime.now(timezone.utc)
        return (now - last).total_seconds() < self.dedup_hours * 3600

    def notify(self, level: str, key: str, message: str,
               *, now: datetime | None = None) -> bool:
        """Send ``message`` once per ``key`` per ``dedup_hours``.

        Returns True only when the sink accepted the message AND the key
        was marked sent. Returns False on dedup-hit, quiet hours, or sink
        failure (caller may retry later — state is not poisoned).
        """
        level = level if level in LEVELS else "info"
        now = now or datetime.now(timezone.utc)
        if self.recently_sent(key, now):
            return False
        if self.is_quiet(now):
            return False
        if not self.sink.send(level, message):
            return False
        self._load()[key] = now.isoformat()
        self._save()
        return True

    def send_raw(self, level: str, message: str) -> bool:
        """Deliver through the sink WITHOUT dedup/quiet-hours checks.

        For batch callers (e.g. drift-alert grouping N violations into one
        message): they filter+dedup themselves, then mark keys via
        ``mark_sent``. Returns the sink's verdict."""
        level = level if level in LEVELS else "info"
        return bool(self.sink.send(level, message))

    def mark_sent(self, key: str, now: datetime | None = None) -> None:
        """Record ``key`` as notified at ``now`` (after a successful send)."""
        self._load()[key] = (now or datetime.now(timezone.utc)).isoformat()
        self._save()

    def flush(self) -> None:
        """Force-write pending state (mostly for tests/shutdown)."""
        self._save()


def _default_state_dir() -> Path:
    """XDG state dir for alert state — ``$XDG_STATE_HOME/<app>`` or
    ``~/.local/state/<app>``. ``<app>`` defaults to ``devin-alerts``."""
    app = os.environ.get("ALERT_APP", "devin-alerts")
    base = os.environ.get("XDG_STATE_HOME")
    root = Path(base) if base else Path.home() / ".local" / "state"
    return root / app


# Module-level convenience: a process-wide default alerter.
_default: Alerter | None = None


def get_alerter(**kwargs) -> Alerter:
    global _default
    if _default is None or kwargs:
        _default = Alerter(**kwargs)
    return _default


def notify(level: str, key: str, message: str, **kwargs) -> bool:
    """One-shot notify via the shared alerter (see ``Alerter.notify``)."""
    return get_alerter(**kwargs).notify(level, key, message)
