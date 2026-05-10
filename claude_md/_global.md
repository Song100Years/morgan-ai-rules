---
status: current
valid_from: 2026-05-09
owner: morgan
project_id: ai_governance
version: 2.2.0
---

# AI 協作共用規範 (_global.md) — v2.2

> 各專案 CLAUDE.md 由本檔 + `<project>.md` 拼接而成（衍生物，pre-commit hook 擋直編）。
> 中央 single source of truth：`morgan-ai-rules/claude_md/_global.md`
> 改規則流程：edit → PR → dual-review → admin merge → 各專案 `pull_rules.sh` + `render_claude_md.py` → 自動更新

## §0. 必讀

- `{VAULT}/99-system/AI_RULES.md`（全域 AI 工作守則）
- `{VAULT}/99-system/AI_Governance/DESIGN.md`（治理升級 v2.2 設計）

---

## §1. 安全紅線（必須遵守）

- **絕對不**把 token / 密碼 / API key / SSH private key 寫進 git；一律走 `.env` 或環境變數
- **API endpoint 必須驗證輸入**（型別 / 範圍 / 白名單）
- **API 呼叫必須設 timeout**（沒設等於潛在掛死）
- **禁止 SQL 拼接**（使用 SQL 的專案）— 一律參數化查詢
- **禁止 `--dangerously-skip-permissions`** 等繞過安全機制的 flag

各專案 specific 紅線見 `<project>.md §2`（PT_BOT_SECRET / 路徑 traversal / DELETE 防 traversal 等）。

---

## §2. Commit / Code Style

- **Conventional Commits + 繁中**：`feat:` / `fix:` / `refactor:` / `docs:` / `security:` / `test:` / `chore:`
- **Branch**：`feature/<topic>` / `fix/<topic>` / `chore/<topic>` / `hotfix/<topic>`
- 每個功能獨立 commit；改完跑相關測試（pytest / npm test / 該專案測試指令）
- **不要猜測修改** — 先寫最小重現再改主程式
- 風格工具見各專案 `<project>.md`（Python: ruff + black 設定 `pyproject.toml` / JS: prettier + eslint / 等）

---

## §3. Review Tier — 兩軸（scope + risk）

> v2.2 修正：原 `T0-T3 + -semantic` 強合併改為兩軸，避免丟精度

### 3.1 Scope（檔案影響範圍）

| Tier | 觸發 |
|---|---|
| **T0** | 純文件 / 註解 / 格式 |
| **T1** | 單檔 < 50 行 + 有測試 / 一次性 script |
| **T2** | 跨模組 / scripts / tests / DB schema 異動 |
| **T3** | 系統核心檔（具體路徑見 `<project>.md §4`）|

### 3.2 Risk（動作後果嚴重度）

| Risk | 觸發 |
|---|---|
| `low` | UI 文案 / docs / non-semantic refactor |
| `semantic` | 跨層協調 / API 行為 / 認證 / 資料 schema |
| `contract` | events.jsonl / 認證契約 / 執行語意 / 不可逆操作 |

**強制升級規則**：events.jsonl / auth / execution contract / 不可逆動作 → 自動 `risk:contract`

### 3.3 標籤格式

`scope:T2 / risk:semantic` 或縮寫 `T2/semantic`

### 3.4 Review 流程對應

| scope×risk | 流程 |
|---|---|
| T0 + risk:low | 直接 commit |
| T1 + risk:low | self-review + 跑測試 |
| T2 + risk:low or semantic | Codex review（單 prompt）+ 模板 |
| T3 or risk:contract | Codex dual-prompt review（Sonnet+Opus 都 PASS 才 PASS）+ Morgan 人類確認 + Plan Mode |

### 3.5 Override

- Morgan prompt 開頭 `[T0]` ~ `[T3]` 強制 scope
- `[risk:low]` / `[risk:semantic]` / `[risk:contract]` 強制 risk
- `[skip-review]` 只准 T0/T1 + risk:low
- `[force-review]` 強制至少 T2 / risk:semantic

---

## §4. 雙主腦 Review 流程

> `.reviews/` 加進 `.gitignore` — review trail 不入版控（process artifact，跟 build log 同性質）

### 4.1 Flow

1. Claude 實作完 → 寫 `.reviews/REVIEW_REQUEST_<ts>_<topic>.md`（模板：`morgan-ai-rules/templates/review_request.template.md`）
2. 終端印「請執行: codex review .reviews/REVIEW_REQUEST_<ts>_<topic>.md」
3. Codex 產出 `.reviews/REVIEW_RESULT_<ts>_<topic>.md`（模板：`morgan-ai-rules/templates/review_result.template.md`）
4. Claude 讀 RESULT：
   - `APPROVE` → 程式碼端合併 commit；REQUEST/RESULT 可選擇歸檔到 `.reviews/archive/`
   - `REQUEST_CHANGES` → 修正後重出 v2（同 topic）
   - `NEED_DISCUSSION` → 設計分歧，Morgan 仲裁
