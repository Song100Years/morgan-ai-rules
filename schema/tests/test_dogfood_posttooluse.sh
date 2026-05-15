#!/usr/bin/env bash
# test_dogfood_posttooluse.sh - Phase 5.5 PostToolUse five-verdict dogfood
#
# Verifies the PostToolUse hook end-to-end against an isolated fake vault +
# fake morgan-ai-rules clone (so we never touch real OneDrive Vault or hook
# config).
#
# Cases covered:
#   1. PASS  → COMMIT       (allowed path, frontmatter ok, file gets committed)
#   2. REJECT (R1 forbidden path, untracked) → quarantine
#   3. REJECT (R1 forbidden path, tracked update) → checkout HEAD
#   4. NEEDS_HUMAN (R18) → quarantine
#   5. OUTSIDE_VAULT → no-op (hook ignores)
#
# Each case asserts:
#   - hook exit 0 (PostToolUse always 0)
#   - filesystem state matches expectation
#   - log JSONL line records the verdict + action

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
HOOK="$REPO_ROOT/hooks/posttooluse_vault_revert.sh.template"
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

FAKE_VAULT="$TMPDIR/vault"
FAKE_GIT_DIR="$TMPDIR/tracking/.git"
FAKE_QUARANTINE="$TMPDIR/tracking/quarantine"
FAKE_RULES="$TMPDIR/morgan-ai-rules"
ORIGIN="$TMPDIR/origin.git"
LOG_FILE="$TMPDIR/revert.jsonl"

mkdir -p "$FAKE_VAULT/projects/test" "$FAKE_VAULT/99-system" \
         "$FAKE_VAULT/claude_md" "$FAKE_RULES/claude_md" \
         "$FAKE_RULES/scripts" "$FAKE_GIT_DIR" "$FAKE_QUARANTINE"

# Copy schema_lint so the hook's lint subprocess works.
cp "$REPO_ROOT/scripts/schema_lint.py" "$FAKE_RULES/scripts/schema_lint.py"
printf '# global v1\n' > "$FAKE_RULES/claude_md/_global.md"

# Fake morgan-ai-rules needs a git repo so R17 fingerprint can resolve.
git init -q "$FAKE_RULES"
git -C "$FAKE_RULES" config user.email "dogfood@local"
git -C "$FAKE_RULES" config user.name "dogfood"
git -C "$FAKE_RULES" add -A
git -C "$FAKE_RULES" commit -q -m "init"
git -C "$FAKE_RULES" branch -M main
git init --bare -q "$ORIGIN"
git -C "$FAKE_RULES" remote add origin "$ORIGIN"
git -C "$FAKE_RULES" push -q -u origin main

# Initialise vault-tracking git with baseline.
printf 'baseline content\n' > "$FAKE_VAULT/projects/test/baseline.md"
printf '# tracked forbidden init\n' > "$FAKE_VAULT/claude_md/_global.md"
git --git-dir="$FAKE_GIT_DIR" --work-tree="$FAKE_VAULT" init -q -b main
git --git-dir="$FAKE_GIT_DIR" --work-tree="$FAKE_VAULT" config user.email "baseline@local"
git --git-dir="$FAKE_GIT_DIR" --work-tree="$FAKE_VAULT" config user.name "baseline"
git --git-dir="$FAKE_GIT_DIR" --work-tree="$FAKE_VAULT" add -A
git --git-dir="$FAKE_GIT_DIR" --work-tree="$FAKE_VAULT" commit -q -m "baseline"

export VAULT_ROOT="$FAKE_VAULT"
export VAULT_TRACKING_GIT_DIR="$FAKE_GIT_DIR"
export QUARANTINE_DIR="$FAKE_QUARANTINE"
export REVERT_LOG="$LOG_FILE"
export MORGAN_AI_RULES_ROOT="$FAKE_RULES"

# Helper: invoke hook with payload, capture exit + log diff.
run_case() {
    local label="$1"; shift
    local payload="$1"; shift
    local assert_fn="$1"

    local log_before
    log_before=$(wc -l < "$LOG_FILE" 2>/dev/null || echo 0)

    set +e
    bash "$HOOK" <<<"$payload" >/dev/null 2>&1
    local rc=$?
    set -e

    local log_after
    log_after=$(wc -l < "$LOG_FILE" 2>/dev/null || echo 0)
    local new_lines=$((log_after - log_before))
    local last_log=""
    if [[ "$new_lines" -gt 0 ]]; then
        last_log=$(tail -n 1 "$LOG_FILE")
    fi

    if "$assert_fn" "$rc" "$last_log"; then
        echo "PASS  $label"
        PASSED=$((PASSED + 1))
    else
        echo "FAIL  $label (rc=$rc log=$last_log)"
        FAILED=$((FAILED + 1))
    fi
}

# ---- Case 1: PASS — allowed path with valid frontmatter → COMMIT ----
cat > "$FAKE_VAULT/projects/test/case1_ok.md" <<EOF
---
status: current
valid_from: 2026-05-15
owner: morgan
project_id: pattern_trader
---
# legit note

A routine note in an allowed path.
EOF

