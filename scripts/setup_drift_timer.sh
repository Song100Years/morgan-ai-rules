#!/usr/bin/env bash
# setup_drift_timer.sh - Phase 3 systemd timer for drift_check.sh
#
# Run on VPS as root: sudo bash setup_drift_timer.sh [--dry-run]
#
# Installs:
#   /etc/systemd/system/guardian-drift.service
#   /etc/systemd/system/guardian-drift.timer
#
# Per Phase 3 design (AI_Governance/INTEGRATION_DECISION.md):
#   - drift_check.sh runs as User=morgan (no sudo needed at runtime)
#   - log path = $HOME/morgan_ai_logs/ (script-managed, daily-rotated)
#   - 90-day cleanup handled inside drift_check.sh
#   - systemd journal captures stdout/stderr for debug
#   - daily run with Persistent=true so a missed run after VPS reboot still fires
#
# Idempotent: re-running overwrites unit files only when content differs,
# with timestamped backup to /etc/systemd/system/.backup-phase3/.

set -euo pipefail

DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

DRIFT_SCRIPT="/home/morgan/morgan-ai-rules/scripts/drift_check.sh"
SERVICE_PATH="/etc/systemd/system/guardian-drift.service"
TIMER_PATH="/etc/systemd/system/guardian-drift.timer"
BACKUP_DIR="/etc/systemd/system/.backup-phase3"
ts=$(date -u +%Y%m%dT%H%M%SZ)

# ----------------------------------------------------------------------------
# Preflight
# ----------------------------------------------------------------------------
if [[ $DRY_RUN -eq 0 && "$EUID" -ne 0 ]]; then
    echo "ERROR: setup_drift_timer.sh must be run as root (sudo bash setup_drift_timer.sh)" >&2
    echo "       (or pass --dry-run to preview without root)" >&2
    exit 1
fi

if [[ ! -r "$DRIFT_SCRIPT" ]]; then
    echo "ERROR: drift_check.sh not found at $DRIFT_SCRIPT" >&2
    echo "       Make sure morgan-ai-rules is cloned at /home/morgan/morgan-ai-rules" >&2
    echo "       and the working tree is up-to-date (git -C ... pull origin main)." >&2
    exit 2
fi

if [[ ! -x "$DRIFT_SCRIPT" ]]; then
    echo "WARN: $DRIFT_SCRIPT is not executable; chmod +x will be applied"
    if [[ $DRY_RUN -eq 0 ]]; then chmod +x "$DRIFT_SCRIPT"; fi
fi

# ----------------------------------------------------------------------------
# Build expected unit content
# ----------------------------------------------------------------------------
service_body=$(cat <<'UNIT'
[Unit]
Description=Guardian prompt drift check (Phase 2b / Phase 3 timer)
Documentation=https://github.com/Song100Years/morgan-ai-rules
After=network.target

[Service]
Type=oneshot
User=morgan
Environment=HOME=/home/morgan
ExecStart=/home/morgan/morgan-ai-rules/scripts/drift_check.sh
StandardOutput=journal
StandardError=journal
UNIT
)

timer_body=$(cat <<'UNIT'
[Unit]
Description=Daily guardian prompt drift check

[Timer]
OnCalendar=daily
Persistent=true
Unit=guardian-drift.service

[Install]
WantedBy=timers.target
UNIT
)

write_unit() {
    local path="$1"
    local body="$2"
    local name
    name=$(basename "$path")

    if [[ $DRY_RUN -eq 1 ]]; then
        echo "[dry-run] would write $path ($(printf '%s\n' "$body" | wc -l) lines)"
        return 0
    fi

    if [[ -f "$path" ]]; then
        local existing
        existing=$(cat "$path")
        if [[ "$existing" == "$body" ]]; then
            echo "[skip] $path already up-to-date"
            return 0
        fi
        mkdir -p "$BACKUP_DIR"
        cp -p "$path" "$BACKUP_DIR/${name}.${ts}.bak"
        echo "[backup] $path -> $BACKUP_DIR/${name}.${ts}.bak"
    fi
    printf '%s\n' "$body" > "$path"
    chown root:root "$path"
    chmod 0644 "$path"
    echo "[write] $path"
}

write_unit "$SERVICE_PATH" "$service_body"
write_unit "$TIMER_PATH"   "$timer_body"

if [[ $DRY_RUN -eq 1 ]]; then
    echo
    echo "[dry-run] would run:"
    echo "  systemctl daemon-reload"
    echo "  systemctl enable --now guardian-drift.timer"
    echo "  systemctl start guardian-drift.service   # sanity one-shot"
    echo "  systemctl list-timers guardian-drift.timer"
    echo "  systemctl status guardian-drift.service"
    exit 0
fi

# ----------------------------------------------------------------------------
# Load, enable, and run once to verify
# ----------------------------------------------------------------------------
systemctl daemon-reload
systemctl enable --now guardian-drift.timer

echo
echo "[verify] running guardian-drift.service once (oneshot, completes fast)..."
systemctl start guardian-drift.service

# Brief pause so journal has time to flush the oneshot output.
sleep 1

echo
echo "=== systemctl list-timers guardian-drift.timer ==="
systemctl list-timers guardian-drift.timer --all --no-pager || true

echo
echo "=== systemctl status guardian-drift.service ==="
systemctl status guardian-drift.service --no-pager --lines=15 || true

today_log="/home/morgan/morgan_ai_logs/guardian_drift_$(date -u +%F).log"
echo
echo "=== last 10 lines of $today_log ==="
if [[ -r "$today_log" ]]; then
    tail -10 "$today_log"
else
    echo "(log not yet created — check journalctl -u guardian-drift.service)"
fi

echo
echo "Setup complete. Daily timer active, Persistent=true so a missed run after"
echo "reboot still fires. Logs in ~morgan/morgan_ai_logs/ (90-day retention)."
