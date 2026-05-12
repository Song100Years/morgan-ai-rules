#!/usr/bin/env bash
# drift_check.sh - VPS-side periodic check.
#
# Compares /etc/guardian/prompt.md against a local clone of the public reference
# copy at ~/morgan-ai-rules/agents/guardian.md. The wrapper already fails closed
# at runtime if the hashes diverge; this gives ops a heads-up between vault
# write attempts.
#
# Hash uses CRLF-normalized content so a Windows-side commit cannot trip a
# false positive against the Linux-deployed copy.
#
# Env (optional):
#   GUARDIAN_PROMPT_PATH (default: /etc/guardian/prompt.md)
#   GUARDIAN_REF_PATH    (default: $HOME/morgan-ai-rules/agents/guardian.md)
#   DRIFT_LOG_DIR        (default: $HOME/morgan_ai_logs)
#
# Exit: 0 hashes match | 1 drift detected | 2 read error.
#
# This script is idempotent and side-effect free except for the daily log file.
# Scheduling (systemd timer or cron) is NOT enabled here; Morgan installs the
# timer manually after reviewing this script.

set -euo pipefail
export PYTHONIOENCODING=utf-8

GUARDIAN_PROMPT_PATH="${GUARDIAN_PROMPT_PATH:-/etc/guardian/prompt.md}"
GUARDIAN_REF_PATH="${GUARDIAN_REF_PATH:-$HOME/morgan-ai-rules/agents/guardian.md}"
DRIFT_LOG_DIR="${DRIFT_LOG_DIR:-$HOME/morgan_ai_logs}"

mkdir -p "$DRIFT_LOG_DIR"
find "$DRIFT_LOG_DIR" -maxdepth 1 -name 'guardian_drift_*.log' -type f -mtime +90 -delete 2>/dev/null || true
log_file="$DRIFT_LOG_DIR/guardian_drift_$(date -u +%F).log"
ts=$(date -u +%FT%TZ)

log() {
    printf '%s %s\n' "$ts" "$1" | tee -a "$log_file"
}

if [[ ! -r "$GUARDIAN_PROMPT_PATH" ]]; then
    log "ERROR prompt_unreadable=$GUARDIAN_PROMPT_PATH"
    echo "DRIFT_CHECK_ERROR prompt_unreadable=$GUARDIAN_PROMPT_PATH" >&2
    exit 2
fi
if [[ ! -r "$GUARDIAN_REF_PATH" ]]; then
    log "ERROR ref_unreadable=$GUARDIAN_REF_PATH"
    echo "DRIFT_CHECK_ERROR ref_unreadable=$GUARDIAN_REF_PATH" >&2
    exit 2
fi

normalize_hash() {
    tr -d '\r' < "$1" | sha256sum | awk '{print $1}'
}

sudo_hash=$(normalize_hash "$GUARDIAN_PROMPT_PATH")
ref_hash=$(normalize_hash "$GUARDIAN_REF_PATH")

if [[ "$sudo_hash" == "$ref_hash" ]]; then
    log "OK sha256=$sudo_hash"
    exit 0
fi

log "DRIFT sudo=$sudo_hash ref=$ref_hash"
echo "DRIFT_DETECTED sudo=$sudo_hash ref=$ref_hash" >&2
exit 1
