#!/usr/bin/env bash
# install_pretooluse_hook.sh - Phase 2c v2 cross-machine PreToolUse hook installer
#
# Installs:
#   ~/.claude/hooks/pretooluse_vault_check.sh   <- copied from hooks/<template>
#   ~/.claude/settings.json                     <- merges PreToolUse entry (idempotent)
#
# Cross-platform support:
#   - Windows (Home / Office / NB): run from Git Bash (HOME -> /c/users/<name>)
#   - Linux (VPS): standard $HOME
#
# Idempotent: safe to re-run; skips entry insertion if already present.
# No sudo required. Does not touch any other ~/.claude/ files.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TEMPLATE="$REPO_ROOT/hooks/pretooluse_vault_check.sh.template"
HOOK_DIR="$HOME/.claude/hooks"
HOOK_DEST="$HOOK_DIR/pretooluse_vault_check.sh"
SETTINGS="$HOME/.claude/settings.json"

for tool in bash python3; do
  command -v "$tool" >/dev/null 2>&1 || { echo "ERROR: required tool missing: $tool" >&2; exit 1; }
done

[[ -r "$TEMPLATE" ]] || { echo "ERROR: template not found: $TEMPLATE" >&2; exit 1; }
[[ -r "$REPO_ROOT/scripts/schema_lint.py" ]] || { echo "ERROR: schema_lint.py not found in repo: $REPO_ROOT/scripts/" >&2; exit 1; }

# schema_lint imports yaml; without it the hook silently fails because
# schema_lint crashes on import before producing any verdict JSON.
# Auto-install via pip --user (no sudo). Set INSTALL_HOOK_SKIP_PYYAML=1 to
# bypass (e.g. when the host uses a system-managed PyYAML package).
if [[ "${INSTALL_HOOK_SKIP_PYYAML:-0}" != "1" ]]; then
    if ! python3 -c "import yaml" >/dev/null 2>&1; then
        echo "[install] PyYAML missing; schema_lint cannot parse frontmatter without it."
        echo "[install] running: python3 -m pip install --user --quiet pyyaml"
        if python3 -m pip install --user --quiet pyyaml; then
            if python3 -c "import yaml" >/dev/null 2>&1; then
                yaml_ver=$(python3 -c "import yaml; print(yaml.__version__)" 2>/dev/null)
                echo "[install] PyYAML ${yaml_ver} installed."
            else
                echo "ERROR: pip reported success but yaml still un-importable; check python paths" >&2
                exit 1
            fi
        else
            echo "ERROR: pyyaml auto-install failed. Run manually then re-run installer:" >&2
            echo "  python3 -m pip install --user pyyaml" >&2
            echo "On distros that block pip user-installs (PEP 668), use the system package:" >&2
            echo "  sudo apt install python3-yaml   # Debian / Ubuntu" >&2
            exit 1
        fi
    else
        yaml_ver=$(python3 -c "import yaml; print(yaml.__version__)" 2>/dev/null)
        echo "[install] PyYAML ${yaml_ver} present."
    fi
fi

mkdir -p "$HOOK_DIR"
cp "$TEMPLATE" "$HOOK_DEST"
chmod +x "$HOOK_DEST"
echo "[install] hook script -> $HOOK_DEST"

python3 - "$SETTINGS" "$REPO_ROOT" <<'PY'
import json, sys, pathlib
settings_path, repo_root = sys.argv[1], sys.argv[2]
sp = pathlib.Path(settings_path)
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
    'bash ~/.claude/hooks/pretooluse_vault_check.sh '
    '"$CLAUDE_TOOL_NAME" "$CLAUDE_TOOL_INPUT"'
)
matcher = "Write|Edit"
fingerprint = "pretooluse_vault_check.sh"

hooks_root = settings.setdefault("hooks", {})
pre = hooks_root.setdefault("PreToolUse", [])

target_block = None
for block in pre:
    if block.get("matcher") == matcher:
        target_block = block
        break
if target_block is None:
    target_block = {"matcher": matcher, "hooks": []}
    pre.append(target_block)

existing = target_block.setdefault("hooks", [])
already = any(fingerprint in h.get("command", "") for h in existing)
if already:
    print("[install] settings.json: PreToolUse entry already present (idempotent skip)")
else:
    existing.append({"type": "command", "command": command})
    sp.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print("[install] settings.json: PreToolUse entry merged")

print(f"[install] morgan-ai-rules root recorded: {repo_root}")
PY

cat <<'MSG'
[install] done.

Next steps:
  1. Restart Claude Code session so settings.json reloads.
  2. To force a specific morgan-ai-rules clone path, export
     MORGAN_AI_RULES_ROOT before launching Claude Code.
  3. Smoke test by triggering a Write tool on a vault path; the hook
     prints [VAULT-CHECK] when it intervenes.
MSG
