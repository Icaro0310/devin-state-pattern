#!/usr/bin/env bash
# bootstrap.sh — scaffold a new state-pattern ecosystem directory.
#
# Usage: ./bootstrap.sh [target-dir]        (default: ./my-ecosystem)
#
# Works from any cwd — all paths resolve relative to this script's repo.
#
# Creates under <target-dir>:
#   state/{bin,systemd,hooks}/     checker + hook directories
#   state/bin/lib/                 shared library modules
#   logs/  backups/                runtime output + backup dirs
#   state/*.yaml                   from examples/*.yaml.example
#   state/bin/*.py                 from templates/*.tmpl (if present)
#   state/systemd/*                from templates/systemd/*.tmpl (if present)
#   .git                           git init + initial commit
#
# Existing state/*.yaml files are NEVER overwritten — they are user-edited
# declarations. Re-running bootstrap only fills in what is missing.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

TARGET="${1:-./my-ecosystem}"
mkdir -p "$TARGET"
TARGET="$(cd "$TARGET" && pwd)"

if [ "$TARGET" = "$REPO_ROOT" ]; then
    echo "error: refusing to bootstrap into the pattern repo itself ($REPO_ROOT)" >&2
    echo "       pass a different target directory, e.g. ./my-ecosystem" >&2
    exit 1
fi

echo "==> bootstrapping state-pattern ecosystem at: $TARGET"

# --- directory skeleton ---------------------------------------------------
mkdir -p "$TARGET/state/bin/lib" "$TARGET/state/systemd" "$TARGET/state/hooks" \
         "$TARGET/logs" "$TARGET/backups"

# nullglob: unmatched globs expand to nothing instead of a literal pattern.
shopt -s nullglob

# --- state YAMLs from examples/*.yaml.example ------------------------------
# repos.yaml.example -> state/repos.yaml, etc. Existing files are kept so
# re-running bootstrap never clobbers declarations the user already edited.
copied=0
kept=0
for example in "$REPO_ROOT"/examples/*.yaml.example; do
    name="$(basename "$example" .example)"
    dest="$TARGET/state/$name"
    if [ -e "$dest" ]; then
        echo "    keep    state/$name (already exists)"
        kept=$((kept + 1))
    else
        cp "$example" "$dest"
        echo "    create  state/$name"
        copied=$((copied + 1))
    fi
done
echo "==> state YAMLs: $copied created, $kept kept"

# --- checker scripts from templates/*.tmpl (optional) ----------------------
# Templates may not exist yet in a fresh checkout of this pattern — the
# compgen guard makes bootstrap work either way.
if compgen -G "$REPO_ROOT/templates/*.tmpl" > /dev/null; then
    for tmpl in "$REPO_ROOT"/templates/*.tmpl; do
        name="$(basename "$tmpl" .tmpl)"
        cp "$tmpl" "$TARGET/state/bin/$name"
        echo "    create  state/bin/$name (from template)"
    done
else
    echo "==> no templates/*.tmpl found — state/bin gets lib/ only for now"
fi

# --- shared library modules lib/*.py ---------------------------------------
lib_count=0
for libfile in "$REPO_ROOT"/lib/*.py; do
    [ -e "$libfile" ] || continue
    cp "$libfile" "$TARGET/state/bin/lib/"
    lib_count=$((lib_count + 1))
done
echo "==> lib modules copied into state/bin/lib/: $lib_count"

# --- systemd unit templates templates/systemd/*.tmpl ------------------------
if compgen -G "$REPO_ROOT/templates/systemd/*.tmpl" > /dev/null; then
    for tmpl in "$REPO_ROOT"/templates/systemd/*.tmpl; do
        name="$(basename "$tmpl" .tmpl)"
        cp "$tmpl" "$TARGET/state/systemd/$name"
        echo "    create  state/systemd/$name (from template)"
    done
else
    echo "==> no templates/systemd/*.tmpl found — state/systemd left empty"
fi

# --- git init + initial commit ----------------------------------------------
if [ ! -d "$TARGET/.git" ]; then
    # -b main where supported (git >= 2.28); plain init otherwise.
    git -C "$TARGET" init -q -b main 2>/dev/null || git -C "$TARGET" init -q
    echo "==> git repository initialised"
else
    echo "==> existing git repository — history left untouched"
fi

git -C "$TARGET" add -A
if git -C "$TARGET" diff --cached --quiet; then
    echo "==> nothing new to commit"
elif git -C "$TARGET" rev-parse --verify HEAD >/dev/null 2>&1; then
    echo "==> existing history with staged changes — commit them yourself"
else
    git -C "$TARGET" \
        -c user.name="ecosystem-bootstrap" \
        -c user.email="bootstrap@localhost" \
        commit -q -m "chore: bootstrap from devin-state-pattern"
    echo "==> initial commit created"
fi

cat <<'NEXT'

==> next steps:
    1. Edit the declared state — start with:
         state/repos.yaml          which repos exist + hygiene limits
         state/fleet.yaml          pinned tool/package versions
         state/daemons.yaml        scheduled jobs and services
         state/prs.yaml            open-PR policy
         state/dependabot.yaml     bot-PR policy
         state/rules.yaml          compliance rules
         state/reconciliation.yaml reconcile schedule + auto-fix policy
         state/triggers.yaml       tool/trigger manifest
    2. Fill in every TODO marker inside state/bin/*.py and state/systemd/* —
       templates are scaffolds, not finished checkers.
    3. Schedule the reconciler (cron or systemd timer), e.g.:
         0 3 * * *  cd <target-dir> && python3 state/bin/drift_git.py
    4. After changes to THIS repo, run scripts/validate.sh.

NEXT
