---
status: current
valid_from: 2026-05-09
owner: morgan
project_id: ai_governance
---

# Phase 0 SOP — 建立 morgan-ai-rules 中央規則 repo

> Phase 0 約 1-2 天，Morgan 親自做的部分需 30-60 分鐘
> 完成後進 Phase 1（從三專案 _shared.md 抽出 `_global.md`）
> 整體 Phase plan 見 [DESIGN.md §4](DESIGN.md)

---

## 必要前提

- gh CLI 已登入 morgan-admin 帳號（Song100Years）
- 本機 SSH key 已存在
- Vault 內 v2.2 設計文件已就緒（DESIGN.md / CHANGELOG.md / agents/guardian.md / schema/RULES.md）✅ 2026-05-09 已備齊

---

## Phase 0 步驟（按順序）

### Step 1：建 morgan-ai-rules GitHub private repo

```powershell
gh repo create Song100Years/morgan-ai-rules --private --description "Central source of truth for AI governance rules"
```

**驗證**：`gh repo view Song100Years/morgan-ai-rules`

---

### Step 2：建 4 個 machine user GitHub 帳號

> 此步必須親自在 GitHub web 做（gh CLI 無法建帳號）

| Username | Email | 用途 |
|---|---|---|
| `morgan-ai-executor` | morgan-ai-executor@&lt;your-domain&gt; | VPS executor 用 |
| `morgan-ai-advisor` | morgan-ai-advisor@&lt;your-domain&gt; | advisor 角色用 |
| `morgan-ai-auditor` | morgan-ai-auditor@&lt;your-domain&gt; | auditor 角色用 |
| `morgan-admin` | （你已有的 Song100Years） | 已有，不需新建 |

每個 machine user 帳號：
1. 註冊 GitHub 帳號（建議用 gmail+alias 管理多 email）
2. 啟用 2FA（Authenticator app）
3. 為各 machine user **分別**產生 SSH key（不要共用）：
   ```bash
   ssh-keygen -t ed25519 -C "morgan-ai-executor" -f ~/.ssh/morgan_ai_executor
   ssh-keygen -t ed25519 -C "morgan-ai-advisor"  -f ~/.ssh/morgan_ai_advisor
   ssh-keygen -t ed25519 -C "morgan-ai-auditor"  -f ~/.ssh/morgan_ai_auditor
   ```
4. 把 public key 加進對應 GitHub 帳號 Settings > SSH keys

**注意**：machine user 帳號平時不互動登入，只用來 SSH 跟 GitHub API 互動。

---

### Step 3：morgan-admin 建 fine-grained PAT（**只在 Desktop**，永不放 VPS）

1. GitHub > Settings > Developer settings > Personal access tokens > Fine-grained tokens
2. Generate new token：
   - **Name**: `morgan-admin-rules-merge`
   - **Expiration**: 90 days（calendar 設 60 天提醒 rotate）
   - **Resource owner**: Song100Years
   - **Repository access**: Only select repositories → `morgan-ai-rules`
   - **Permissions**:
     - `Contents: Read and write`
     - `Pull requests: Read and write`
     - `Metadata: Read`
3. 複製 token，存到 Desktop 的 password manager
4. **永不放 VPS / 永不寫進任何 repo**

---

### Step 4：Clone repo + 跑 init script

```powershell
cd D:\workspace
git clone git@github.com:Song100Years/morgan-ai-rules.git
cd morgan-ai-rules

# 跑 init script (從 Vault 搬 v2.2 設計文件進來 + 建 placeholder)
bash D:/OneDrive/VPS-Obsidian/99-system/AI_Governance/scripts/02_init_repo_structure.sh
```

**驗證**：repo 內出現以下結構：

