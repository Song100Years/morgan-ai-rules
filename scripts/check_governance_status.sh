#!/usr/bin/env bash
# check_governance_status.sh - Phase 5.5 觀察期一鍵 status 報告
#
# Usage:
#   bash check_governance_status.sh          # default: 7-day window
#   bash check_governance_status.sh 30d      # 30-day window
#   bash check_governance_status.sh all      # all time
#
# Output: markdown to stdout (advisor 跑後解讀給 Morgan 看)
#
# Reads:
#   - ~/.claude/logs/vault_governance_revert.jsonl  (Phase 5.5 PostToolUse log)
#   - ~/.claude/logs/vault_governance_shadow.jsonl  (Phase 5 shadow log, if used)
#   - D:/vault-tracking/quarantine/YYYY-MM-DD/      (Phase 5.5 quarantine)
#   - D:/vault-tracking/.git                        (baseline HEAD)
#
# Note: Local utility, NOT committed to repo (Morgan 觀察期 1-2 週用)

set -uo pipefail
export PYTHONIOENCODING=utf-8

WINDOW="${1:-7d}"

REVERT_LOG="${REVERT_LOG:-$HOME/.claude/logs/vault_governance_revert.jsonl}"
SHADOW_LOG="${SHADOW_LOG:-$HOME/.claude/logs/vault_governance_shadow.jsonl}"

VAULT_TRACKING_GIT_DIR=""
for cand in "/d/vault-tracking/.git" "/e/vault-tracking/.git" "$HOME/vault-tracking/.git"; do
  if [[ -d "$cand" ]]; then
    VAULT_TRACKING_GIT_DIR="$cand"
    break
  fi
done
QUARANTINE_DIR=""
if [[ -n "$VAULT_TRACKING_GIT_DIR" ]]; then
  QUARANTINE_DIR="${VAULT_TRACKING_GIT_DIR%/.git}/quarantine"
fi

NOW_UTC=$(date -u +%Y-%m-%dT%H:%M:%SZ)
HOSTNAME_SHORT=$(hostname 2>/dev/null || echo "unknown")
BASELINE="NOT_INIT"
if [[ -n "$VAULT_TRACKING_GIT_DIR" ]]; then
  BASELINE=$(git --git-dir="$VAULT_TRACKING_GIT_DIR" rev-parse --short HEAD 2>/dev/null || echo "NOT_INIT")
fi

cat <<HEADER
# Governance Status — Phase 5.5 觀察期報告

