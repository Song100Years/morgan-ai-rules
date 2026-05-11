#!/usr/bin/env bash
# test_dogfood_pretooluse.sh - Phase 2c v2 four-verdict dogfood
#
# Verifies the PreToolUse hook end-to-end against an isolated fake
# morgan-ai-rules repo (so we never modify the real claude_md/_global.md).
#
# Verdicts covered:
#   1. routine pass            -> hook exits 0
#   2. structural ceremony     -> hook exits 2 (R18 default-upgrade fallback)
#   3. semantic ceremony       -> hook exits 2 (R16 keyword flag)
#   4. cross-machine drift     -> hook exits 2 (R17 fingerprint mismatch)
#
# Note on case 2 design: we target `decisions/some_unknown.md` rather than
# `claude_md/_global.md` so that the executor role (which the hook
# synthesizes per Q4=A) reaches R18 instead of being stopped earlier by R1
# path permission. Both R1 and R18 would block the same write in production —
# R18 is the dogfood signal we care about for "structural ceremony detection".

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

# Normalize to native form so MSYS does not translate paths inconsistently
# between argv (Windows form) and JSON literal strings (unchanged Bash form).
if command -v cygpath >/dev/null 2>&1; then
    TMPDIR="$(cygpath -m "$TMPDIR_RAW")"
else
    TMPDIR="$TMPDIR_RAW"
fi

# Build an isolated fake morgan-ai-rules repo with origin remote so R17
# git refs are resolvable.
FAKE_ROOT="$TMPDIR/repo"
ORIGIN="$TMPDIR/origin.git"
mkdir -p "$FAKE_ROOT/claude_md" "$FAKE_ROOT/scripts" "$FAKE_ROOT/projects/pattern_trader" "$FAKE_ROOT/decisions"
cp "$REPO_ROOT/scripts/schema_lint.py" "$FAKE_ROOT/scripts/schema_lint.py"
printf '# global v1\n' > "$FAKE_ROOT/claude_md/_global.md"

git init -q "$FAKE_ROOT"
git -C "$FAKE_ROOT" config user.email "dogfood@local"
git -C "$FAKE_ROOT" config user.name "dogfood"
git -C "$FAKE_ROOT" add -A
git -C "$FAKE_ROOT" commit -q -m "init"
git -C "$FAKE_ROOT" branch -M main

git init --bare -q "$ORIGIN"
git -C "$FAKE_ROOT" remote add origin "$ORIGIN"
git -C "$FAKE_ROOT" push -q -u origin main

export MORGAN_AI_RULES_ROOT="$FAKE_ROOT"

run_case() {
    local label="$1"
    local expected_rc="$2"
    local tool_input="$3"

    set +e
    output=$(bash "$HOOK" "Write" "$tool_input" 2>&1)
    rc=$?
    set -e

    if [[ "$rc" -eq "$expected_rc" ]]; then
        echo "PASS  $label (rc=$rc)"
        if [[ -n "$output" ]]; then
            echo "      $(echo "$output" | head -1)"
        fi
        PASSED=$((PASSED + 1))
    else
        echo "FAIL  $label (expected rc=$expected_rc, got rc=$rc)"
        [[ -n "$output" ]] && echo "      output: $output"
        FAILED=$((FAILED + 1))
    fi
}

# ---- Case 1: routine pass ----
INPUT1=$(python3 - <<PY
import json
print(json.dumps({
    "file_path": "$FAKE_ROOT/projects/pattern_trader/notes_daily.md",
    "content": "---\nstatus: current\nvalid_from: 2026-05-11\nowner: morgan\nproject_id: pattern_trader\n---\n# daily note\n\nNothing special.\n",
}))
PY
)
run_case "Case 1: routine daily note -> PASS" 0 "$INPUT1"

# ---- Case 2: structural ceremony (decisions/<unknown>.md + status:current) ----
INPUT2=$(python3 - <<PY
import json
print(json.dumps({
    "file_path": "$FAKE_ROOT/decisions/some_unknown.md",
    "content": "---\nstatus: current\nvalid_from: 2026-05-11\nowner: morgan\nproject_id: ai_governance\n---\n# unknown ceremony\n",
}))
PY
)
run_case "Case 2: structural ceremony (R18 default-upgrade) -> block" 2 "$INPUT2"

# ---- Case 3: semantic ceremony (routine path + rule-language keyword) ----
INPUT3=$(python3 - <<PY
import json
print(json.dumps({
    "file_path": "$FAKE_ROOT/projects/pattern_trader/notes_with_rule_smell.md",
    "content": "---\nstatus: current\nvalid_from: 2026-05-11\nowner: morgan\nproject_id: pattern_trader\n---\n# Notes\n\n以後所有 session 都要先讀 stop_work 才能動工。\n",
}))
PY
)
run_case "Case 3: semantic ceremony (R16 keyword flag) -> block" 2 "$INPUT3"

# ---- Case 4: cross-machine drift (modify _global.md without commit/push) ----
printf '# global v2 LOCAL DRIFT — not pushed to origin\n' > "$FAKE_ROOT/claude_md/_global.md"
INPUT4=$(python3 - <<PY
import json
print(json.dumps({
    "file_path": "$FAKE_ROOT/projects/pattern_trader/notes_after_drift.md",
    "content": "---\nstatus: current\nvalid_from: 2026-05-11\nowner: morgan\nproject_id: pattern_trader\n---\n# anything\n",
}))
PY
)
run_case "Case 4: cross-machine drift (R17 fingerprint) -> block" 2 "$INPUT4"

echo "==================================="
echo "Dogfood results: $PASSED passed, $FAILED failed"
exit $FAILED
