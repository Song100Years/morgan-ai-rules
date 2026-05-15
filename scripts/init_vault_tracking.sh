#!/usr/bin/env bash
# init_vault_tracking.sh - Phase 5.5 vault-tracking git init helper
#
# Initialises an external --git-dir (NOT inside Vault) so the Phase 5.5
# PostToolUse hook can `git checkout HEAD -- <file>` to revert violations.
#
# Why external --git-dir
#   Putting .git inside D:/OneDrive/VPS-Obsidian/ caused 299 conflict files
#   (per memory reference_vault_sync_topology.md 2026-05-13). Keep .git out
#   of any OneDrive-synced path.
#
# Usage
#   bash scripts/init_vault_tracking.sh
#     -> tries to auto-detect Vault root (D:/E: OneDrive/VPS-Obsidian)
#     -> writes baseline commit at $VAULT_TRACKING_GIT_DIR (default D:/vault-tracking/.git)
#
# Env overrides
#   VAULT_ROOT             — explicit vault path
#   VAULT_TRACKING_GIT_DIR — explicit external --git-dir
#
# Re-run safety
#   Refuses to re-init if VAULT_TRACKING_GIT_DIR already has refs.

set -euo pipefail

# Auto-detect Vault root.
VAULT_ROOT="${VAULT_ROOT:-}"
if [[ -z "$VAULT_ROOT" ]]; then
  for cand in "/d/OneDrive/VPS-Obsidian" "/e/OneDrive/VPS-Obsidian"; do
    if [[ -d "$cand" ]]; then
      VAULT_ROOT="$cand"
      break
    fi
  done
fi
if [[ -z "$VAULT_ROOT" || ! -d "$VAULT_ROOT" ]]; then
  echo "ERROR: cannot find vault root (set VAULT_ROOT=...)" >&2
  exit 1
fi

# Choose tracking dir on the same drive as the vault (so paths align with
# the hook auto-detect logic) but outside the OneDrive subtree.
if [[ -z "${VAULT_TRACKING_GIT_DIR:-}" ]]; then
  case "$VAULT_ROOT" in
    /d/*) VAULT_TRACKING_GIT_DIR="/d/vault-tracking/.git" ;;
    /e/*) VAULT_TRACKING_GIT_DIR="/e/vault-tracking/.git" ;;
    *)    VAULT_TRACKING_GIT_DIR="$HOME/vault-tracking/.git" ;;
  esac
fi

# Safety: make sure tracking dir is NOT inside any OneDrive path.
case "$VAULT_TRACKING_GIT_DIR" in
  */OneDrive/*)
    echo "ERROR: VAULT_TRACKING_GIT_DIR is inside OneDrive ($VAULT_TRACKING_GIT_DIR)" >&2
    echo "       That recreates the 2026-05-13 .git conflict disaster. Aborting." >&2
    exit 1
    ;;
esac

TRACKING_PARENT="$(dirname "$VAULT_TRACKING_GIT_DIR")"

if [[ -d "$VAULT_TRACKING_GIT_DIR/refs/heads" ]] && \
   git --git-dir="$VAULT_TRACKING_GIT_DIR" --work-tree="$VAULT_ROOT" rev-parse HEAD >/dev/null 2>&1; then
  echo "Vault tracking already initialised at $VAULT_TRACKING_GIT_DIR"
  echo "HEAD: $(git --git-dir="$VAULT_TRACKING_GIT_DIR" --work-tree="$VAULT_ROOT" rev-parse --short HEAD)"
  exit 0
fi

echo "Initialising vault tracking:"
echo "  vault root  : $VAULT_ROOT"
echo "  git dir     : $VAULT_TRACKING_GIT_DIR"
echo "  quarantine  : $TRACKING_PARENT/quarantine"

mkdir -p "$VAULT_TRACKING_GIT_DIR"
mkdir -p "$TRACKING_PARENT/quarantine"

git --git-dir="$VAULT_TRACKING_GIT_DIR" --work-tree="$VAULT_ROOT" init -q -b main
git --git-dir="$VAULT_TRACKING_GIT_DIR" --work-tree="$VAULT_ROOT" \
    config user.name "ai-governance-baseline"
git --git-dir="$VAULT_TRACKING_GIT_DIR" --work-tree="$VAULT_ROOT" \
    config user.email "baseline@local"

# .gitignore lives in the vault so OneDrive replicates it across machines.
# Keep it minimal — we exclude things Obsidian / OS noise that don't belong
# in governance baseline (and would explode commit size).
GITIGNORE="$VAULT_ROOT/.gitignore"
if [[ ! -f "$GITIGNORE" ]]; then
  cat > "$GITIGNORE" <<'GI'
# Phase 5.5 vault-tracking ignore list
# OneDrive / OS noise
.tmp.driveupload
Thumbs.db
desktop.ini
.DS_Store
# Obsidian workspace / cache
.obsidian/workspace.json
.obsidian/workspace-mobile.json
.obsidian/cache
.trash/
# Stale Syncthing artifacts
.stfolder/
.stversions-*/
GI
fi

echo "Staging baseline (may take a few minutes for full vault)..."
git --git-dir="$VAULT_TRACKING_GIT_DIR" --work-tree="$VAULT_ROOT" add -A

# Skip commit if nothing staged (unlikely but defensive).
if git --git-dir="$VAULT_TRACKING_GIT_DIR" --work-tree="$VAULT_ROOT" diff --cached --quiet; then
  echo "WARN: nothing to commit — vault appears empty?" >&2
  exit 1
fi

git --git-dir="$VAULT_TRACKING_GIT_DIR" --work-tree="$VAULT_ROOT" \
    commit -q -m "v2.2 Phase 5.5 baseline: $(date -u +%Y-%m-%dT%H:%M:%SZ)"

HEAD_SHA=$(git --git-dir="$VAULT_TRACKING_GIT_DIR" --work-tree="$VAULT_ROOT" rev-parse --short HEAD)
FILE_COUNT=$(git --git-dir="$VAULT_TRACKING_GIT_DIR" --work-tree="$VAULT_ROOT" ls-files | wc -l)

echo ""
echo "Vault tracking baseline created."
echo "  HEAD       : $HEAD_SHA"
echo "  files      : $FILE_COUNT"
echo ""
echo "Next: install the PostToolUse hook (scripts/install_posttooluse_hook.sh)."
