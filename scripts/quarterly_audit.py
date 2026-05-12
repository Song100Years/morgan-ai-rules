#!/usr/bin/env python3
"""quarterly_audit.py - Phase 4 quarterly audit report skeleton.

Generates a markdown audit report covering:
  1. Recent INBOX scan statistics (counts only — trend analysis pending Phase 9)
  2. Archive expiry warnings (e.g. Phase 3 SSH key archive 30-day window)
  3. Machine topology drift vs MACHINE_USER_TOPOLOGY.md (Home PC only — cross-machine
     drift comparison pending Phase 9)
  4. Stale doc warnings (count only — expires_at hard check pending Phase 9)

Phase 4 scope: skeleton + dry run only. Phase 9 will:
  - Replace each section's stub with a real implementation
  - Wire to systemd timer / cron
  - Add hard expiry triggers + Morgan notifications

Output: markdown report to stdout, or `--write <path>` for QUARTERLY/audit_YYYY-QN.md.
JSON output reserved for future automation (Phase 5+ metric collection).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

VAULT_AI_GOV_REL = "99-System/AI_Governance"


def quarter_label(now: datetime) -> str:
    q = (now.month - 1) // 3 + 1
    return f"{now.year}-Q{q}"


# ----------------------------------------------------------------------------
# Section stubs (Phase 9 will replace with real logic)
# ----------------------------------------------------------------------------

def section_rule_stats(vault_root: Path) -> str:
    inbox = vault_root / VAULT_AI_GOV_REL / "INBOX"
    if not inbox.exists():
        return "_INBOX directory not found; skip._\n"
    scans = sorted(inbox.glob("scan_*.md"))
    if not scans:
        return "_No INBOX scans yet._\n"
    lines = [f"- found **{len(scans)}** INBOX scan files"]
    lines.append("- most recent 5:")
    for s in scans[-5:]:
        mt = datetime.fromtimestamp(s.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%d")
        lines.append(f"  - `{s.name}` (mtime {mt})")
    lines.append("")
    lines.append("_Phase 9: aggregate rule hit counts across quarter, trend analysis._")
    return "\n".join(lines) + "\n"


def section_archive_expiry(vault_root: Path) -> str:
    candidates = [
        Path.home() / ".ssh" / ".archived-phase3",
        vault_root / VAULT_AI_GOV_REL / "INBOX" / "_archive",
    ]
    now = datetime.now(timezone.utc)
    lines = []
    for path in candidates:
        if not path.exists():
            lines.append(f"- `{path}`: not present (skip)")
            continue
        items = list(path.iterdir())
        ages = []
        for it in items:
            try:
                age_days = (now - datetime.fromtimestamp(it.stat().st_mtime, tz=timezone.utc)).days
                ages.append((it.name, age_days))
            except OSError:
                continue
        ages.sort(key=lambda x: -x[1])
        lines.append(f"- `{path}`: {len(items)} items")
        for name, age in ages[:3]:
            flag = " ⚠️ >30d" if age > 30 else ""
            lines.append(f"  - `{name}` ({age}d old){flag}")
    lines.append("")
    lines.append("_Phase 9: hard 30-day trigger + Morgan notification on threshold breach._")
    return "\n".join(lines) + "\n"


def section_machine_topology(vault_root: Path) -> str:
    topo = vault_root / VAULT_AI_GOV_REL / "MACHINE_USER_TOPOLOGY.md"
    ssh_dir = Path.home() / ".ssh"
    lines = []
    if not topo.exists():
        lines.append("- MACHINE_USER_TOPOLOGY.md not found in Vault; skip")
    else:
        mt = datetime.fromtimestamp(topo.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%d")
        lines.append(f"- topology doc: `{topo.name}` (last modified {mt})")
    if not ssh_dir.exists():
        lines.append("- local `~/.ssh/` not found; skip drift check")
    else:
        pubs = sorted(ssh_dir.glob("*.pub"))
        lines.append(f"- local `~/.ssh/` pub keys: **{len(pubs)}**")
        for p in pubs[:10]:
            lines.append(f"  - `{p.name}`")
    lines.append("")
    lines.append("_Phase 9: full topology diff (Home + Office + NB + VPS) vs doc; flag drift._")
    return "\n".join(lines) + "\n"


def section_stale_docs(vault_root: Path) -> str:
    draft_count = 0
    sample = []
    for md in (vault_root / VAULT_AI_GOV_REL).rglob("*.md"):
        try:
            text = md.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if "status: draft" in text:
            draft_count += 1
            if len(sample) < 5:
                rel = md.relative_to(vault_root).as_posix()
                sample.append(rel)
    lines = [f"- drafts under `{VAULT_AI_GOV_REL}/`: **{draft_count}**"]
    for s in sample:
        lines.append(f"  - `{s}`")
    lines.append("")
    lines.append("_Phase 9: parse expires_at, flag past-due drafts as REJECT-worthy._")
    return "\n".join(lines) + "\n"


# ----------------------------------------------------------------------------
# Report assembly
# ----------------------------------------------------------------------------

def build_report(vault_root: Path, now: datetime) -> str:
    label = quarter_label(now)
    return f"""---
