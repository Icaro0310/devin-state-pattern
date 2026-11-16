"""Severity ordering for reconciliation statuses — total order + safe worst-of.

WHY this module exists (CASE-STUDIES.md, bug c):
    A reconciler that folds many per-item statuses into one verdict needs a
    total order. The naive version initialises the accumulator to the *best*
    status ("OK") and promotes only on strictly-greater severity. Statuses
    that share the top severity with OK — or sit below it — then NEVER
    promote, and the report says "all OK" forever while the class is broken.
    Observed in production: a MIGRATED status with SEV_ORDER[MIGRATED]=0 tied
    with OK, and every run reported 0 MIGRATED items for months.

    The fix is two rules, both enforced here:
      1. Accumulate with ``worst_of`` starting from ``None`` — first status
         always wins, ties never demote.
      2. Promotion is STRICTLY ``>`` on the rank — equal ranks keep the
         incumbent (documented, deterministic).

Adopters: define your own RANK dict for your status vocabulary; the helpers
below are vocabulary-agnostic.
"""

from __future__ import annotations

from typing import Iterable, TypeVar

T = TypeVar("T")

# TODO(adopt): replace with YOUR status vocabulary. Convention used by the
# reference implementation: benign states rank 0-1, attention states 2-4,
# hard violations share the top rank. Equal ranks are legal — promotion is
# strict, so ordering within a rank is arbitrary but stable.
RANK: dict[str, int] = {
    "OK": 0,
    "MIGRATED": 0,       # moved to another system — not a failure
    "DISABLED": 0,       # intentionally off
    "UNVERIFIABLE": 1,   # cannot measure — visible but not alarming
    "DRYRUN": 2,         # would-fix mode, reports but doesn't act
    "SILENT": 3,         # declared active but produced no evidence
    "NO_EFFECT": 4,      # runs but changes nothing observable
    "MISSING": 5,        # declared but absent
    "PHANTOM": 5,        # exists but undeclared
    "COMPETING": 5,      # two tools claim the same domain
}


def rank(status: str) -> int:
    """Rank of a status; unknown statuses rank ABOVE everything (fail-safe).

    WHY: an unrecognised status is more likely a new violation class than a
    new benign state. Ranking it top keeps it visible instead of silently
    folding into OK.
    """
    return RANK.get(status, max(RANK.values()) + 1)


def worst_of(statuses: Iterable[str]) -> str | None:
    """Highest-severity status in ``statuses``; ``None`` if empty.

    Deterministic: on equal ranks the FIRST status wins (iteration order).
    Callers that need a specific tie-break should sort before calling.
    """
    worst: str | None = None
    for st in statuses:
        if worst is None or rank(st) > rank(worst):
            worst = st
    return worst


def is_benign(status: str | None) -> bool:
    """True when ``status`` should NOT page anyone (rank <= DRYRUN)."""
    if status is None:
        return True
    return rank(status) <= RANK.get("DRYRUN", 2)
