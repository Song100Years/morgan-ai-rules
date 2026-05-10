---
status: current
valid_from: 2026-05-09
owner: morgan
project_id: ai_governance
version: 2.2.0
---

# Schema Lint Rules — Hard Gate

> **Deterministic** check，跑在 guardian LLM 之前。
> **實作**：純 Python，不呼叫 LLM。
> **目標**：1 秒內擋掉 80% 程式可判斷的違規，避免無謂的 LLM 開銷。

---

## 架構位置

```
PR push → GitHub Actions
  ├─ Step 1: schema_lint（本文件）
  │    ├─ pass → Step 2
  │    └─ fail → REJECT（不呼叫 guardian）
  └─ Step 2: guardian LLM（語意判斷）
       ├─ PASS → auto-merge
       ├─ REJECT → block PR
       └─ NEEDS_HUMAN → label + dashboard
```

**為什麼分兩層**：
- Schema lint 處理「程式可判斷」（路徑匹配、欄位完整、命名規則）→ 快、穩、deterministic、跨 LLM 版本不漂移
- Guardian 處理「語意判斷」（同主題衝突、契約變更、injection 偵測）→ 必須 LLM

---

## 規則總覽

| ID | 規則 | 觸發 | Verdict |
|---|---|---|---|
| R1 | Path × writer_role 匹配 | 路徑不在角色允許清單 | REJECT |
| R2 | writer_engine × writer_role 限制 | codex + executor | REJECT |
| R3 | Frontmatter 必填欄位 | 缺欄位 | REJECT |
| R4 | Frontmatter status enum | status 值非法 | REJECT |
| R5 | Frontmatter 條件欄位 | superseded 缺 superseded_by / draft 缺 expires_at | REJECT |
| R6 | 命名規範 | ASCII / snake_case / 非空泛 / 無 _v2 後綴 | REJECT |
| R7 | Legacy 區唯讀 | path 開頭 archive/legacy_ | REJECT |
| R8 | ADR 不可改 | 對既有 ADR 做 update | REJECT |
| R9 | superseded_by 鏈完整性 | 目標不存在 / 非 active / 循環 | REJECT |
| R10 | ADR ID 互斥鎖 | 另一個 open PR 也聲稱取代同一 ADR | NEEDS_HUMAN |
| R11 | Draft expires_at 有效性 | 不在 30 天內 / 格式錯 | REJECT |
| R12 | Promote draft 升級旗標 | draft → current 觸發 strict guardian | (flag) |
| R13 | Stop_work schema | minimal（hotfix/）vs full（其他）| REJECT |
| R14 | Timestamp UTC | 任何日期欄位非 UTC ISO8601 | REJECT |
| R15 | project_id 註冊驗證 | project_id 未註冊 | REJECT |

---

## 規則細節

### R1 — Path × writer_role 匹配

| writer_role | 允許路徑 prefix | 禁止路徑 prefix |
|---|---|---|
| `executor` | `projects/`, `decisions/` | `00-Morgan/`, `archive/legacy_`, `99-rules/`, `agents/` |
| `advisor` | `decisions/concerns/`, `decisions/verdicts/` | 上述以外 |
| `auditor` | `00-Morgan/`, `audit_logs/` | 上述以外 |
| `desktop` | （無） | 整個 vault |
| `human_only` | （無限制，admin token bypass guardian）| – |
| `other` | （無） | 整個 vault |

**邏輯**：`target_path.startswith(allowed_prefix)` 且 NOT `target_path.startswith(forbidden_prefix)`

**suggested_fix**：列出該 role 允許的路徑

### R2 — writer_engine × writer_role 限制

```python
if writer_engine == "codex" and writer_role == "executor":
    return REJECT("CODEX_EXECUTOR_FORBIDDEN")
```

**理由**：codex bwrap sandbox 不可讀檔/寫檔/跑 shell（pattern_trader §6 Gotchas 2026-05-07）

**suggested_fix**：「使用 writer_engine: claude，或改 writer_role 為 advisor / auditor」

### R3 — Frontmatter 必填欄位

`status / valid_from / owner / project_id`（共 4 個必填）

**suggested_fix**：列出缺哪些欄位 + 範例

### R4 — Frontmatter status enum

允許值：`current | draft | superseded | archived | legacy`

**suggested_fix**：列出合法 status 列表

### R5 — Frontmatter 條件欄位

| status | 條件欄位 |
|---|---|
| `superseded` | 必填 `superseded_by` |
| `draft` | 必填 `expires_at`（30 天內，UTC ISO8601）|

**suggested_fix**：根據 status 列出該補的欄位

