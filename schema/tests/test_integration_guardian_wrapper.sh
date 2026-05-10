#!/usr/bin/env bash
# Integration test: schema_lint -> guardian-wrapper pipeline (Phase 2b).
#
# Cases (per Phase 2b spec):
#   1. lint PASS         -> wrapper invoked      -> mock guardian PASS
#   2. lint REJECT       -> wrapper NOT invoked  -> lint REJECT forwarded
#   3. lint NEEDS_HUMAN  -> wrapper invoked      -> mock guardian propagates
#   4. wrapper drift     -> GUARDIAN_UNAVAILABLE
#
# Run:
#   bash schema/tests/test_integration_guardian_wrapper.sh
#
# Exit: 0 if all cases pass.

set -euo pipefail
export PYTHONIOENCODING=utf-8

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SCHEMA_LINT="$REPO_ROOT/scripts/schema_lint.py"
WRAPPER="$REPO_ROOT/scripts/guardian-wrapper.sh"
GUARDIAN_REF="$REPO_ROOT/agents/guardian.md"

# Prefer venv python (PyYAML installed there); fall back to system.
if [[ -x "$REPO_ROOT/.venv/Scripts/python.exe" ]]; then
    PYTHON_BIN="$REPO_ROOT/.venv/Scripts/python.exe"
elif [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then
    PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
else
    PYTHON_BIN="${PYTHON_BIN:-python3}"
fi

for path in "$SCHEMA_LINT" "$WRAPPER" "$GUARDIAN_REF"; do
    if [[ ! -r "$path" ]]; then
        echo "ERROR: missing $path" >&2
        exit 2
    fi
done

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

pass_count=0
fail_count=0
total_count=0

assert_eq() {
    local label="$1" expected="$2" actual="$3"
    if [[ "$expected" == "$actual" ]]; then
        echo "  OK  $label = $actual"
        return 0
    fi
    echo "  FAIL $label: expected '$expected' got '$actual'" >&2
    return 1
}

json_get() {
    "$PYTHON_BIN" -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception as e:
    sys.stderr.write(f"json_get: not JSON: {e}\n")
    sys.exit(1)
print(d.get(sys.argv[1], ""))
' "$1"
}

# orchestrate: shared schema_lint -> wrapper pipeline.
# stdin : write request JSON
# arg1  : optional wrapper path override (default $WRAPPER)
# stdout: final JSON (lint REJECT, or wrapper output)
# return: lint REJECT -> 1; else wrapper exit code.
orchestrate() {
    local wrapper="${1:-$WRAPPER}"
    local input lint_out lint_rc lint_verdict
    input=$(cat)
    set +e
    lint_out=$("$PYTHON_BIN" "$SCHEMA_LINT" <<<"$input")
    lint_rc=$?
    set -e
    lint_verdict=$(printf '%s' "$lint_out" | "$PYTHON_BIN" -c \
        'import json,sys; print(json.load(sys.stdin).get("verdict",""))')
    case "$lint_verdict" in
        REJECT)
            printf '%s\n' "$lint_out"
            return 1
            ;;
        PASS|NEEDS_HUMAN)
            local wrapper_input
            wrapper_input=$("$PYTHON_BIN" -c '
import json, sys
req = json.loads(sys.argv[1])
lint = json.loads(sys.argv[2])
req["schema_lint_flags"] = lint.get("flags", [])
req["schema_lint_verdict"] = lint.get("verdict")
print(json.dumps(req))
' "$input" "$lint_out")
            set +e
            printf '%s' "$wrapper_input" | bash "$wrapper"
            local wrapper_rc=$?
            set -e
            return $wrapper_rc
            ;;
        *)
            echo "ERROR: unexpected lint verdict: $lint_verdict (rc=$lint_rc)" >&2
            return 99
            ;;
    esac
}

run_case() {
    local label="$1"; shift
    total_count=$((total_count + 1))
    echo "=== $label ==="
    if "$@"; then
        pass_count=$((pass_count + 1))
        echo "PASS: $label"
    else
        fail_count=$((fail_count + 1))
        echo "FAIL: $label" >&2
    fi
    echo
}

PASS_INPUT='{"writer_role":"executor","writer_engine":"claude","target_path":"projects/pattern_trader/notes/x.md","operation":"create","content":"---\nstatus: current\nvalid_from: 2026-05-10\nowner: morgan\nproject_id: pattern_trader\n---\nbody"}'

# --- Case 1: lint PASS -> wrapper PASS ---
case1() {
    set +e
    GUARDIAN_PROMPT_PATH="$GUARDIAN_REF" \
    GUARDIAN_REF_PATH="$GUARDIAN_REF" \
    GUARDIAN_LLM_MODE=stub_pass \
        orchestrate <<<"$PASS_INPUT" > "$tmp/case1.out"
    local rc=$?
    set -e
    local verdict
    verdict=$(json_get verdict < "$tmp/case1.out")
    assert_eq "exit code" "0" "$rc" || return 1
    assert_eq "verdict"   "PASS" "$verdict" || return 1
}