| 項 | 值 |
|---|---|
| 報告產出時間 (UTC) | $NOW_UTC |
| 觀察窗口 | $WINDOW |
| 機器 | $HOSTNAME_SHORT |
| Vault baseline HEAD | \`$BASELINE\` |
| revert log | \`$REVERT_LOG\` |
| quarantine dir | \`$QUARANTINE_DIR\` |

---

HEADER

# === §1 PostToolUse Revert Log ===
echo "## §1 PostToolUse Revert Log"
echo
if [[ ! -f "$REVERT_LOG" ]]; then
  cat <<NOLOG
⚠️ revert log 不存在：\`$REVERT_LOG\`

可能原因：
- Morgan 還沒重啟 Claude Code session（hook 未 active）
- Hook 尚未 fire（vault 上沒寫入紀錄）

🟡 觀察期 trigger 之一：log 第一筆出現 = hook 活著
NOLOG
else
  TOTAL_LINES=$(wc -l < "$REVERT_LOG" 2>/dev/null | tr -d ' ' || echo 0)
  echo "log total lines: \`$TOTAL_LINES\`"
  echo
  python3 - "$REVERT_LOG" "$WINDOW" <<'PY'
import sys, json
from datetime import datetime, timezone, timedelta
from collections import Counter

path, window = sys.argv[1], sys.argv[2]
now = datetime.now(timezone.utc)

if window == "all":
    since = None
elif window.endswith("d"):
    try:
        since = now - timedelta(days=int(window[:-1]))
    except ValueError:
        since = None
else:
    since = None

records = []
with open(path, encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        try:
            ts = datetime.fromisoformat(rec.get("timestamp", "").replace("Z", "+00:00"))
        except Exception:
            ts = None
        if since and (ts is None or ts < since):
            continue
        records.append((ts, rec))

records.sort(key=lambda x: x[0] or datetime.min.replace(tzinfo=timezone.utc))

print(f"records in window ({window}): {len(records)}")
print()
if not records:
    print("→ 觀察期內無紀錄")
    sys.exit(0)

verdicts = Counter(r[1].get("verdict", "UNKNOWN") for r in records)
actions = Counter(r[1].get("action", "NONE") for r in records)
rules = Counter(r[1].get("fail_at_rule", "") for r in records if r[1].get("fail_at_rule"))

print("### Verdict 分布")
print()
print("| Verdict | 次數 |")
print("|---|---|")
for v, n in verdicts.most_common():
    print(f"| {v} | {n} |")
print()

print("### Action 分布")
print()
print("| Action | 次數 |")
print("|---|---|")
for a, n in actions.most_common():
    print(f"| {a} | {n} |")
print()

if rules:
    print("### 規則命中 top 5")
    print()
    print("| Rule | 次數 |")
    print("|---|---|")
    for r, n in rules.most_common(5):
        print(f"| {r} | {n} |")
    print()

print("### 最近 5 筆")
print()
for ts, r in records[-5:]:
    ts_str = ts.strftime("%Y-%m-%dT%H:%M:%SZ") if ts else "?"
    action = r.get("action", "?")
    verdict = r.get("verdict", "?")
    rel = r.get("rel_path", "?")
    rule = r.get("fail_at_rule", "")
    note = r.get("result_note", "")
    line = f"- `{ts_str}` {action} ({verdict}) `{rel}`"
    if rule:
        line += f" [rule={rule}]"
    if note:
        line += f" — {note[:80]}"
    print(line)
PY
fi
echo

# === §2 Quarantine ===
echo "## §2 Quarantine 目錄"
echo
if [[ -z "$QUARANTINE_DIR" || ! -d "$QUARANTINE_DIR" ]]; then
  echo "⚠️ quarantine dir 不存在: \`$QUARANTINE_DIR\`"
  echo
  echo "推測：Phase 5.5 init_vault_tracking.sh 尚未跑"
else
  TOTAL=$(find "$QUARANTINE_DIR" -type f 2>/dev/null | wc -l | tr -d ' ')
  echo "累積檔數: \`${TOTAL:-0}\`"
  echo
  if [[ "${TOTAL:-0}" -gt 0 ]]; then
    echo "### 每日量（最近 10 日）"
    echo
    echo "| 日期 | 檔數 |"
    echo "|---|---|"
    for d in $(ls -1 "$QUARANTINE_DIR" 2>/dev/null | sort -r | head -10); do
      [[ -d "$QUARANTINE_DIR/$d" ]] || continue
      cnt=$(find "$QUARANTINE_DIR/$d" -type f 2>/dev/null | wc -l | tr -d ' ')
      echo "| $d | $cnt |"
    done
  else
    echo "→ 觀察期內無 quarantine（hook 沒攔到 untracked 違規檔）"
  fi
fi
echo

# === §3 Shadow log ===
echo "## §3 Shadow Mode Log"
echo
if [[ ! -f "$SHADOW_LOG" ]]; then
  echo "✅ shadow log 不存在（default enforce 模式正常）"
else
  TOTAL=$(wc -l < "$SHADOW_LOG" 2>/dev/null | tr -d ' ' || echo 0)
  echo "shadow log total lines: \`$TOTAL\`"
fi
echo

# === §4 Phase 6 trigger 量化指標 ===
echo "## §4 Phase 6 動工 trigger（量化綠燈）"
echo

if [[ -f "$REVERT_LOG" ]]; then
  REVERT_COUNT=$(python3 - "$REVERT_LOG" <<'PYR'
import sys, json
from datetime import datetime, timezone, timedelta
path = sys.argv[1]
now = datetime.now(timezone.utc)
since = now - timedelta(days=7)
count = 0
try:
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line.strip())
                if rec.get("action") != "REVERT":
                    continue
                ts = datetime.fromisoformat(rec.get("timestamp", "").replace("Z", "+00:00"))
                if ts >= since:
                    count += 1
            except Exception:
                pass
except Exception:
    pass
print(count)
PYR
)
else
  REVERT_COUNT="—"
fi

if [[ -d "$QUARANTINE_DIR" ]]; then
  Q_BIWEEKLY=$(find "$QUARANTINE_DIR" -type f -mtime -14 2>/dev/null | wc -l | tr -d ' ')
else
  Q_BIWEEKLY="—"
fi

green_revert="🟡"
if [[ "$REVERT_COUNT" =~ ^[0-9]+$ ]] && [[ "$REVERT_COUNT" -lt 5 ]]; then
  green_revert="✅"
fi
green_quar="🟡"
if [[ "$Q_BIWEEKLY" =~ ^[0-9]+$ ]] && [[ "$Q_BIWEEKLY" -lt 10 ]]; then
  green_quar="✅"
fi

echo "| 指標 | 綠燈門檻 | 現況 | 狀態 |"
echo "|---|---|---|---|"
echo "| REVERT 量 (7d) | < 5 / 週 | $REVERT_COUNT | $green_revert |"
echo "| false positive | 0 | （Morgan 抽 3-5 筆人工確認） | 🟡 手動 |"
echo "| quarantine 累積 (14d) | < 10 / 兩週 | $Q_BIWEEKLY | $green_quar |"
echo "| 雲端 BAD revision 漏網 | 0 | （Morgan 抽 3-5 個治理檔 OneDrive history） | 🟡 手動 |"
echo

cat <<FOOTER
---

## 一句話判讀

（advisor 跑此 script 後依結果寫場景化結論給 Morgan）

End of governance status report.
FOOTER
