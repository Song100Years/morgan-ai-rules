# morgan-ai-rules

Central source of truth for AI governance rules.

## ⚠️ Do NOT push directly to main

This repo uses GitHub branch protection. All changes must go through PR.
Direct push to main will be rejected.

## Structure

| Path | Purpose |
|---|---|
| `docs/DESIGN.md` | v2.2 architecture (single source of truth) |
| `CHANGELOG.md` | Version history (v2 → v2.1 → v2.2) |
| `agents/guardian.md` | Guardian LLM prompt (bilingual: 中 for Morgan / EN for LLM) |
| `schema/RULES.md` | Schema lint rules (15 rules, hard gate) |
| `claude_md/_global.md` | (Phase 1) Common CLAUDE.md content abstracted from 3 projects |
| `hooks/` | (Phase 7) Cross-project hooks (handoff, verify_stop_work) |
| `templates/` | (Phase 1) Review request/result templates |
| `scripts/` | (Phase 2) render_claude_md.py / pull_rules.sh / wrappers |

## How to modify rules

1. Edit reference copy in this repo
2. Open PR (machine user accounts have write but not merge)
3. dual-review automation generates human summary on PR
4. Morgan reviews summary on dashboard
5. Morgan merges via admin token (Desktop only, never on VPS)
6. cron syncs reference copy to VPS sudo-only `/etc/guardian/prompt.md` after drift check

See `docs/DESIGN.md` for full architecture.

## Phase Status

- ✅ Phase 0: Initial structure (this commit)
- ⏳ Phase 1: Extract `_global.md` from 3 projects
- ⏳ Phase 2: schema_lint.py + guardian deployment
- ⏳ Phase 3: Machine user collaborators on AI Vault
- ⏳ Phase 4: AI Vault freeze + legacy migration
- ⏳ Phase 5: Shadow mode
- ⏳ Phase 6: Reject mode
- ⏳ Phase 7: verify_stop_work to all projects
- ⏳ Phase 8: .agent-rules import central
- ⏳ Phase 9: Half-year audit cron + hook self-verify

See `docs/PHASE_0_SOP.md` for current phase.