# --- Case 2: lint REJECT -> wrapper NOT invoked ---
case2() {
    # Path violation: executor cannot write to 00-Morgan/.
    local input='{"writer_role":"executor","writer_engine":"claude","target_path":"00-Morgan/x.md","operation":"create","content":"---\nstatus: current\nvalid_from: 2026-05-10\nowner: morgan\nproject_id: pattern_trader\n---\n"}'
    local sentinel="$tmp/case2_wrapper_called"
    cat > "$tmp/wrapper_sentinel.sh" <<EOS
#!/usr/bin/env bash
echo "WRAPPER_WAS_CALLED" > "$sentinel"
exec bash "$WRAPPER" "\$@"
EOS
    chmod +x "$tmp/wrapper_sentinel.sh"
    set +e
    orchestrate "$tmp/wrapper_sentinel.sh" <<<"$input" > "$tmp/case2.out"
    local rc=$?
    set -e
    local verdict
    verdict=$(json_get verdict < "$tmp/case2.out")
    assert_eq "exit code" "1" "$rc" || return 1
    assert_eq "verdict"   "REJECT" "$verdict" || return 1
    if [[ -e "$sentinel" ]]; then
        echo "  FAIL wrapper sentinel was triggered (REJECT should not call wrapper)" >&2
        return 1
    fi
    echo "  OK  wrapper sentinel not triggered"
}

# --- Case 3: lint NEEDS_HUMAN -> wrapper propagate ---
case3() {
    # Inject fake gh CLI to force ADR mutex conflict (R10 -> NEEDS_HUMAN).
    mkdir -p "$tmp/fakegh"
    cat > "$tmp/fakegh/gh" <<'FAKEGH'
#!/usr/bin/env bash
case "$*" in
    *"pr list"*)
        cat <<'JSON'
[{"number": 999, "title": "Other PR", "body": "supersedes ADR_2026-05-01_legacy_auth"}]
JSON
        ;;
    *) echo '[]' ;;
esac
FAKEGH
    chmod +x "$tmp/fakegh/gh"
    local input='{"writer_role":"executor","writer_engine":"claude","target_path":"decisions/ADR_2026-05-10_new_auth.md","operation":"create","content":"---\nstatus: current\nvalid_from: 2026-05-10\nowner: morgan\nproject_id: ai_governance\nsupersedes: ADR_2026-05-01_legacy_auth\n---\nbody"}'
    set +e
    PATH="$tmp/fakegh:$PATH" \
    GUARDIAN_PROMPT_PATH="$GUARDIAN_REF" \
    GUARDIAN_REF_PATH="$GUARDIAN_REF" \
    GUARDIAN_LLM_MODE=stub_needs_human \
        orchestrate <<<"$input" > "$tmp/case3.out"
    local rc=$?
    set -e
    local verdict
    verdict=$(json_get verdict < "$tmp/case3.out")
    assert_eq "exit code" "1" "$rc" || return 1
    assert_eq "verdict"   "NEEDS_HUMAN" "$verdict" || return 1
}

# --- Case 4: wrapper drift -> GUARDIAN_UNAVAILABLE ---
case4() {
    cp "$GUARDIAN_REF" "$tmp/sudo_drift.md"
    printf '\nartificial drift line\n' >> "$tmp/sudo_drift.md"
    set +e
    GUARDIAN_PROMPT_PATH="$tmp/sudo_drift.md" \
    GUARDIAN_REF_PATH="$GUARDIAN_REF" \
    GUARDIAN_LLM_MODE=stub_pass \
        orchestrate <<<"$PASS_INPUT" > "$tmp/case4.out"
    local rc=$?
    set -e
    local verdict reason
    verdict=$(json_get verdict   < "$tmp/case4.out")
    reason=$( json_get reason_en < "$tmp/case4.out")
    assert_eq "exit code" "99" "$rc" || return 1
    assert_eq "verdict"   "GUARDIAN_UNAVAILABLE" "$verdict" || return 1
    if [[ "$reason" != drift_detected* ]]; then
        echo "  FAIL reason '$reason' does not start with 'drift_detected'" >&2
        return 1
    fi
    echo "  OK  reason: $reason"
}

run_case "Case 1: lint PASS -> wrapper mock PASS"           case1
run_case "Case 2: lint REJECT -> wrapper not invoked"       case2
run_case "Case 3: lint NEEDS_HUMAN -> wrapper propagates"   case3
run_case "Case 4: wrapper drift -> GUARDIAN_UNAVAILABLE"    case4

echo "==================================="
echo "Results: ${pass_count}/${total_count} passed, ${fail_count} failed"
if (( fail_count > 0 )); then
    exit 1
fi
exit 0