### R6 — 命名規範

合法檔名：
- ASCII only：`[a-zA-Z0-9_\-\.]+\.md`
- snake_case 或 kebab-case
- 不接受空泛：`untitled / new / temp / draft / test`
- 不接受 suffix versioning：`_v2.md / (1).md`（用 frontmatter `supersedes` 而非檔名）

**suggested_fix**：「建議檔名：`<topic>_<descriptor>.md`，例如 `slice_03_handoff.md`」

### R7 — Legacy 區唯讀

```python
if target_path.startswith("archive/legacy_"):
    return REJECT("LEGACY_READONLY")
```

**理由**：legacy 是凍結歷史，AI 不該動。promote 走 auditor 提案 → Morgan 裁決 → executor 寫到 current 區的流程。

**suggested_fix**：「legacy 不可寫；如需內容，在 current 區寫新文件並引用 legacy 來源」

### R8 — ADR 不可改

```python
if (path 含 /decisions/ 或 /ADR/) and operation == "update" and 既有 ADR 存在:
    return REJECT("ADR_IMMUTABLE")
```

**理由**：決策落地後不可改，要寫新 ADR + frontmatter `supersedes: <舊 ID>`。

**suggested_fix**：「建立新 ADR `decisions/ADR_YYYY-MM-DD_<topic>.md`，frontmatter 加 `supersedes: <old_id>`」

### R9 — superseded_by 鏈完整性

如 frontmatter 有 `superseded_by`：

1. 目標檔案必須存在於 vault
2. 目標檔案 status 必須是 `current` 或 `superseded`（**不可** `archived` / `legacy`）
3. 不得形成循環鏈（A → B → C → A）

**邏輯**：DFS 走 superseded_by 鏈，最多走 10 層（防 runaway），檢查 visited set。

**suggested_fix**：依失敗原因給不同訊息（不存在 / 已 archived / 循環）

### R10 — ADR ID 互斥鎖（NEEDS_HUMAN）

```python
if frontmatter.supersedes:
    other_open_prs = get_open_prs_with_supersedes_target(frontmatter.supersedes)
    if other_open_prs:
        return NEEDS_HUMAN("ADR_MUTEX_CONFLICT")
```

**理由**：兩個 PR 同時想取代同一個 ADR → merge 順序決定誰贏，混亂。Morgan 必須裁決保留哪份。

**human_summary**：「{writer_role} 和 PR #{other_pr} 都想取代 ADR {target}，需要你裁決保留哪份」

### R11 — Draft expires_at 有效性

```python
if frontmatter.status == "draft":
    expires_at = parse_utc_iso(frontmatter.expires_at)
    if expires_at > now_utc() + timedelta(days=30):
        return REJECT("DRAFT_EXPIRES_INVALID")
    if expires_at < now_utc():
        return REJECT("DRAFT_EXPIRES_INVALID", "draft already expired")
```

**suggested_fix**：「expires_at 必須在 30 天內，格式 UTC ISO8601 (`2026-06-08T00:00:00Z`)」

### R12 — Promote draft 升級旗標（不 REJECT，僅旗標）

```python
if operation == "update":
    previous = read_existing(target_path)
    if previous.status == "draft" and frontmatter.status == "current":
        flags.append("PROMOTE_DRAFT_STRICT_GUARDIAN")
```

**作用**：通知 orchestrator「這次 promote 必須跑 guardian strict mode」（不接受 cache，雙 prompt regardless of risk）。

### R13 — Stop_work schema 分級

| 觸發條件 | Schema |
|---|---|
| Branch 開頭 `hotfix/*` 或 frontmatter `emergency: true` | minimal schema |
| 其他 | full schema |

**Minimal schema 必填**：
- `commit_hash`
- `task_summary`（一句話）
- `next_step`
- `emergency: true`
- `wip_since` (UTC)

**Full schema 必填**（multi-agent 既有 verify_stop_work.py 的標準）：
- `current_task`
- `status`
- `next_tasks` (list)
- `next_command`
- `registry_note`
- `wip_since` / `promoted_at`
- `session_id`
- `machine_id`
- `vault_context_hash`

### R14 — Timestamp UTC

所有日期欄位（`valid_from`, `expires_at`, `wip_since`, `promoted_at`, `generated_at`, ...）必須是 UTC ISO8601 格式：

合法：`2026-05-09T15:30:00Z` / `2026-05-09T15:30:00+00:00`
非法：`2026-05-09 15:30` / `2026-05-09T15:30:00+08:00`（非 UTC）/ `May 9, 2026`

**理由**：跨機判斷 stale 必須統一時區，否則跨機 stale 判斷會錯。