```
morgan-ai-rules/
├── README.md
├── CHANGELOG.md
├── .gitignore
├── docs/
│   └── DESIGN.md
├── agents/
│   └── guardian.md
├── schema/
│   ├── RULES.md
│   └── tests/.gitkeep
├── claude_md/.gitkeep
├── hooks/.gitkeep
├── templates/.gitkeep
└── scripts/.gitkeep
```

---

### Step 5：設 branch protection

```powershell
bash D:/OneDrive/VPS-Obsidian/99-system/AI_Governance/scripts/01_setup_branch_protection.sh
```

這會跑 `gh api` 設定 morgan-ai-rules main branch：
- disable direct push
- require linear history
- require pull request before merging
- required status checks: `schema_lint`, `guardian_check`（即使 workflow 還沒實作，先佔位）
- `enforce_admins: false`（admin 可 bypass，給緊急 force-revert 用）
- disable force push / deletion

**驗證**：

```powershell
gh api /repos/Song100Years/morgan-ai-rules/branches/main/protection
```

應該回 200 OK 含上述設定。

---

### Step 6：第一個 commit + push（透過 PR）

init script 已 commit 在 `chore/initial-structure` branch。現在開 PR + merge：

```powershell
cd D:\workspace\morgan-ai-rules
git push -u origin chore/initial-structure

gh pr create --title "chore: initial v2.2 structure" --body "Phase 0 init - 建立 morgan-ai-rules 初始結構含 v2.2 設計文件"

# 因為 schema_lint/guardian workflow 還沒寫，required status checks 會 pending
# 用 admin bypass merge（這是 Phase 0 的特例，之後不該用）
gh pr merge <PR#> --merge --admin
```

---

### Step 7：確認 Phase 0 完成

```
✅ morgan-ai-rules private repo 存在 GitHub
✅ 4 個 machine user GitHub 帳號存在
✅ 4 把 SSH key（其中 3 把對應 machine user）
✅ morgan-admin PAT 在 Desktop 安全保存
✅ main branch protection 啟用
✅ repo 內有 v2.2 設計文件（docs/DESIGN.md, CHANGELOG.md, agents/guardian.md, schema/RULES.md）
✅ 第一個 commit 透過 PR + admin merge 完成
```

完成 → 進 Phase 1（抽 `_global.md`，DESIGN.md §4 列出）。

---

## 風險 / Gotchas

- **Step 2 帳號管理**：建議建一個 `~/.morgan_ai_accounts.md`（**不入 git**）記錄 4 個 machine user 的 email / SSH key path / 2FA backup code
- **Step 3 PAT expiration**：calendar 設 60 天提醒 rotate；過期會自動 90 天無回應 → P0（v2.2 #14 token 監測）
- **Step 5 enforce_admins: false**：是預期不是漏洞，留給緊急 force-revert（v2.2 #31）
- **Step 6 admin bypass merge**：Phase 0 唯一一次容許，之後所有 PR 都要過 schema_lint + guardian check 才 merge

---

## 後續 Phase 提醒

| Phase | 名稱 | 依賴 Phase 0 | 預計時間 |
|---|---|---|---|
| 1 | 從三專案 _shared.md 抽 `_global.md` | ✅ | 1 天 |
| 2 | 寫 schema_lint + guardian deploy VPS sudo-only | ✅ + Phase 1 | 3 天 |
| 3 | 4 machine user 加 AI Vault collaborator + token rotation 排程 | ✅ + Phase 2 | 0.5 天 |
| 4 | AI Vault freeze + legacy 分批 mv | ✅ + Phase 3 | 2 天 |
| 5 | shadow mode 啟動 | Phase 4 | 7-14 天 |
| 6 | metric-driven 切 reject | Phase 5 | – |
| 7 | verify_stop_work 推廣三業務專案 | Phase 5 | 2 天 |
| 8 | 各專案 .agent-rules import 中央 | Phase 5 | 5-7 天 |
| 9 | 半年體檢 cron + hook 自驗自動化 | Phase 6,7,8 | 1 天 |

完整細節見 DESIGN.md §4。
