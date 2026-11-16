"""Repo-hygiene tests for the devin-state-pattern pattern repo.

These tests guard the *pattern itself*, not any generated ecosystem:
  * templates ship with TODO markers so adopters know what to fill in
  * no personal paths, personal-org references or secret-shaped tokens leak
    into a public repo
  * every examples/*.yaml.example is valid YAML
  * lib/ exposes the shared helpers checkers rely on
  * scripts/bootstrap.sh scaffolds a working target directory
  * scripts/validate.sh passes end-to-end

Stdlib + PyYAML + pytest only — no third-party beyond that.
"""

import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]

# The two files that DEFINE the scan patterns below. They are excluded from
# every content scan so their own pattern literals cannot self-match.
CHECKER_FILES = {
    "scripts/validate.sh",
    "tests/test_pattern.py",
}

# Directories never scanned (VCS internals, caches, vendored envs).
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "node_modules", ".venv"}

# Patterns — kept identical in spirit to scripts/validate.sh. Each is
# assembled from fragments so this file does not literally contain its own
# match strings (the file is also excluded from scans — defense in depth
# for anyone grepping the repo by hand).
HOME_RE = re.compile("/home" "/")  # any absolute home path (code files only)
ORG_RE = re.compile("Icaro" "0310")  # personal org/account — allowlisted per line
ORG_ALLOW = "Icaro" "0310/devin-state-pattern"  # this repo's own name
OTHER_RE = re.compile("agent-" "worktrees|personal-" "agent-system")
SECRET_RE = re.compile(
    "cog" "_" "|sk-" "[a-zA-Z0-9]" "|gh" "p_" "|AK" "IA" "|BE" "GIN.*" "PRIV" "ATE"
)

CODE_SUFFIXES = {".py", ".sh", ".tmpl"}


def _iter_repo_files():
    """Yield (relpath, text) for every text file in the repo.

    Binary files and checker files are skipped; .git and caches are pruned.
    """
    for dirpath, dirnames, filenames in os.walk(REPO_ROOT):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            path = Path(dirpath) / name
            rel = path.relative_to(REPO_ROOT).as_posix()
            if rel in CHECKER_FILES:
                continue
            try:
                data = path.read_bytes()
            except OSError:
                continue
            if b"\0" in data[:8192]:  # binary
                continue
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                continue
            yield rel, text


def test_templates_have_todos():
    """Every templates/**/*.tmpl must contain a TODO marker."""
    tmpls = sorted((REPO_ROOT / "templates").rglob("*.tmpl"))
    if not tmpls:
        pytest.skip("no templates/**/*.tmpl present yet")
    missing = [
        t.relative_to(REPO_ROOT).as_posix()
        for t in tmpls
        if "TODO" not in t.read_text(encoding="utf-8", errors="replace")
    ]
    assert not missing, f"templates missing TODO marker: {missing}"


def test_no_personal_paths():
    """No personal paths, org references or upstream repo names."""
    violations = []
    for rel, text in _iter_repo_files():
        suffix = Path(rel).suffix
        for lineno, line in enumerate(text.splitlines(), 1):
            where = f"{rel}:{lineno}"
            if suffix in CODE_SUFFIXES and HOME_RE.search(line):
                violations.append(f"{where}: home-relative path")
            if ORG_RE.search(line) and ORG_ALLOW not in line:
                violations.append(f"{where}: personal org/account reference")
            if OTHER_RE.search(line):
                violations.append(f"{where}: upstream/personal identifier")
    assert not violations, "personal references found:\n" + "\n".join(violations)


def test_no_secrets():
    """No secret-shaped tokens (API keys, PATs, private-key blocks)."""
    violations = []
    for rel, text in _iter_repo_files():
        for lineno, line in enumerate(text.splitlines(), 1):
            if SECRET_RE.search(line):
                violations.append(f"{rel}:{lineno}")
    assert not violations, "secret-shaped tokens found:\n" + "\n".join(violations)


def test_examples_parse():
    """Every examples/*.yaml.example must parse via yaml.safe_load."""
    examples = sorted((REPO_ROOT / "examples").glob("*.yaml.example"))
    assert examples, "no examples/*.yaml.example files found"
    for example in examples:
        doc = yaml.safe_load(example.read_text(encoding="utf-8"))
        assert doc is not None, f"{example.name} parsed to None"


def _load_lib_module(lib_dir: Path, name: str):
    """Import lib/<name>.py directly by path.

    Needed for ``cmd``: CPython ships a stdlib module with the same name and
    pytest/pdb may already have it in ``sys.modules``, so a plain
    ``import cmd`` can resolve to the stdlib module instead of lib/cmd.py.
    Loading by path bypasses ``sys.modules`` entirely.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        f"_dsp_lib_{name}", lib_dir / f"{name}.py"
    )
    assert spec is not None and spec.loader is not None, f"cannot load lib/{name}.py"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_lib_imports(monkeypatch):
    """lib/ must expose the shared helpers checkers rely on."""
    lib_dir = REPO_ROOT / "lib"
    assert lib_dir.is_dir(), "lib/ directory missing"
    monkeypatch.syspath_prepend(str(lib_dir))

    import alert  # noqa: PLC0415 - path is set up inside the test
    import jsonl  # noqa: PLC0415
    import xdg  # noqa: PLC0415

    cmd = _load_lib_module(lib_dir, "cmd")  # stdlib name collision — see helper

    assert callable(getattr(jsonl, "append", None)), "jsonl.append missing"
    assert callable(getattr(cmd, "run", None)), "cmd.run missing"
    assert callable(getattr(alert, "notify", None)), "alert.notify missing"
    assert callable(getattr(xdg, "state_dir", None)), "xdg.state_dir missing"


def test_bootstrap_creates_structure(tmp_path):
    """bootstrap.sh scaffolds dirs, state YAMLs and a git repo."""
    target = tmp_path / "my-ecosystem"
    result = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "bootstrap.sh"), str(target)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    assert (target / "state" / "repos.yaml").is_file()
    for subdir in ("bin", "systemd", "hooks"):
        assert (target / "state" / subdir).is_dir(), f"state/{subdir} missing"
    assert (target / "state" / "bin" / "lib").is_dir()
    assert (target / "logs").is_dir()
    assert (target / "backups").is_dir()
    assert (target / ".git").is_dir()

    # Checker scripts only exist if templates were present at bootstrap time.
    has_templates = any((REPO_ROOT / "templates").rglob("*.tmpl"))
    if has_templates:
        assert list((target / "state" / "bin").glob("*.py")), (
            "templates existed but no .py checkers were produced"
        )


def test_validate_script_passes():
    """scripts/validate.sh must exit 0.

    PATTERN_SKIP_VALIDATE_TEST=1 tells the inner validate run to skip its
    own pytest step — otherwise this test would recurse forever.
    """
    env = dict(os.environ, PATTERN_SKIP_VALIDATE_TEST="1")
    result = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "validate.sh")],
        capture_output=True,
        text=True,
        timeout=300,
        env=env,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stdout + result.stderr
