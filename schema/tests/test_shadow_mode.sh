#!/usr/bin/env bash
# test_shadow_mode.sh - Phase 5 shadow mode 5-case dogfood
#
# Covers Phase 5 補4 + 補5 拍板 outcomes:
#   1. enforce + R1 violation      -> exit 2, log unchanged
#   2. shadow  + R1 REJECT         -> log +1, exit 0
#   3. shadow  + R16 NEEDS_HUMAN   -> log +1, exit 0    (補4: 一視同仁)
#   4. shadow  + R17 drift         -> exit 2, log unchanged  (補5 採 A: R17 enforce 後門)
#   5. shadow  + log path unwritable -> fallback exit 2 + stderr (治理底線)
#
# Builds an isolated fake morgan-ai-rules repo so the real claude_md/_global.md
# is never touched.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
HOOK="$REPO_ROOT/hooks/pretooluse_vault_check.sh.template"
PASSED=0
FAILED=0

[[ -r "$HOOK" ]] || { echo "ERROR: hook template not found: $HOOK" >&2; exit 1; }

TMPDIR_RAW="$(mktemp -d)"
cleanup() { rm -rf "$TMPDIR_RAW"; }
trap cleanup EXIT

if command -v cygpath >/dev/null 2>&1; then
    TMPDIR="$(cygpath -m "$TMPDIR_RAW")"
else
    TMPDIR="$TMPDIR_RAW"
fi

FAKE_ROOT="$TMPDIR/repo"
ORIGIN="$TMPDIR/origin.git"
LOG_DIR="$TMPDIR/logs"
LOG_PATH="$LOG_DIR/shadow.jsonl"

mkdir -p "$FAKE_ROOT/claude_md" "$FAKE_ROOT/scripts" \
         "$FAKE_ROOT/projects/pattern_trader" "$FAKE_ROOT/decisions" \
         "$FAKE_ROOT/00-Morgan"
cp "$REPO_ROOT/scripts/schema_lint.py" "$FAKE_ROOT/scripts/schema_lint.py"
printf '# global v1\n' > "$FAKE_ROOT/claude_md/_global.md"

git init -q "$FAKE_ROOT"
git -C "$FAKE_ROOT" config user.email "shadow-dogfood@local"
git -C "$FAKE_ROOT" config user.name "shadow-dogfood"
git -C "$FAKE_ROOT" add -A
git -C "$FAKE_ROOT" commit -q -m "init"
git -C "$FAKE_ROOT" branch -M main

git init --bare -q "$ORIGIN"
git -C "$FAKE_ROOT" remote add origin "$ORIGIN"
git -C "$FAKE_ROOT" push -q -u origin main

export MORGAN_AI_RULES_ROOT="$FAKE_ROOT"
export VAULT_SHADOW_LOG_PATH="$LOG_PATH"

count_log_lines() {
    [[ -f "$LOG_PATH" ]] || { echo 0; return; }
    wc -l < "$LOG_PATH" | tr -d ' \r\n'
}

run_case() {
    local label="$1"
    local expected_rc="$2"
    local expected_delta="$3"
    local tool_input="$4"

    local before after delta rc output
    before=$(count_log_lines)

    set +e
    output=$(bash "$HOOK" "Write" "$tool_input" 2>&1)
    rc=$?
    set -e

    after=$(count_log_lines)
    delta=$((after - before))

    if [[ "$rc" -eq "$expected_rc" && "$delta" -eq "$expected_delta" ]]; then
        echo "PASS  $label (rc=$rc, log_delta=$delta)"
        [[ -n "$output" ]] && echo "      $(echo "$output" | head -1)"
        PASSED=$((PASSED + 1))
    else
        echo "FAIL  $label (expected rc=$expected_rc log_delta=$expected_delta, got rc=$rc log_delta=$delta)"
        [[ -n "$output" ]] && echo "      output: $output"
        FAILED=$((FAILED + 1))
    fi
}

