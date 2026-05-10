---
status: current
valid_from: 2026-05-09
owner: morgan
project_id: solar_dashboard
---

# solar_dashboard — 專案特化規範

> 共用規範見 `_global.md`（拼接時自動含）。
> 本檔僅放 solar_dashboard 領域知識 + 特化規則。

## §1. 專案介紹

太陽能案場發電追蹤分析平台（per-site SQLite + Dash + Flask Web）。

- **技術棧**：Python 3.12 + Dash + Plotly + dash-bootstrap-components + sqlite3
- **部署**：VPS `/home/morgan/projects/solar_dashboard`，systemd `solar-dashboard.service`
- **Port**：VPS production 8060；本機開發 8050；UI 最小重現腳本用 8051（**避開 production**）
- **啟動**：`start.sh`（cd + venv + source .env + python web/app.py）
- **資料結構**：`sites/<案場名稱>/db/power_data.db` 一案場一 DB（schema 跨案場一致）
- **主要表**：`PlantDailyData`（廠級日資料）、`DailyPowerData`（string 級日資料）
- **配置**：`global_config/sites_registry.json` / `global_config/export_presets.json`
- **重要文件**：`docs/DB_SPEC.md` / `docs/NEW_SITE_RUNBOOK.md`
- **Vault**：`{VAULT}/21_Projects/加加減減/10_Projects/solar_dashboard/CONTEXT.md`

## §2. 專案特化安全紅線

- **路徑 traversal 防護**：接受 site name 參數時，白名單比對 `sites_registry.json`，不准 `../` 或絕對路徑

## §3. 領域規範

### 3.1 Dash callback ID 命名前綴

| 前綴 | 用途 |
|------|------|
| `plant-pg-` | 廠級頁面 callback |
| `plant-graph-` | 廠級圖表 callback |
| `str-` | string 級頁面 callback |
| `cfg-` | 配置頁 callback |
| `det-` | detail 頁 callback |
| `ns-` | new-site / 新案場 callback |

新增 callback **必須**用上述前綴避免 ID 衝突。

### 3.2 配色與用語

- 層膜前（coating 之前）：`#868e96`（灰）
- 層膜後（coating 之後）：`#dc3545`（紅）
- 層膜日（coating 當日）：`#28a745`（綠）
- 用語：**「鍍膜」→「層膜」**（專案內部統一用「層膜」）

### 3.3 例外處理

- **`except Exception` 必須 print 錯誤**，禁 silent return None
- 連鎖呼叫的中間層也要 raise / log，不准吞掉

### 3.4 Per-site DB 設計

每個案場一個 `sites/<案場>/db/power_data.db`，**不要試圖統一成單一 DB**。Schema 跨案場一致，但實體分離方便逐廠維護 / 備份 / 重灌。

寫 query 時**先用 `sites_registry.json` 解析路徑**，不要 hardcode site name 對 DB 路徑。

## §4. Tier scope 觸發路徑（補充 _global §3.1）

| Tier | 觸發路徑 |
|---|---|
| T1 | 單檔 < 50 行 + 純 plot/分析腳本（`plot_*.py` / 一次性 script）|
| T2 | `scripts/` / `tests/` / 資料 ETL 腳本 / DB schema 異動 |
| T3 | `web/*`（Dash app / API endpoint / DB query / callback）|

修法：先寫最小重現腳本（port 8051）→ 確認可行 → 再改主程式。

## §5. Gotchas

- [2026-05-03] per-site DB 設計：每個案場一個 `sites/<案場>/db/power_data.db`，**不要試圖統一**。
  根因：跨案場資料量差異大、維護視窗不同、備份策略獨立。
  → 規則：見 §3.4，先用 `sites_registry.json` 解析路徑

- [2026-05-03] `sites/` 已 `.gitignore`（生產資料，大檔）。
  根因：commit 大檔會炸 repo + 暴露案場資料。
  → 規則：不要 commit 案場資料；不要在 LLM context 硬塞案場 dump；需要時直接從 VPS 讀 DB

- [2026-05-03] 從舊 CLAUDE.md 遷移時保留：callback 前綴規範、配色、「鍍膜→層膜」用語、`except Exception` print 規則。
  根因：這些是專案領域知識，違反會踩既有設計。
  → 規則：見 §3
