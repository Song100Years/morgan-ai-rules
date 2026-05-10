#!/usr/bin/env bash
# Internal helper invoked by guardian-wrapper.sh. Phase 2b stub only.
# Phase 2c will replace the body of this script with a real Anthropic API
# call; wrapper interface (stdin/stdout contract) stays the same.
#
# stdin : JSON {"system": "<B section>", "user": <write request>}
# stdout: mock LLM verdict JSON (matching guardian.md output schema)
# env   : GUARDIAN_LLM_MODE     - which mock to emit
#         GUARDIAN_LLM_STUB_FILE - file to cat when mode=stub_from_file
set -euo pipefail

export PYTHONIOENCODING=utf-8

mode="${GUARDIAN_LLM_MODE:-stub_pass}"
stub_file="${GUARDIAN_LLM_STUB_FILE:-}"

# Drain stdin so the caller's pipe always closes cleanly. Phase 2c will
# json.load this; for now stubs ignore the input.
cat >/dev/null

emit_json() {
    python3 -c "import json,sys; print(json.dumps(json.loads(sys.argv[1]),ensure_ascii=False))" "$1"
}

case "$mode" in
    stub_pass)
        emit_json '{"verdict":"PASS","reason_en":"stub: mock guardian PASS","checklist_failed_at":"none","risk_assessment":{"scope":"T1","risk":"low"}}'
        ;;
    stub_reject)
        emit_json '{"verdict":"REJECT","reason_en":"stub: mock guardian REJECT","suggested_fix":"stub fix instruction","checklist_failed_at":"mock_rule"}'
        ;;
    stub_needs_human)
        emit_json '{"verdict":"NEEDS_HUMAN","reason_en":"stub: mock guardian propagate NEEDS_HUMAN","human_summary_zh":"「executor via claude 想 寫測試，但 mock 觸發 NEEDS_HUMAN，需要你 確認」","checklist_failed_at":"mock_rule"}'
        ;;
    stub_invalid_json)
        printf 'this is intentionally not json\n'
        ;;
    stub_from_file)
        if [[ -z "$stub_file" || ! -r "$stub_file" ]]; then
            echo "STUB_ERROR: stub file unreadable: $stub_file" >&2
            exit 1
        fi
        cat "$stub_file"
        ;;
    real)
        echo "STUB_ERROR: real LLM not implemented in Phase 2b (wired in Phase 2c)" >&2
        exit 1
        ;;
    *)
        echo "STUB_ERROR: unknown GUARDIAN_LLM_MODE: $mode" >&2
        exit 1
        ;;
esac