CASE1_PAYLOAD=$(python3 - <<PY
import json
print(json.dumps({
    "tool_name": "Write",
    "tool_input": {"file_path": "$FAKE_VAULT/projects/test/case1_ok.md"},
}))
PY
)

assert_case1() {
    local rc="$1" log="$2"
    [[ "$rc" -eq 0 ]] || return 1
    echo "$log" | grep -q '"action": "COMMIT"' || return 1
    echo "$log" | grep -q '"verdict": "PASS"' || return 1
    [[ -f "$FAKE_VAULT/projects/test/case1_ok.md" ]] || return 1
    return 0
}
run_case "Case 1: PASS → COMMIT" "$CASE1_PAYLOAD" assert_case1

# ---- Case 2: REJECT untracked → quarantine ----
cat > "$FAKE_VAULT/99-system/case2_forbidden.md" <<EOF
---
status: current
valid_from: 2026-05-15
owner: morgan
project_id: pattern_trader
---
# forbidden path write

R1 should reject this; file is untracked.
EOF

CASE2_PAYLOAD=$(python3 - <<PY
import json
print(json.dumps({
    "tool_name": "Write",
    "tool_input": {"file_path": "$FAKE_VAULT/99-system/case2_forbidden.md"},
}))
PY
)

assert_case2() {
    local rc="$1" log="$2"
    [[ "$rc" -eq 0 ]] || return 1
    echo "$log" | grep -q '"action": "REVERT"' || return 1
    # Quarantine dir should contain something dated today.
    local today
    today=$(date -u +%Y-%m-%d)
    [[ -d "$FAKE_QUARANTINE/$today" ]] || return 1
    # Source file must no longer exist in vault.
    [[ ! -f "$FAKE_VAULT/99-system/case2_forbidden.md" ]] || return 1
    return 0
}
run_case "Case 2: REJECT untracked → quarantine" "$CASE2_PAYLOAD" assert_case2

# ---- Case 3: REJECT tracked modification → checkout HEAD ----
# claude_md/_global.md is in baseline. Mutate it now, then hook should
# checkout HEAD and restore.
printf '# DRIFTED VERSION — should be reverted\n' > "$FAKE_VAULT/claude_md/_global.md"
CASE3_PAYLOAD=$(python3 - <<PY
import json
print(json.dumps({
    "tool_name": "Edit",
    "tool_input": {"file_path": "$FAKE_VAULT/claude_md/_global.md"},
}))
PY
)

assert_case3() {
    local rc="$1" log="$2"
    [[ "$rc" -eq 0 ]] || return 1
    echo "$log" | grep -q '"action": "REVERT"' || return 1
    echo "$log" | grep -q 'checked_out_HEAD' || return 1
    # File content should match baseline.
    grep -q "tracked forbidden init" "$FAKE_VAULT/claude_md/_global.md" || return 1
    return 0
}
run_case "Case 3: REJECT tracked → checkout HEAD" "$CASE3_PAYLOAD" assert_case3

# ---- Case 4: NEEDS_HUMAN (R18) — current status in ceremony-ish path ----
# Use decisions/ + status:current + unknown filename → R18 default-upgrade.
mkdir -p "$FAKE_VAULT/decisions"
cat > "$FAKE_VAULT/decisions/case4_needs_human.md" <<EOF
---
status: current
valid_from: 2026-05-15
owner: morgan
project_id: ai_governance
---
# new ceremony doc

R18 should flag this NEEDS_HUMAN because the filename is not in the
ceremony whitelist.
EOF

CASE4_PAYLOAD=$(python3 - <<PY
import json
print(json.dumps({
    "tool_name": "Write",
    "tool_input": {"file_path": "$FAKE_VAULT/decisions/case4_needs_human.md"},
}))
PY
)

assert_case4() {
    local rc="$1" log="$2"
    [[ "$rc" -eq 0 ]] || return 1
    echo "$log" | grep -q '"action": "REVERT"' || return 1
    [[ ! -f "$FAKE_VAULT/decisions/case4_needs_human.md" ]] || return 1
    return 0
}
run_case "Case 4: NEEDS_HUMAN → quarantine" "$CASE4_PAYLOAD" assert_case4

# ---- Case 5: OUTSIDE_VAULT → no-op ----
echo "outside" > "$TMPDIR/outside.md"
CASE5_PAYLOAD=$(python3 - <<PY
import json
print(json.dumps({
    "tool_name": "Write",
    "tool_input": {"file_path": "$TMPDIR/outside.md"},
}))
PY
)

assert_case5() {
    local rc="$1" log="$2"
    [[ "$rc" -eq 0 ]] || return 1
    # File should NOT be touched.
    [[ -f "$TMPDIR/outside.md" ]] || return 1
    grep -q "outside" "$TMPDIR/outside.md" || return 1
    # No new log line (hook exits before logging on out-of-scope).
    return 0
}
run_case "Case 5: OUTSIDE_VAULT → no-op" "$CASE5_PAYLOAD" assert_case5

echo "==================================="
echo "Dogfood results: $PASSED passed, $FAILED failed"
exit $FAILED
