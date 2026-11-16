"""Append-only JSONL store with file locking.

Why this exists
---------------
Drift/compliance reconcilers append one JSON object per line to a shared
ledger (e.g. ``drift.jsonl``). Several processes can write to the same
ledger in the same window: the daily reconcile timer, a SessionEnd hook,
and a manual audit run. Without locking, two appends can interleave and
produce a torn line that every downstream reader silently skips — the
violation disappears without ever being recorded.

Design notes
------------
- ``append()`` opens in ``"a"`` mode and takes an exclusive ``fcntl``
  lock around the write+fsync. POSIX only; on platforms without ``fcntl``
  the lock degrades to a no-op (still safe on POSIX filesystems because
  ``O_APPEND`` writes are atomic for reasonable line sizes).
- ``iter_lines()`` never raises on malformed JSON — a corrupt line is
  skipped, not fatal. Ledgers are long-lived; one bad line must not blind
  the reader.
- ``latest_per_key()`` implements "latest run wins" semantics: for
  append-only ledgers, the last occurrence of a key is the current state;
  older entries with ``count > 0`` are history, not alerts.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

try:  # POSIX
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None  # type: ignore[assignment]


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _default(obj: Any) -> Any:
    """Fallback serializer for non-JSON-native values (datetime, Path...)."""
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return str(obj)


def append(path: str | os.PathLike[str], obj: dict,
           *, fsync: bool = True) -> None:
    """Append one JSON object as a single line, under an exclusive lock.

    Args:
        path: ledger file path (created, including parents, if missing).
        obj:  mapping to serialize; non-JSON values go through ``str``.
        fsync: flush+fsync before releasing the lock. Keep True for
               ledgers whose loss would hide drift; False for hot paths.
    """
    p = Path(path)
    _ensure_parent(p)
    line = json.dumps(obj, ensure_ascii=False, default=_default) + "\n"
    with open(p, "a", encoding="utf-8") as f:
        if fcntl is not None:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            f.write(line)
            f.flush()
            if fsync:
                os.fsync(f.fileno())
        finally:
            if fcntl is not None:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def iter_lines(path: str | os.PathLike[str],
               *, cls: Optional[str] = None,
               errors: str = "skip") -> Iterator[dict]:
    """Yield parsed JSON objects from a JSONL file, oldest first.

    Args:
        path: ledger file path; missing file yields nothing.
        cls:  if set, only yield records whose ``"class"`` field equals it.
        errors: ``"skip"`` (default) ignores malformed lines; ``"raise"``
                re-raises ``json.JSONDecodeError`` for strict callers.
    """
    p = Path(path)
    if not p.exists():
        return
    with open(p, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                if errors == "raise":
                    raise
                continue
            if not isinstance(rec, dict):
                continue
            if cls is not None and rec.get("class") != cls:
                continue
            yield rec


def latest_per_key(path: str | os.PathLike[str],
                   key: Callable[[dict], Any] | str,
                   *, cls: Optional[str] = None) -> dict:
    """Return ``{key: record}`` keeping only the LAST entry per key.

    Append-only ledgers are replayed in file order, so the last write wins.
    ``key`` may be a field name or a callable ``record -> hashable``.
    """
    out: dict[Any, dict] = {}
    for rec in iter_lines(path, cls=cls):
        k = rec.get(key) if isinstance(key, str) else key(rec)
        if k is None:
            continue
        out[k] = rec
    return out


def read_all(path: str | os.PathLike[str],
             *, cls: Optional[str] = None) -> list[dict]:
    """Materialize ``iter_lines`` as a list (small ledgers / tests)."""
    return list(iter_lines(path, cls=cls))


def rotate_if_oversize(path: str | os.PathLike[str],
                       max_bytes: int = 10 * 1024 * 1024,
                       keep_gz_months: int = 3) -> Optional[Path]:
    """Monthly-gzip rotation for a growing ledger.

    If ``path`` exceeds ``max_bytes`` it is renamed to
    ``<name>.YYYYMM`` and gzipped; archives older than
    ``keep_gz_months`` are deleted. Returns the archive path when a
    rotation happened, else ``None``.
    """
    import gzip
    import shutil
    from datetime import datetime, timezone

    p = Path(path)
    if not p.exists() or p.stat().st_size <= max_bytes:
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m")
    tmp = p.with_name(f"{p.name}.{stamp}.tmp")
    shutil.move(str(p), str(tmp))
    gz = p.with_name(f"{p.name}.{stamp}.gz")
    with open(tmp, "rb") as src, gzip.open(gz, "wb") as dst:
        shutil.copyfileobj(src, dst)
    tmp.unlink()
    # prune archives older than keep_gz_months
    cutoff_month = (datetime.now(timezone.utc).year * 12
                    + datetime.now(timezone.utc).month - keep_gz_months)
    for old in p.parent.glob(f"{p.name}.*.gz"):
        m = old.name.rsplit(".", 2)[-2] if old.name.count(".") >= 2 else ""
        try:
            y, mo = int(m[:4]), int(m[4:6])
        except (ValueError, IndexError):
            continue
        if y * 12 + mo < cutoff_month:
            try:
                old.unlink()
            except OSError:
                pass
    return gz


# Convenience alias matching the naming used across reconcilers.
JsonlWriter = append
