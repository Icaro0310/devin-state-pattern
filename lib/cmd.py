"""Subprocess runner shared by reconcilers and hooks.

Why this exists
---------------
Every drift check shells out to ``git``, ``gh``, ``systemctl``, ``ssh``…
and each call site reinvented the same three lines of
``subprocess.run(..., capture_output=True, text=True)``. The important
part is the *contract*, not the call:

- **never raise on non-zero exit** — a failing probe is data
  (``rc != 0``), not an exception. Reconcilers are fail-open by design:
  one broken probe must not blind the whole sweep.
- **always bounded** — ``timeout`` is mandatory in spirit; an unbounded
  ``git fetch`` or ``ssh`` can hang a daily timer forever. On timeout we
  return ``rc=124`` (GNU ``timeout`` convention) instead of raising.
- **one return shape** — ``(rc, stdout, stderr)`` everywhere, so call
  sites never juggle ``CompletedProcess`` vs string.

Usage::

    from lib.cmd import run

    rc, out, err = run(["git", "-C", path, "status", "--porcelain"], timeout=15)
    rc, out, err = run("crontab -l 2>/dev/null", timeout=10)   # str => shell
"""

from __future__ import annotations

import subprocess
from typing import Sequence, Union

# rc values with special meaning (documented, not magic)
RC_TIMEOUT = 124        # matches GNU coreutils `timeout`
RC_NOT_FOUND = 127      # matches shell "command not found"
RC_ERROR = -1           # runner itself failed (bad args, OS error)


def run(cmd: Union[str, Sequence[str]],
        timeout: float = 30,
        cwd: Union[str, None] = None,
        shell: bool | None = None,
        env: dict | None = None) -> tuple[int, str, str]:
    """Run ``cmd`` and return ``(rc, stdout, stderr)``.

    Args:
        cmd:     argument list (preferred — no quoting bugs) or a string.
                 A string implies ``shell=True`` unless ``shell=False``.
        timeout: seconds before the process is killed; on expiry returns
                 ``(RC_TIMEOUT, partial_stdout, "timeout after Ns")``.
        cwd:     working directory for the child.
        shell:   override the str-implies-shell default.
        env:     full environment for the child (None = inherit).

    Never raises for: non-zero exit, timeout, missing binary, bad cwd.
    """
    use_shell = shell if shell is not None else isinstance(cmd, str)
    try:
        proc = subprocess.run(
            cmd,
            shell=use_shell,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            env=env,
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except subprocess.TimeoutExpired as e:
        out = e.stdout if isinstance(e.stdout, str) else ""
        err = e.stderr if isinstance(e.stderr, str) else ""
        note = f"timeout after {timeout}s"
        return RC_TIMEOUT, out, (err + "\n" + note).strip() or note
    except FileNotFoundError as e:
        return RC_NOT_FOUND, "", f"command not found: {e}"
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        return RC_ERROR, "", f"runner error: {e}"


def ok(rc: int) -> bool:
    """True when ``rc`` indicates success (``run`` never raises, so callers
    still need *some* predicate — this is it)."""
    return rc == 0


def which(name: str, timeout: float = 5) -> bool:
    """True if ``name`` resolves on PATH (portable ``which`` check)."""
    rc, _out, _err = run(["which", name] if _posix() else
                         ["where", name], timeout=timeout)
    return rc == 0


def _posix() -> bool:
    import os
    return os.name == "posix"


def git(repo_path: str, *args: str, timeout: float = 30) -> tuple[int, str, str]:
    """Convenience wrapper: ``git -C <repo_path> <args...>``."""
    return run(["git", "-C", str(repo_path), *args], timeout=timeout)
