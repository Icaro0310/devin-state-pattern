#!/usr/bin/env bash
# validate.sh — hygiene checks for the devin-state-pattern repo itself.
#
# Run from anywhere: all paths resolve relative to this script's location,
# then checks execute from the repo root.
#
# Exit 0 = every check passed, 1 = at least one failed.
#
# Checks:
#   a. every templates/**/*.tmpl contains a TODO marker
#   b. no personal paths / personal-org references (allowlist below)
#   c. no secret-shaped tokens anywhere in the repo
#   d. every examples/*.yaml.example parses as YAML
#   e. pytest suite passes — skipped when PATTERN_SKIP_VALIDATE_TEST=1,
#      which tests/test_pattern.py sets to avoid infinite recursion
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$REPO_ROOT"

FAILURES=0

pass() { printf 'PASS  %s\n' "$1"; }
fail() { printf 'FAIL  %s\n' "$1"; FAILURES=$((FAILURES + 1)); }
skip() { printf 'SKIP  %s\n' "$1"; }

# Exclude VCS internals, caches, vendored dirs — and the two checker files
# themselves, which must contain the scan patterns as literals.
EXCLUDES=(
    --exclude-dir=.git
    --exclude-dir=__pycache__
    --exclude-dir=.pytest_cache
    --exclude-dir=node_modules
    --exclude-dir=.venv
    --exclude=validate.sh
    --exclude=test_pattern.py
)

echo "== devin-state-pattern validate =="
echo "repo: $REPO_ROOT"
echo

# --- (a) templates contain TODO markers ------------------------------------
echo "[a] template TODO markers"
tmpl_count=0
tmpl_missing=0
if [ -d templates ]; then
    while IFS= read -r tmpl; do
        tmpl_count=$((tmpl_count + 1))
        if ! grep -q 'TODO' "$tmpl"; then
            printf '     missing TODO: %s\n' "$tmpl"
            tmpl_missing=$((tmpl_missing + 1))
        fi
    done < <(find templates -type f -name '*.tmpl' | sort)
fi
if [ "$tmpl_count" -eq 0 ]; then
    skip "no templates/**/*.tmpl found yet (vacuous pass)"
elif [ "$tmpl_missing" -eq 0 ]; then
    pass "all $tmpl_count template(s) contain TODO"
else
    fail "$tmpl_missing of $tmpl_count template(s) missing TODO"
fi
echo

# --- (b) no personal paths / personal-org references -----------------------
echo "[b] personal paths and org references"
# Patterns are assembled from fragments so this script does not literally
# contain its own match strings — defense in depth on top of --exclude.
PERSONAL_RE="/home""/[a-z]|Icaro""0310|agent-work""trees|personal-agent-""system"
ORG_ALLOW='Icaro0310/devin-state-pattern'   # this repo's own name — never a violation
personal_hits="$(
    grep -rInE "${EXCLUDES[@]}" \
        -e "$PERSONAL_RE" \
        . 2>/dev/null \
    | grep -vF "$ORG_ALLOW" || true
)"
if [ -n "$personal_hits" ]; then
    fail "personal paths or org references found:"
    printf '%s\n' "$personal_hits" | sed 's/^/     /'
else
    pass "no personal paths or org references"
fi
echo

# --- (c) no secret-shaped tokens --------------------------------------------
echo "[c] secret-shaped tokens"
SECRET_RE='cog''_|sk-[a-zA-Z0-9]|gh''p_|AK''IA|BEGIN.*PRIVAT''E'
secret_hits="$(
    grep -rInE "${EXCLUDES[@]}" \
        -e "$SECRET_RE" \
        . 2>/dev/null || true
)"
if [ -n "$secret_hits" ]; then
    fail "secret-shaped tokens found:"
    printf '%s\n' "$secret_hits" | sed 's/^/     /'
else
    pass "no secret-shaped tokens"
fi
echo

# --- (d) examples parse as YAML ----------------------------------------------
echo "[d] examples/*.yaml.example parse"
yaml_count=0
yaml_fail=0
shopt -s nullglob
for example in examples/*.yaml.example; do
    yaml_count=$((yaml_count + 1))
    if python3 -c 'import sys, yaml; yaml.safe_load(open(sys.argv[1], encoding="utf-8"))' "$example"; then
        :
    else
        printf '     YAML parse failed: %s\n' "$example"
        yaml_fail=$((yaml_fail + 1))
    fi
done
if [ "$yaml_count" -eq 0 ]; then
    skip "no examples/*.yaml.example found (vacuous pass)"
elif [ "$yaml_fail" -eq 0 ]; then
    pass "all $yaml_count example file(s) parse"
else
    fail "$yaml_fail of $yaml_count example file(s) failed to parse"
fi
echo

# --- (e) pytest suite ---------------------------------------------------------
echo "[e] pytest suite"
if [ "${PATTERN_SKIP_VALIDATE_TEST:-}" = "1" ]; then
    skip "pytest tests/ -q (PATTERN_SKIP_VALIDATE_TEST=1)"
elif python3 -m pytest tests/ -q; then
    pass "pytest tests/ -q"
else
    fail "pytest tests/ -q"
fi
echo

if [ "$FAILURES" -eq 0 ]; then
    echo "validate: ALL CHECKS PASSED"
    exit 0
fi
echo "validate: $FAILURES check(s) FAILED"
exit 1