status: current
valid_from: {now.strftime('%Y-%m-%d')}
owner: morgan
project_id: ai_governance
generated_at: {now.isoformat(timespec='seconds')}
generator: quarterly_audit.py phase4-v1
audit_quarter: {label}
---

# Quarterly Audit — {label}

> Phase 4 骨架版本。實際檢查邏輯部分為 stub，Phase 9 體檢上線時補齊 + 排 cron。
> 本份報告主要驗證輸出格式 + 各 section 觸發路徑可用。

## 1. INBOX Scan Statistics

{section_rule_stats(vault_root)}

## 2. Archive Expiry Warnings

{section_archive_expiry(vault_root)}

## 3. Machine Topology Drift

{section_machine_topology(vault_root)}

## 4. Stale Doc Warnings

{section_stale_docs(vault_root)}

---

## 開放決策（Phase 9 補齊）

- INBOX scan rule hit by quarter trend (聚合過去 N 份 scan 規則命中分佈)
- Archive 30-day expiry hard trigger + Morgan notification (Phase 3 SSH archive 2026-06-11 第一次觸發)
- 全機 SSH 拓樸 vs MACHINE_USER_TOPOLOGY.md diff (Home + Office + NB + VPS)
- draft 過 expires_at 自動掃描升 REJECT
- Cron / systemd timer 排程上線
"""


def build_report_json(vault_root: Path, now: datetime) -> str:
    label = quarter_label(now)
    return json.dumps({
        "quarter": label,
        "generated_at": now.isoformat(timespec="seconds"),
        "audit_quarter": label,
        "generator": "quarterly_audit.py phase4-v1",
        "sections": ["rule_stats", "archive_expiry", "machine_topology", "stale_docs"],
        "schema_version": "phase4-v1",
        "note": "Phase 4 skeleton; per-section payload pending Phase 9.",
    }, ensure_ascii=False, indent=2)


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="quarterly_audit - Phase 4 skeleton")
    parser.add_argument("--root", required=True, type=Path,
                        help="Vault root (e.g. D:/OneDrive/VPS-Obsidian)")
    parser.add_argument("--output", choices=["markdown", "json"], default="markdown")
    parser.add_argument("--write", type=Path, default=None,
                        help="Write report to file (auto mkdir -p); default stdout")
    parser.add_argument("--dry-run", action="store_true",
                        help="Build report but do not emit / write")
    args = parser.parse_args(argv)

    if not args.root.is_dir():
        print(f"ERROR: --root not a directory: {args.root}", file=sys.stderr)
        return 1

    now = datetime.now(timezone.utc)
    report = (
        build_report(args.root, now)
        if args.output == "markdown"
        else build_report_json(args.root, now)
    )

    if args.dry_run:
        print(f"[quarterly_audit] dry-run; report built ({len(report)} bytes); format={args.output}",
              file=sys.stderr)
        return 0

    if args.write:
        args.write.parent.mkdir(parents=True, exist_ok=True)
        args.write.write_text(report, encoding="utf-8")
        print(f"[quarterly_audit] wrote {args.write}", file=sys.stderr)
    else:
        print(report)
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
