# CHANGELOG

## v2.2 — 2026-05-09

兩家 LLM (Claude + Codex) 第二輪 review 補強。**verdict 預期 8/10 撐 12 個月**。

### 修正前一輪拍板（兩家共識反駁）

- **#25 修正**：handoff/stop_work 從「不同層級」改為「**WIP buffer vs clean checkpoint**」生命週期定義；session end hook 強制 promote
- **#21 修正**：Tier 從 `T0-T3 + -semantic` 強合併改為**兩軸**（scope T0-T3 + risk low/semantic/contract）
- **#20 修正**：verify_stop_work 推廣分 **minimal receipt（hotfix）vs full milestone**

### 新增（兩家 review 共識補強，#27-#42）

- 中央離線 vendored snapshot（submodule pin）+ 規則類 PR fail closed
- codex 角色限制：advisor / scoped-auditor only
- guardian outage fail closed + label
- build artifact 帶 commit hash + machine_id + UTC timestamp
- revert 走 admin bot 特權路徑
- timestamp 統一 UTC
- T3 / risk:semantic 雙 prompt 都 PASS 才 PASS
- ADR superseded_by 鏈完整性 + 互斥鎖
- multi-machine session lock
- draft expires_at + promote 過 strict
- hook installation 自驗
- guardian sudo-only vs repo copy drift 檢查
- NEEDS_HUMAN 全刪禁止
- shadow mode CI 紅黃燈
- 半年體檢 cron
- Phase 8 改 5-7 天 + shadow

---

## v2.1 — 2026-05-09

整合既有 CLAUDE.md / .agent-rules / hook 機制，發現 60-70% 已有雛形實作。

### 新增 9 條（#18-#26）

- 三專案 _shared.md §2-§9 抽到中央 `_global.md`
- `.agent-rules/_shared.md` 改成 import 中央
- verify_stop_work 從 multi-agent 推廣到所有專案
- T0-T3 + -semantic flag 統一分級（**v2.2 已修正成兩軸**）
- VPS 建立 `~/.claude/CLAUDE.md`
- review templates 統一中央
- codex bwrap 限制寫進 guardian writer 規則
- handoff（本機）+ stop_work（vault）兩層並存（**v2.2 已修正成生命週期定義**）
- Gotchas 格式列入中央規範

---

## v2 — 2026-05-09

兩家 LLM 第一輪 review 共識 17 條。Verdict 6-7/10。

### 共識核心（#1-#17）

- guardian prompt 物理隔離（VPS sudo-only）
- 兩層 gate（schema_lint + LLM guardian）
- NEEDS_HUMAN 分級
- rules repo branch protection
- shadow → reject metric-driven
- writer_role 4 種抽象
- frontmatter 5 欄
- GitHub PR-only flow（取代 gitea）
- shadow mode AI client-side 視 warning 為失敗
- prompt injection 防護
- legacy archive 分批 mv
- 3 按鈕級 runbook 內建在 dashboard
- dashboard 自驗證
- token / deploy key 分離
- legacy promote 啟發式
- warning 含 suggested_fix
- stop_work 觸發點擴大

---

## 失敗根因（為什麼需要這次升級）

過去半年治理規則改了 N 版都失敗，根因：

1. 規則只是文字告示牌，AI 自由判斷遵不遵守
2. 沒有單一執行者
3. 規則寫在 CLAUDE.md / Vault，AI 可改可忽略
4. 多環境同步靠手動，4 地不一致
5. Morgan 非技術背景，無法及時發現漂移
6. 發現混亂後再寫一版規則，根因（無強制執行）沒解

v2.2 的結構性差異：

- 規則寫在 hook + agent prompt + branch protection（物理）
- AI 物理上無 push 權限到 main
- Morgan 看儀表板 + 仲裁，不審 diff
- 規則靠 git submodule pin 跨機同步