### R15 — project_id 註冊驗證

```python
VALID_PROJECT_IDS = load_from("morgan_ai_rules/projects_registry.json")

if frontmatter.project_id not in VALID_PROJECT_IDS:
    return REJECT("PROJECT_ID_NOT_FOUND")
```

**理由**：避免亂打 project_id 導致 dashboard 統計亂。

**suggested_fix**：列出已註冊 project_ids（pretest_system / solar_dashboard / pattern_trader / codex_multi_agent / ai_governance / ...）

---

## 錯誤碼總表

| code | 對應規則 | Verdict | 一句話描述 |
|---|---|---|---|
| `PATH_PERMISSION` | R1 | REJECT | writer_role 不能寫此路徑 |
| `CODEX_EXECUTOR_FORBIDDEN` | R2 | REJECT | codex 不能當 unsupervised executor |
| `FRONTMATTER_MISSING` | R3 | REJECT | 缺必填欄位 |
| `FRONTMATTER_INVALID_STATUS` | R4 | REJECT | status 值不在 enum |
| `FRONTMATTER_CONDITIONAL_MISSING` | R5 | REJECT | superseded/draft 缺條件欄位 |
| `NAMING_VIOLATION` | R6 | REJECT | 檔名違反命名規範 |
| `LEGACY_READONLY` | R7 | REJECT | legacy 區不可寫 |
| `ADR_IMMUTABLE` | R8 | REJECT | 對既有 ADR 做 update |
| `ADR_CHAIN_BROKEN` | R9 | REJECT | superseded_by 鏈斷 |
| `ADR_MUTEX_CONFLICT` | R10 | NEEDS_HUMAN | 兩 PR 想取代同 ADR |
| `DRAFT_EXPIRES_INVALID` | R11 | REJECT | draft expires_at 無效 |
| `STOPWORK_SCHEMA` | R13 | REJECT | stop_work 不符 schema |
| `TIMESTAMP_NOT_UTC` | R14 | REJECT | timestamp 非 UTC |
| `PROJECT_ID_NOT_FOUND` | R15 | REJECT | project_id 未註冊 |

---

## Implementation Sketch（Python skeleton）

