#!/usr/bin/env bash
# guardian-wrapper.sh - Gate 2 entrypoint for AI Vault writes.
#
# Pipeline (per DESIGN.md §3.2):
#   1. Drift check : sha256(/etc/guardian/prompt.md) == sha256(repo agents/guardian.md)
#   2. Extract B section from sudo-only prompt (LLM execution prompt)
#   3. Read write request from stdin, validate JSON
#   4. Compose LLM input ({system: B-section, user: request})
#   5. Call LLM (Phase 2b: stub via _guardian_llm_stub.sh; Phase 2c: real API)
#   6. Parse + validate LLM output JSON, extract verdict
#   7. Forward result to stdout, exit by verdict
#
# stdin : JSON write request (same shape as schema_lint input + optional
#         schema_lint_flags / schema_lint_verdict fields injected by caller)
# stdout: strict JSON guardian verdict (matches guardian.md section B output)
# exit  : 0 PASS | 1 REJECT or NEEDS_HUMAN | 99 GUARDIAN_UNAVAILABLE
#
# Env (all optional, defaults shown):
#   GUARDIAN_PROMPT_PATH=/etc/guardian/prompt.md
#   GUARDIAN_REF_PATH=<repo_root>/agents/guardian.md
#   GUARDIAN_LLM_MODE=stub_pass
#   GUARDIAN_LLM_STUB_FILE=
#   GUARDIAN_TIMEOUT_SEC=300
#
# Failure rule: ANY internal error -> emit GUARDIAN_UNAVAILABLE + exit 99.
# Wrapper does not interpret commit body claims; injection defense is the
# LLM's job (see B section).

set -euo pipefail

# Force UTF-8 for python stdout regardless of host locale (Windows defaults
# to cp950 in zh-TW environments, which mangles human_summary_zh).
export PYTHONIOENCODING=utf-8

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

GUARDIAN_PROMPT_PATH="${GUARDIAN_PROMPT_PATH:-/etc/guardian/prompt.md}"
GUARDIAN_REF_PATH="${GUARDIAN_REF_PATH:-$REPO_ROOT/agents/guardian.md}"
GUARDIAN_LLM_MODE="${GUARDIAN_LLM_MODE:-stub_pass}"
GUARDIAN_LLM_STUB_FILE="${GUARDIAN_LLM_STUB_FILE:-}"
GUARDIAN_TIMEOUT_SEC="${GUARDIAN_TIMEOUT_SEC:-300}"
LLM_HELPER="$SCRIPT_DIR/_guardian_llm_stub.sh"

emit_unavailable() {
    local reason="$1"
    python3 - "$reason" <<'PY'
import json, sys
print(json.dumps(
    {"verdict": "GUARDIAN_UNAVAILABLE", "reason_en": sys.argv[1]},
    ensure_ascii=False,
))
PY
    exit 99
}

# 0. Tool dependencies (fail closed if any missing).
for tool in python3 awk sha256sum tr timeout; do
    command -v "$tool" >/dev/null 2>&1 || emit_unavailable "missing_tool_${tool}"
done

if [[ ! -x "$LLM_HELPER" && ! -r "$LLM_HELPER" ]]; then
    emit_unavailable "llm_helper_unreadable"
fi

# 1. Drift check. Normalize CRLF -> LF before hashing so Windows-checked-out
#    references and Linux-deployed prompts compare equal.
[[ -r "$GUARDIAN_PROMPT_PATH" ]] || emit_unavailable "prompt_path_unreadable: $GUARDIAN_PROMPT_PATH"
[[ -r "$GUARDIAN_REF_PATH"   ]] || emit_unavailable "ref_path_unreadable: $GUARDIAN_REF_PATH"

normalize_hash() {
    tr -d '\r' < "$1" | sha256sum | awk '{print $1}'
}

if ! sudo_hash=$(normalize_hash "$GUARDIAN_PROMPT_PATH"); then
    emit_unavailable "drift_hash_compute_failed_sudo"
fi
if ! ref_hash=$(normalize_hash "$GUARDIAN_REF_PATH"); then
    emit_unavailable "drift_hash_compute_failed_ref"
fi
if [[ "$sudo_hash" != "$ref_hash" ]]; then
    emit_unavailable "drift_detected sudo=${sudo_hash:0:12} ref=${ref_hash:0:12}"
fi

# 2. Extract B section (LLM execution prompt). Skip the header line itself,
#    matching the sketch in schema/RULES.md.
b_section=$(awk '/^# B\. LLM Execution Prompt/{flag=1; next} flag' "$GUARDIAN_PROMPT_PATH")
if [[ -z "$b_section" ]]; then
    emit_unavailable "b_section_empty"
fi

# 3. Read stdin and validate it parses as JSON.
input_json="$(cat)"
if [[ -z "$input_json" ]]; then
    emit_unavailable "input_empty"
fi
if ! printf '%s' "$input_json" | python3 -c 'import json,sys; json.load(sys.stdin)' >/dev/null 2>&1; then
    emit_unavailable "input_invalid_json"
fi

# 4. Compose LLM input. Phase 2c will feed this into the real API; the stub
#    drains stdin without using it.
if ! llm_input=$(printf '%s' "$input_json" | python3 -c '
import json, sys
sys_prompt = sys.argv[1]
user_payload = json.load(sys.stdin)
print(json.dumps({"system": sys_prompt, "user": user_payload}, ensure_ascii=False))
' "$b_section"); then
    emit_unavailable "llm_input_compose_failed"
fi

# 5. Call LLM (Phase 2b stub) under a hard timeout.
set +e
llm_raw=$(printf '%s' "$llm_input" | \
    GUARDIAN_LLM_MODE="$GUARDIAN_LLM_MODE" \
    GUARDIAN_LLM_STUB_FILE="$GUARDIAN_LLM_STUB_FILE" \
    timeout "$GUARDIAN_TIMEOUT_SEC" bash "$LLM_HELPER")
rc=$?
set -e
if [[ $rc -eq 124 ]]; then
    emit_unavailable "llm_timeout_${GUARDIAN_TIMEOUT_SEC}s"
fi
if [[ $rc -ne 0 ]]; then
    emit_unavailable "llm_call_rc_${rc}"
fi

# 6. Parse LLM output and validate verdict field.
if ! printf '%s' "$llm_raw" | python3 -c 'import json,sys; json.load(sys.stdin)' >/dev/null 2>&1; then
    emit_unavailable "llm_output_invalid_json"
fi
verdict=$(printf '%s' "$llm_raw" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("verdict",""))')

case "$verdict" in
    PASS|REJECT|NEEDS_HUMAN|GUARDIAN_UNAVAILABLE) ;;
    *) emit_unavailable "llm_output_missing_verdict_${verdict:-empty}" ;;
esac

# 7. Output and exit by verdict.
printf '%s\n' "$llm_raw"
case "$verdict" in
    PASS) exit 0 ;;
    REJECT|NEEDS_HUMAN) exit 1 ;;
    GUARDIAN_UNAVAILABLE) exit 99 ;;
esac
