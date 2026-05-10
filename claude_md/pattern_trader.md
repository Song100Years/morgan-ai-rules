---
status: current
valid_from: 2026-05-09
owner: morgan
project_id: pattern_trader
---

# pattern_trader — 專案特化規範

> 共用規範見 `_global.md`（拼接時自動含）。
> 本檔僅放 pattern_trader 領域知識 + 特化規則。

## §1. 專案介紹

台股日頻型態操盤輔助系統（Dashboard + Telegram Bot + 資料管線）。

- **技術棧**：Python + Dash + SQLite + Telegram Bot
- **SPEC**：Vault `24_Finance/Project/pattern_trader/SPEC_v1.1*.md`
- **VPS**：`/home/morgan/projects/pattern_trader`，systemd `pattern-trader.service`
- **Port**：production 8050 (127.0.0.1)
- **Vault**：
  - Home/NB: `D:\OneDrive\VPS-Obsidian\24_Finance\Project\pattern_trader\`
  - Office: `E:\OneDrive\VPS-Obsidian\24_Finance\Project\pattern_trader\`

## §2. 專案特化安全紅線

（在 `_global.md §1` 通用 5 條之外的）

- **PT_BOT_SECRET 必須驗證**（Bot API 端點）

## §3. 領域規範

主要領域邏輯在 Vault `24_Finance/Project/pattern_trader/SPEC_v1.1*.md`，本檔不重複。

### 3.1 雙 DB 設計

- **Production DB**（`data/pattern_trader.db`）：業務表 `stock_daily` / `institutional_flow` / `screener_*`
- **QH DB**（`data/qh.db`）：quant_harness 進度追蹤 `backfill_watermark`

寫 backfill / spec / SDD 時必須**明指每張表所在 DB**，不嘗試統一兩個 DB。

## §4. Tier scope 觸發路徑（補充 _global §3.1）

| Tier | 觸發路徑 |
|---|---|
| T1 | 單檔 < 50 行 + 有對應測試 |
| T2 | `tests/` / `scripts/` / `quant_harness/` 內變動 |
| T3 | `src/*.py` 任何變動（**實盤路徑**）|

風格工具：ruff + black（設定見 `pyproject.toml`）；改完跑 pytest。

## §5. Gotchas

- [2026-05-02] POC 階段 B 計畫「`.reviews/` 進 git」，實作後改 `.gitignore`（commit bd43ee0）。
  根因：review 是 process artifact 不是 deliverable，跟 build 過程同性質。
  → 規則：見 `_global.md §4` `.reviews/` 不入版控

- [2026-05-03] 雙 DB 設計：production DB 裝業務表；qh DB 只裝 quant_harness 進度追蹤。
  根因：嘗試統一兩個 DB 會破壞 backfill watermark 邊界。
  → 規則：見 §3.1，撰寫 backfill / spec / SDD 時必須明指每張表所在 DB

- [2026-05-07] codex review 兩次出現「no blocker / no regression」隱式 APPROVE 廢話。
  根因：裸跑 `codex review --uncommitted` 沒帶 prompt，LLM 預設「找不到明顯 bug 就 APPROVE」。
  → 規則：見 `_global.md §4.2` codex 呼叫實務三條（必帶 prompt / 必出結構化 RESULT / bwrap 不可用）