```python
# schema_lint.py — sketch
# Phase 2 動工時擴展為完整實作

import yaml
import re
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

# ========= Constants (load from morgan_ai_rules) =========

WRITER_ROLE_PATHS = {
    "executor": {"allow": ["projects/", "decisions/"],
                 "deny": ["00-Morgan/", "archive/legacy_", "99-rules/", "agents/"]},
    "advisor":  {"allow": ["decisions/concerns/", "decisions/verdicts/"],
                 "deny": []},  # implicit deny everything else
    "auditor":  {"allow": ["00-Morgan/", "audit_logs/"], "deny": []},
    "desktop":  {"allow": [], "deny": ["*"]},
    "human_only": {"allow": ["*"], "deny": []},
    "other":    {"allow": [], "deny": ["*"]},
}

STATUS_ENUM = {"current", "draft", "superseded", "archived", "legacy"}
VACUOUS_NAMES = {"untitled", "new", "temp", "draft", "test"}
NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_\-\.]*\.md$")
SUFFIX_VERSIONING = re.compile(r"_v\d+\.md$|\(\d+\)\.md$")

# ========= Public API =========

def lint(req: dict) -> dict:
    """
    req: {writer_role, writer_engine, target_path, operation, content, ...}
    returns: {verdict, error_code, suggested_fix, fail_at_rule, flags}
    """
    role = req["writer_role"]
    engine = req["writer_engine"]
    path = req["target_path"]
    op = req["operation"]
    content = req["content"]

    # R1
    if not _path_allowed(path, role):
        return _reject("PATH_PERMISSION", _allowed_paths_msg(role), "R1")

    # R2
    if engine == "codex" and role == "executor":
        return _reject("CODEX_EXECUTOR_FORBIDDEN",
                       "use writer_engine: claude, or change role to advisor/auditor", "R2")

    # R3-R5: frontmatter
    try:
        fm = _parse_frontmatter(content)
    except yaml.YAMLError as e:
        return _reject("FRONTMATTER_MISSING", f"YAML parse error: {e}", "R3")

    if missing := _required_missing(fm):
        return _reject("FRONTMATTER_MISSING", f"missing: {missing}", "R3")

    if fm["status"] not in STATUS_ENUM:
        return _reject("FRONTMATTER_INVALID_STATUS",
                       f"got '{fm['status']}', want one of {sorted(STATUS_ENUM)}", "R4")

    if cond_err := _conditional_missing(fm):
        return _reject("FRONTMATTER_CONDITIONAL_MISSING", cond_err, "R5")

    # R6
    name = Path(path).name
    if name_err := _check_naming(name):
        return _reject("NAMING_VIOLATION", name_err, "R6")

    # R7
    if path.startswith("archive/legacy_"):
        return _reject("LEGACY_READONLY", "legacy region read-only", "R7")

    # R8
    if _is_adr_path(path) and op == "update" and _file_exists_in_vault(path):
        return _reject("ADR_IMMUTABLE",
                       "ADR immutable; create new + supersedes", "R8")

    # R9
    if "superseded_by" in fm:
        if chain_err := _validate_chain(fm["superseded_by"]):
            return _reject("ADR_CHAIN_BROKEN", chain_err, "R9")

    # R10 (NEEDS_HUMAN)
    if "supersedes" in fm:
        if other_pr := _adr_mutex_check(fm["supersedes"]):
            return _needs_human("ADR_MUTEX_CONFLICT",
                                f"PR #{other_pr} 也想取代 {fm['supersedes']}", "R10")

    # R11
    if fm["status"] == "draft":
        if exp_err := _check_expires_at(fm.get("expires_at")):
            return _reject("DRAFT_EXPIRES_INVALID", exp_err, "R11")

    # R12 (flag, not fail)
    flags = []
    if op == "update":
        prev = _read_existing(path)
        if prev and prev.get("status") == "draft" and fm["status"] == "current":
            flags.append("PROMOTE_DRAFT_STRICT_GUARDIAN")

    # R13
    if "handoff/stop_work_" in path:
        is_emergency = req.get("branch", "").startswith("hotfix/") or fm.get("emergency")
        if sw_err := _check_stopwork_schema(content, minimal=is_emergency):
            return _reject("STOPWORK_SCHEMA", sw_err, "R13")

    # R14
    if ts_err := _check_all_timestamps_utc(fm):
        return _reject("TIMESTAMP_NOT_UTC", ts_err, "R14")

    # R15
    if not _project_id_registered(fm.get("project_id")):
        return _reject("PROJECT_ID_NOT_FOUND",
                       _registered_projects_msg(), "R15")

    return {"verdict": "PASS", "flags": flags}

# ========= Helpers (stub, full impl in Phase 2) =========

def _reject(code, fix, rule):
    return {"verdict": "REJECT", "error_code": code,
            "suggested_fix": fix, "fail_at_rule": rule}

def _needs_human(code, summary, rule):
    return {"verdict": "NEEDS_HUMAN", "error_code": code,
            "human_summary_zh": summary, "fail_at_rule": rule}

# ... 其餘 helper 函式 stub
```

---

## 測試用例（Phase 2 動工時實作）

每條規則至少 3 個 test case：
- positive case（PASS）
- negative case（fail with expected error_code）
- edge case（boundary：30 天剛好、ADR 鏈剛好 10 層、空 frontmatter 等）

存放：`morgan_ai_rules/schema/tests/test_schema_lint.py`

CI required：每次 morgan_ai_rules PR 必跑 schema_lint 自己的測試。

---

## 跟 guardian 的銜接

schema_lint pass → 把 input + flags 傳給 guardian wrapper：

```bash
# wrapper sketch
LINT_RESULT=$(python schema_lint.py < input.json)
LINT_VERDICT=$(echo "$LINT_RESULT" | jq -r '.verdict')

if [ "$LINT_VERDICT" != "PASS" ]; then
    echo "$LINT_RESULT"  # forward REJECT/NEEDS_HUMAN to PR check
    exit 1
fi

# pass: include flags in guardian input
FLAGS=$(echo "$LINT_RESULT" | jq -r '.flags[]')
GUARDIAN_INPUT=$(jq --arg flags "$FLAGS" '. + {schema_lint_flags: $flags}' input.json)

# call guardian with extracted English execution prompt
EXEC_PROMPT=$(awk '/^# B\. LLM Execution Prompt/{flag=1; next} flag' /etc/guardian/prompt.md)
echo "$GUARDIAN_INPUT" | claude api --system-stdin "$EXEC_PROMPT" --json-output
```

---

## 演進空間

**v2.2 不含但未來可加**：
- R16: 跨檔 dependency 圖驗證（A 引用 B，B archived → A 該知道）
- R17: 內容大小上限（advisor 寫 > 100 行直接 REJECT，跟 guardian #6 對齊但更嚴）
- R18: 內容語言一致性（中英混排警告）
- R19: 引用 link 完整性（markdown 內 link 是否壞）

每條都要先在 issue 討論，過 dual-review 才加進 RULES。
