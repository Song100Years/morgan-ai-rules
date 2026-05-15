#!/usr/bin/env bash
# install_posttooluse_hook.sh - Phase 5.5 cross-machine PostToolUse hook installer
#
# Installs:
#   ~/.claude/hooks/posttooluse_vault_revert.sh   <- copied from hooks/<template>
#   ~/.claude/settings.json                       <- merges PostToolUse entry (idempotent)
#
# This hook is the Phase 5.5 physical enforcement layer.
# PreToolUse v2 prints advisory REJECT; PostToolUse v5.5 reverts the bad
# write via git checkout / quarantine after Claude Code wrote it.
#
# Prerequisite
#   bash scripts/init_vault_tracking.sh   # one-time baseline init per machine
#
# Cross-platform: Windows (Git Bash) + Linux (VPS). No sudo required.
# Idempotent. Safe to re-run.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TEMPLATE="$REPO_ROOT/hooks/posttooluse_vault_revert.sh.template"
HOOK_DIR="$HOME/.claude/hooks"
HOOK_DEST="$HOOK_DIR/posttooluse_vault_revert.sh"
SETTINGS="$HOME/.claude/settings.json"

for tool in bash python3 git; do
  command -v "$tool" >/dev/null 2>&1 || { echo "ERROR: required tool missing: $tool" >&2; exit 1; }
done

[[ -r "$TEMPLATE" ]] || { echo "ERROR: template not found: $TEMPLATE" >&2; exit 1; }
[[ -r "$REPO_ROOT/scripts/schema_lint.py" ]] || { echo "ERROR: schema_lint.py not found: $REPO_ROOT/scripts/" >&2; exit 1; }

mkdir -p "$HOOK_DIR"
cp "$TEMPLATE" "$HOOK_DEST"
chmod +x "$HOOK_DEST"
echo "[install] hook script -> $HOOK_DEST"

python3 - "$SETTINGS" <<'PY'
import json, sys, pathlib
sp = pathlib.Path(sys.argv[1])
sp.parent.mkdir(parents=True, exist_ok=True)
if sp.exists():
    try:
        settings = json.loads(sp.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"ERROR: settings.json malformed JSON: {e}", file=sys.stderr)
        sys.exit(1)
else:
    settings = {}

command = (
    'bash ~/.claude/hooks/posttooluse_vault_revert.sh'
)
matcher = "Write|Edit"
fingerprint = "posttooluse_vault_revert.sh"

hooks_root = settings.setdefault("hooks", {})
post = hooks_root.setdefault("PostToolUse", [])

target_block = None
for block in post:
    if block.get("matcher") == matcher:
        target_block = block
        break
if target_block is None:
    target_block = {"matcher": matcher, "hooks": []}
    post.append(target_block)

existing = target_block.setdefault("hooks", [])
already = any(fingerprint in h.get("command", "") for h in existing)
if already:
    print("[install] settings.json: PostToolUse entry already present (idempotent skip)")
else:
    existing.append({"type": "command", "command": command})
    sp.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print("[install] settings.json: PostToolUse entry merged")
PY

# Sanity check: warn if init_vault_tracking has not been run yet on this
# machine — hook will fail-open until baseline exists.
TRACKING_HINTS=("/d/vault-tracking/.git" "/e/vault-tracking/.git" "$HOME/vault-tracking/.git")
FOUND=""
for h in "${TRACKING_HINTS[@]}"; do
  if [[ -d "$h" ]]; then
    FOUND="$h"
    break
  fi
done

if [[ -z "$FOUND" ]]; then
  cat <<'WARN'
[install] WARNING: no vault tracking .git found yet.
          Run `bash scripts/init_vault_tracking.sh` BEFORE the hook can revert.
          Until then the hook logs "NO_TRACKING" and exits 0 (fail-open).
WARN
else
  echo "[install] vault tracking detected at $FOUND"
fi

cat <<'MSG'
[install] done.

Next steps:
  1. If you have not done so, run scripts/init_vault_tracking.sh (one-time
     per machine; safe to re-run as a no-op).
  2. Restart Claude Code session so settings.json reloads.
  3. PostToolUse hook writes to ~/.claude/logs/vault_governance_revert.jsonl.
  4. Read 99-system/AI_Governance/HOOK_HARDENING_GUIDE.md for full context.
MSG
