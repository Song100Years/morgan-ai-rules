---
status: current
valid_from: 2026-05-09
owner: morgan
project_id: pretest_system
---

# pretest_system — 專案特化規範

> 共用規範見 `_global.md`（拼接時自動含）。
> 本檔僅放 pretest_system 領域知識 + 特化規則。

## §1. 專案介紹

太陽能板 AR 鍍膜施工前的現場檢測 Web App + 後端報告產出。

- **技術棧**：Node.js (Express, port 3456) + Python (報告產出, python-docx) + Vanilla JS PWA + JSON 儲存
- **Repo**：GitHub private (Song100Years/pretest_system)
- **VPS**：morgan@76.13.180.174:/home/morgan/pretest/
- **前端 URL**：https://srv1336145.hstgr.cloud/tools/pretest.html
- **主要檔案**：`pretest.html` / `upload-server.js` / `generate-report.py` / `sync-organized.sh` / `export-pretest-data.py`
- **架構文件**：`docs/RUNBOOK.md`（API / 踩坑 / 部署細節）
- **Vault**：`{VAULT}/21_Projects/加加減減/10_Projects/pretest_system/CONTEXT.md`

## §2. 專案特化安全紅線

- **DELETE 端點必須防 path traversal**（強化 `_global.md §1` 通用輸入驗證）

## §3. 領域規範

- **`except Exception` / `catch` 必須 print/log 錯誤**，禁 silent return None / silent fallback
  （codex 反模式案例：routes 內 `catch{}` 已 review 退過）
- **records.json 寫入用 atomic + lockfile**（`proper-lockfile`）
- **樂觀鎖機制**：`_baseVersion` 欄位級合併，**禁止** `{...existing, ...new}` 整體覆寫
- **軟刪用 tombstone**（`_deletedAt`），**禁止** `delete obj[key]`

## §4. Tier scope 觸發路徑（補充 _global §3.1）

| Tier | 觸發路徑 |
|---|---|
| T1 | 單檔 < 50 行 + 一次性 script |
| T2 | `scripts/` / `tests/` / sync 腳本變動 |
| T3 | `upload-server.js` / `pretest.html` / `generate-report.py` 任何變動 |

## §5. Gotchas

- [2026-04-23] construction-record-routes.js 從另一專案 embedded 進 pretest（require 進 upload-server.js），10 天未 commit 也未廢棄，靠 production 持續跑著未入版控的程式碼。
  根因：file-level require 跨專案 embed 喪失版控可見性。
  → 規則：跨專案的程式碼共用一律走獨立 service + HTTP 介面（或抽成 npm package），**禁止 file-level require 跨專案 embed**

- [2026-04-30] iOS PWA cache 問題：`/api/version` mtime + meta cache-control + checkAppVersion 已實作自動 reload，仍需冷啟動手動清一次。
  根因：iOS Safari PWA cache 異於桌面 browser。
  → 規則：PWA 改動發版時主動告知客戶 hard reload

- [2026-04-21] export-pretest-data.py 漏解 wrapper 導致 CSV 一個月停滯在 494 bytes，v8.7 commit message 聲稱修過但實際未進 commit。
  根因：commit message 跟實際 diff 脫鉤，沒當日驗證。
  → 規則：bug fix 後當日跑一次驗證，**不靠 commit message 證明**