5. 同 topic 超過 3 輪 → Morgan 仲裁

### 4.2 Codex 呼叫實務（全域）

- **必帶 prompt**：呼叫 codex 一律指向 `.reviews/REVIEW_REQUEST_*.md` 路徑或 inline content。**禁止裸跑** `codex review --uncommitted` 等無 prompt 命令（會得隱式 APPROVE 廢話）
- **必出結構化 RESULT**：codex 回應若不符 template 結構（無 verdict / severity / 發現位置）→ review 失敗，需重跑
- **bwrap 限制**：codex sandbox 不可讀檔/寫檔/跑 shell。所有 input 一律 stdin / inline，**不要叫 codex 自己 `cat` / `git diff` / `ls`**
- **角色限制**（v2.2 #28）：codex **只能**當 advisor / scoped-auditor，**禁止** unsupervised executor

---

## §5. Gotchas 踩坑記錄格式

各專案 `<project>.md §5` 用此格式：

```
- [YYYY-MM-DD] 問題簡述 + 根因
  → 規則：對應規則 + 規範修訂位置
```

每條 entry 必含日期、問題、根因、規則。新踩坑 → 立即補進對應 `<project>.md`（不過 schema_lint，因為踩坑紀錄是 append-only）。

---

## §6. Handoff & Stop_work — 雙層生命週期

> v2.2 修正：原「不同層級」改為「WIP buffer vs clean checkpoint」生命週期定義

### 6.1 兩層各自定義

| 層 | 位置 | 性質 | 何時寫 | 跨機？ |
|---|---|---|---|---|
| **handoff（WIP buffer）** | `~/.claude/handoff/<project>.md` 本機 | 髒、本機、可不一致、不對外 | session 任何時候 | ❌ 不跨機 |
| **stop_work（clean checkpoint）** | vault `projects/<X>/handoff/stop_work_<ts>.md` | 過 schema、跨機真相、對外承諾 | milestone（commit/PR/ADR/主題切換）、session end 強制 | ✅ 跨機 |

### 6.2 機制

- **SessionStart hook** (`~/.claude/hooks/session-handoff-read.sh`)：自動讀 handoff（本機）+ vault 最新 stop_work（跨機真相）注入 context
- **SessionEnd hook** (`~/.claude/hooks/session-handoff-write.sh`)：強制把 handoff 收尾 promote 成 stop_work，過 schema_lint
- 失敗 → 下次 session start 紅旗：「上次有未 promote 的 WIP」

### 6.3 衝突仲裁（誰是真相）

- 跨機接續：永遠用 stop_work（vault 真相）
- 同機 session 接力：先讀 stop_work 做 baseline，再用 handoff 補未 promote 部分
- 兩者衝突：stop_work 勝，handoff 顯示「本機舊狀態」提示
- handoff 帶 `wip_since`，stop_work 帶 `promoted_at`；`wip_since > promoted_at + 24h` → 紅旗

### 6.4 Stop_work schema 兩種

- **Minimal (hotfix)**：commit_hash / task_summary / next_step / emergency:true / wip_since
- **Full (milestone)**：完整見 `morgan-ai-rules/schema/stop_work_full.schema.json`

判斷：branch 開頭 `hotfix/*` 或 frontmatter `emergency: true` → 用 minimal；其他用 full。

### 6.5 Stop_work 範例（full milestone）

```markdown
---
status: current
valid_from: 2026-05-09T15:30:00Z
owner: vps_executor
project_id: pattern_trader
session_id: pt-phase12-impl-005
machine_id: vps-claw
wip_since: 2026-05-09T13:00:00Z
promoted_at: 2026-05-09T15:30:00Z
---

# pattern_trader stop_work — 2026-05-09T15:30:00Z

## 當前任務
QH-1 法人籌碼 backfill watermark 邊界測試

## 已動檔案
- src/quant_harness/backfill.py — 修 watermark 邊界
- tests/test_backfill.py — 加 5 個 case

## 下一步
1. 跑完整 backfill 驗證 7 個案場
2. 寫 ADR 記錄 watermark 設計

## 待解問題 / 卡點
無

## 參考
- Vault: SPEC_v1.1_§11_perf.md
- commits: abc123, def456
```

---

## §7. Compact Instructions（/compact 優先保留）

執行 `/compact` 或 auto-compact 時，**必須保留**以下類別：

1. 當前任務描述
2. 最近 5 個檔案修改摘要（path + 變動性質）
3. 未完成 TODO 與卡點
4. §1 安全紅線（整段）— 永遠不能掉
5. **`<project>.md §3` 領域規範**（callback 前綴 / 配色 / 樂觀鎖等專案領域知識）— 永遠不能掉
6. §3 Tier 判定結果（若本 session 已判定）
7. 本 session codex review verdict（若有）

---

## §8. Claude 專屬規範