# ---- Payloads ----

PAYLOAD_R1=$(python3 - <<PY
import json
print(json.dumps({
    "file_path": "$FAKE_ROOT/00-Morgan/morgan_only.md",
    "content": "---\nstatus: current\nvalid_from: 2026-05-12\nowner: morgan\nproject_id: ai_governance\n---\n# morgan-only zone\n",
}))
PY
)

PAYLOAD_R16=$(python3 - <<PY
import json
print(json.dumps({
    "file_path": "$FAKE_ROOT/projects/pattern_trader/rule_smell.md",
    "content": "---\nstatus: current\nvalid_from: 2026-05-12\nowner: morgan\nproject_id: pattern_trader\n---\n# notes\n\n以後所有 session 必須先讀 stop_work 才能動工。\n",
}))
PY
)

# ---- Case 1: enforce + R1 -> block, no log ----
unset VAULT_GOVERNANCE_MODE
run_case "Case 1: enforce + R1 -> block (no log)" 2 0 "$PAYLOAD_R1"

# ---- Case 2: shadow + R1 REJECT -> log + exit 0 ----
export VAULT_GOVERNANCE_MODE=shadow
run_case "Case 2: shadow + R1 REJECT -> log + exit 0" 0 1 "$PAYLOAD_R1"

# ---- Case 3: shadow + R16 NEEDS_HUMAN -> log + exit 0 (補4) ----
run_case "Case 3: shadow + R16 NEEDS_HUMAN -> log + exit 0 (補4)" 0 1 "$PAYLOAD_R16"

# ---- Case 4: shadow + R17 drift -> enforce 後門 (補5 採 A) ----
printf '# global v2 LOCAL DRIFT — not pushed to origin\n' > "$FAKE_ROOT/claude_md/_global.md"
PAYLOAD_R17=$(python3 - <<PY
import json
print(json.dumps({
    "file_path": "$FAKE_ROOT/projects/pattern_trader/after_drift.md",
    "content": "---\nstatus: current\nvalid_from: 2026-05-12\nowner: morgan\nproject_id: pattern_trader\n---\n# anything\n",
}))
PY
)
run_case "Case 4: shadow + R17 drift -> enforce 後門 (no log)" 2 0 "$PAYLOAD_R17"

# Restore _global.md so Case 5 does not also hit R17 first
printf '# global v1\n' > "$FAKE_ROOT/claude_md/_global.md"

# ---- Case 5: shadow + log path unwritable -> fallback exit 2 ----
# Trick: point log path under a file (not a dir), so mkdir(parent) fails with
# FileExistsError on every OS. Use $TMPDIR (cygpath-normalized) so Python sees
# the same path as Bash — using $(mktemp) directly returns a POSIX /tmp/... form
# that Python on Windows would silently rewrite to a different (writable) dir.
BAD_PARENT="$TMPDIR/bad_parent_file"
touch "$BAD_PARENT"
export VAULT_SHADOW_LOG_PATH="$BAD_PARENT/cannot_create.jsonl"

set +e
output=$(bash "$HOOK" "Write" "$PAYLOAD_R1" 2>&1)
rc=$?
set -e

if [[ "$rc" -eq 2 ]] && echo "$output" | grep -q "shadow log write failed"; then
    echo "PASS  Case 5: shadow + log unwritable -> fallback exit 2 + stderr"
    PASSED=$((PASSED + 1))
else
    echo "FAIL  Case 5: expected rc=2 + 'shadow log write failed' stderr, got rc=$rc"
    [[ -n "$output" ]] && echo "      output: $output"
    FAILED=$((FAILED + 1))
fi
rm -f "$BAD_PARENT"
export VAULT_SHADOW_LOG_PATH="$LOG_PATH"

echo "==================================="
echo "Shadow dogfood: $PASSED passed, $FAILED failed"
exit $FAILED