### 8.1 角色

主腦 + 執行者：規劃、跨檔重構、檔案操作、Vault 文件維護。
預設 **Sonnet**。Opus 僅用於：需求模糊、架構決策、Debug 卡超過 3 輪。

### 8.2 Plan Mode 觸發

進 Plan Mode：
- T3 任務 / risk:contract 任務
- 多檔案重構 (≥ 3 檔)
- 架構決策、模糊需求、POC 探索

直接做（不進 Plan Mode）：
- T0 / T1 + risk:low 任務
- 已有 Vault 計畫文件，只負責執行（memory: feedback_autonomous_phase_execution）

### 8.3 Auto-accept

**可**：
- T0 / T1 + risk:low
- read-only 指令（test / lint / build / fetch）
- 規劃完備的 phase 內部技術決策

**禁**：
- T3 動工 / risk:contract 動工
- destructive (`reset --hard` / `push --force` / `rm -rf` / production restart)
- 跨機同步 (push / VPS pull / checkout)
- 改 git config / hooks / CI

### 8.4 自動派任（不需 Morgan 指示）

| 觸發 | 動作 |
|------|------|
| 完成任何實作後 | `codex review "<檔案> <審查重點>"` |
| Python 腳本 / 演算法 / 數值運算 | `codex exec "<完整 spec>"` |
| 業界資料 / 套件文件 / 最新 API | `gemini --prompt "<查詢>"` |

### 8.5 Web Claude 參謀 Handoff

參謀計畫文件：`{VAULT}/99-System/Runbook/morgan/14_<topic>_*.md`

SOP：
1. 讀全文，不掃標題
2. 列本輪要動的**檔案清單** + **指令清單**給 Morgan
3. 等 Morgan 說 GO 才動手
4. 動手前 echo 第一個指令的預期效果

### 8.6 收工流程（觸發：任務完成 / >20 輪 / 切換任務 / context >70%）

1. **寫 stop_work**（過 schema_lint，§6 規範）
2. `git add <具體檔案> && git commit -m "..." && git push`
3. 更新 Vault `CONTEXT.md` §「待接續任務」(≤ 150 行)
4. Vault `_REGISTRY.md` 頂部加一行：`YYYY-MM-DD | <電腦> | <檔案> | <摘要>`
5. 告知 Morgan 接續 prompt

> 注：AGENTS.md 是衍生物不需手動更新；codex 啟動時若需任務狀態，從 git log 推或 Morgan prompt 提供。

### 8.7 Memory（`~/.claude/projects/E--Code/memory/`）

- 寫：Morgan 糾正 / 跨機差異 / 非顯然事實
- 讀：任務開頭、Morgan 提到「之前」/「上次」時
- 不寫：當下進度（那是 Vault 的事）、可從 git log 推得的事實

---

## §9. Codex 專屬規範

### 9.1 角色

實作者 + reviewer。**不**做規劃、**不**做架構決策、**不**寫 Vault 文件。
**v2.2 #28 限制**：只能當 `advisor` 或 `scoped-auditor`，**禁止** unsupervised executor。

### 9.2 寫

- 給定 spec 的程式碼（單檔或小範圍跨檔）
- Python 腳本 / 演算法 / 數值邏輯
- review：讀 REVIEW_REQUEST.md → 產出 REVIEW_RESULT.md

### 9.3 不寫

- SPEC / CONTEXT / HANDOFF / Vault 文件
- 跨檔重構 (≥ 3 檔)
- 架構決策（模組分割、API 設計、DB schema）
- 不可逆動作（DROP / migrate / restart production）

### 9.4 Review 模式

收到 `.reviews/REVIEW_REQUEST_<ts>_<topic>.md`：
1. 讀 Tier、touched files、自評風險點
2. 看 git diff
3. 跑相關 tests
4. 產出 `REVIEW_RESULT_<ts>_<topic>.md`（模板）

**Verdict**：`APPROVE`（無 high/medium 問題）/ `REQUEST_CHANGES`（必修）/ `NEED_DISCUSSION`（設計分歧）
**Severity**：`high`（bug / security / 邏輯）/ `medium`（邊界 / 效能 / 命名）/ `low`（風格）

### 9.5 完成回報格式

```
[完成] <任務名稱>
- 修改檔案：<檔案列表>
- 主要變更：<一句話摘要>
- 測試結果：<pass/fail + 說明>
```

### 9.6 不該主動做

- git push / commit
- 改 `.agent-rules/` / `morgan-ai-rules/`
- 改 Vault 文件
- destructive 指令（`reset --hard` / `rm` / `restart` production）

### 9.7 任務狀態

任務狀態存 Vault `<project_path>/CONTEXT.md`。
**Codex 不讀 Vault**（bwrap 限制），需要 session 狀態時：
- 用 `git log --oneline -10` 推
- 或 Morgan prompt 提供
- 或 wrapper 預先 inline
