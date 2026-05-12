#!/usr/bin/env python3
"""vault_scan.py - Phase 4 Vault passive scan (read-only).

Walks --root for *.md files, runs schema_lint(mode="scan") on each, and
emits violations in either JSON (metric-friendly) or Morgan-readable
markdown (INBOX format).

Design (PHASE_4 prompt sec A):
  - Read-only. Does not modify any file under --root.
  - Calls schema_lint.lint(mode="scan"); internally skips R1/R2/R8/R10/R17
    (write-time-only concepts).
  - Two output formats: json for downstream Phase 5 metric, markdown for
    99-system/AI_Governance/INBOX/scan_YYYY-MM-DD.md.
  - --limit + --exclude let Morgan control first-run noise.
  - --dry-run suppresses payload; only summary to stderr.

Exit codes:
  0 - scan completed (regardless of violation count)
  1 - bad CLI args or unreadable --root
  2 - internal error
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator, Optional

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import schema_lint  # noqa: E402  - sys.path tweak required first


SCRIPT_VERSION = "phase4-v1"

# Phase 4 (ii) auto-exclude: vault_scan's own output dirs. These contain quoted
# rule-language inside violation messages and would otherwise self-trigger R16
# on subsequent scans. Limited to INBOX/QUARTERLY only — audit_logs/, handoff/
# may contain real violations and stay scanned (per Phase 4 review feedback).
# Override via --include-meta when validating scan output format itself.
DEFAULT_META_EXCLUDES: tuple[str, ...] = (
    "99-System/AI_Governance/INBOX/",
    "99-system/AI_Governance/INBOX/",
    "99-System/AI_Governance/QUARTERLY/",
    "99-system/AI_Governance/QUARTERLY/",
)


# ----------------------------------------------------------------------------
# File discovery + filter
# ----------------------------------------------------------------------------

def iter_md_files(root: Path,
                  exclude_patterns: list[str]) -> Iterator[tuple[Path, str]]:
    """Yield (abs_path, vault_relative_posix) for every *.md under root.

    Excludes apply to the vault-relative posix path. Patterns containing
    glob metacharacters (* ? [) use fnmatch; otherwise substring match.
    """
    for abs_path in sorted(root.rglob("*.md")):
        try:
            rel = abs_path.relative_to(root).as_posix()
        except ValueError:
            continue
        if _match_any_exclude(rel, exclude_patterns):
            continue
        yield abs_path, rel


def _match_any_exclude(rel_path: str, patterns: Iterable[str]) -> bool:
    for pat in patterns:
        if any(ch in pat for ch in ("*", "?", "[")):
            if fnmatch.fnmatch(rel_path, pat):
                return True
        elif pat in rel_path:
            return True
    return False


def _file_mtime_utc(p: Path) -> Optional[str]:
    try:
        ts = p.stat().st_mtime
    except OSError:
        return None
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ----------------------------------------------------------------------------
# Per-file scan
# ----------------------------------------------------------------------------

def scan_one(abs_path: Path, rel_path: str) -> dict:
    """Read file + run schema_lint(mode='scan'). Returns enriched verdict dict.

    ERROR verdicts (READ_FAILED / ENCODING_FAILED) are surfaced as violations
    so file-system / encoding issues do not silently disappear.
    """
    mtime = _file_mtime_utc(abs_path)
    try:
        content = abs_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        return {
            "verdict": "ERROR",
            "error_code": "ENCODING_FAILED",
            "suggested_fix": f"file not utf-8 readable: {e}",
            "fail_at_rule": "INPUT",
            "path": rel_path,
            "file_mtime": mtime,
        }
    except OSError as e:
        return {
            "verdict": "ERROR",
            "error_code": "READ_FAILED",
            "suggested_fix": f"cannot read file: {e}",
            "fail_at_rule": "INPUT",
            "path": rel_path,
            "file_mtime": mtime,
        }

    req = {
        "writer_role": None,
        "writer_engine": None,
        "target_path": rel_path,
        "operation": "update",
        "content": content,
        "branch": None,
        "morgan_ai_rules_root": None,
        "previous_frontmatter": None,
        "vault_files": None,
    }
    result = schema_lint.lint(req, mode="scan")
    result["path"] = rel_path
    result["file_mtime"] = mtime
    return result


def collect_violations(root: Path, *, exclude: list[str],
                       limit: Optional[int]) -> tuple[list[dict], int]:
    """Walk + scan; return (non-PASS results, total files scanned)."""
    violations: list[dict] = []
    seen = 0
    for abs_path, rel_path in iter_md_files(root, exclude):
        if limit is not None and seen >= limit:
            break
        seen += 1
        result = scan_one(abs_path, rel_path)
        if result.get("verdict") != "PASS":
            violations.append(result)
    return violations, seen


# ----------------------------------------------------------------------------
# Rendering
# ----------------------------------------------------------------------------

def _counters(violations: list[dict]) -> tuple[Counter, Counter]:
    by_rule = Counter(v.get("fail_at_rule", "?") for v in violations)
    by_verdict = Counter(v.get("verdict", "?") for v in violations)
    return by_rule, by_verdict


def render_markdown(violations: list[dict], *, root: Path, scan_dt: datetime,
                    files_seen: int,
                    user_exclude: list[str], auto_exclude: list[str],
                    limit: Optional[int]) -> str:
    """INBOX markdown — zh-TW, scenario-style, checkbox decision tracking."""
    by_rule, by_verdict = _counters(violations)
    rule_summary = ", ".join(f"{r} x {n}" for r, n in by_rule.most_common()) or "(none)"
    verdict_summary = " / ".join(f"{k} {v}" for k, v in by_verdict.most_common()) or "(none)"

    parts: list[str] = []
    parts.append("---")
    parts.append("status: current")
    parts.append(f"valid_from: {scan_dt.strftime('%Y-%m-%d')}")
    parts.append("owner: morgan")
    parts.append("project_id: ai_governance")
    parts.append(f"generated_at: {scan_dt.strftime('%Y-%m-%dT%H:%M:%SZ')}")
    parts.append(f"generator: vault_scan.py {SCRIPT_VERSION}")
    parts.append("---")
    parts.append("")
    parts.append(f"# Vault 掃描收件匣 - {scan_dt.strftime('%Y-%m-%d')}")
    parts.append("")
    parts.append("> 由 `scripts/vault_scan.py` 唯讀掃描產生 (Phase 4 被動掃描補抓 hook 漏掉的 ~15%)")
    parts.append("> 看完逐筆拍 `[ ]` -> `[x]`; 保留 90 天後 mv 到 `_archive/`")
    parts.append("")
    parts.append("## 摘要")
    parts.append("")
    parts.append(f"- 掃描根: `{root}`")
    parts.append(f"- 使用者排除規則: {user_exclude if user_exclude else '(none)'}")
    parts.append(f"- 自動排除 (INBOX/QUARTERLY): {'是' if auto_exclude else '否 (--include-meta)'}")
    parts.append(f"- limit: {limit if limit is not None else '(unlimited)'}")
    parts.append(f"- 檢查檔數: {files_seen}")
    parts.append(f"- 違規: {len(violations)} 筆 ({verdict_summary})")
    parts.append(f"- 規則命中: {rule_summary}")
    parts.append("")
    parts.append("## 違規清單")
    parts.append("")

    if not violations:
        parts.append("(無違規)")
        parts.append("")
    else:
        for i, v in enumerate(violations, start=1):
            parts.append(f"### {i}. `{v.get('path', '?')}`")
            parts.append("")
            parts.append(f"- 規則: {v.get('fail_at_rule', '?')} - `{v.get('error_code', '?')}`")
            parts.append(f"- 裁決: {v.get('verdict', '?')}")
            msg = v.get("suggested_fix") or v.get("human_summary_zh") or "(no message)"
            parts.append(f"- 訊息: {msg}")
            mtime = v.get("file_mtime")
            if mtime:
                parts.append(f"- 檔 mtime: {mtime}")
            parts.append("- 決策: [ ] 已處理 (打勾代表已看過 / 已決策; 未修正項下次 scan 仍會檢出)")
            parts.append("")

    parts.append("## 怎麼處理")
    parts.append("")
    parts.append("1. 逐筆讀 `規則` / `訊息`, 判斷該修還是接受現況")
    parts.append("2. 該修 -> 改 Vault 對應檔; 接受 -> 在「決策」打勾")
    parts.append("3. 90 天到期 -> 整份 mv 到 `_archive/` (Phase 9 統一清)")
    parts.append("4. 未修正項在下次 scan 仍會出現, 不會漏")
    parts.append("")
    return "\n".join(parts)


def render_json(violations: list[dict], *, root: Path, scan_dt: datetime,
                files_seen: int,
                user_exclude: list[str], auto_exclude: list[str],
                limit: Optional[int]) -> str:
    by_rule, by_verdict = _counters(violations)
    payload = {
        "scan_meta": {
            "scan_date": scan_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "vault_root": str(root),
            "user_exclude_patterns": list(user_exclude),
            "auto_exclude_patterns": list(auto_exclude),
            "limit": limit,
            "files_seen": files_seen,
            "violations_count": len(violations),
            "rules_summary": dict(by_rule),
            "verdict_summary": dict(by_verdict),
            "generator_version": SCRIPT_VERSION,
        },
        "violations": violations,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------

def _parse_args(argv: Optional[list]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="vault_scan - Phase 4 read-only Vault passive scan",
    )
    p.add_argument("--root", required=True,
                   help="Vault root directory (e.g. D:/OneDrive/VPS-Obsidian)")
    p.add_argument("--output", choices=("json", "markdown"), default="markdown",
                   help="Payload format (default: markdown)")
    p.add_argument("--dry-run", action="store_true",
                   help="Scan + summary to stderr only; suppress payload")
    p.add_argument("--limit", type=int, default=None,
                   help="Stop after scanning N .md files (default: unlimited)")
    p.add_argument("--exclude", action="append", default=[],
                   help="Skip paths matching pattern (substring or fnmatch glob); repeatable")
    p.add_argument("--write", default=None,
                   help="Write payload to this path instead of stdout")
    p.add_argument("--include-meta", action="store_true",
                   help=("Include vault_scan's own output dirs "
                         "(INBOX/, QUARTERLY/) in scan. Default excludes them "
                         "to avoid self-trigger noise. Use when validating "
                         "scan output format itself."))
    return p.parse_args(argv)


def main(argv: Optional[list] = None) -> int:
    args = _parse_args(argv)

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"[vault_scan] --root not a directory: {root}", file=sys.stderr)
        return 1

    if args.limit is not None and args.limit <= 0:
        print(f"[vault_scan] --limit must be positive; got {args.limit}", file=sys.stderr)
        return 1
    limit: Optional[int] = args.limit

    excludes = list(args.exclude)
    auto_excludes: list[str] = []
    if not args.include_meta:
        auto_excludes = list(DEFAULT_META_EXCLUDES)
        excludes.extend(auto_excludes)

    scan_dt = datetime.now(timezone.utc)
    violations, files_seen = collect_violations(
        root, exclude=excludes, limit=limit,
    )

    summary = (
        f"[vault_scan] scanned {files_seen} files; "
        f"{len(violations)} violations; "
        f"format={args.output}; dry_run={args.dry_run}"
    )
    print(summary, file=sys.stderr)

    if args.dry_run:
        return 0

    if args.output == "markdown":
        payload = render_markdown(
            violations, root=root, scan_dt=scan_dt,
            files_seen=files_seen,
            user_exclude=list(args.exclude),
            auto_exclude=auto_excludes,
            limit=limit,
        )
    else:
        payload = render_json(
            violations, root=root, scan_dt=scan_dt,
            files_seen=files_seen,
            user_exclude=list(args.exclude),
            auto_exclude=auto_excludes,
            limit=limit,
        )

    if args.write:
        target = Path(args.write)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(payload, encoding="utf-8", newline="\n")
        print(f"[vault_scan] wrote {target}", file=sys.stderr)
    else:
        if hasattr(sys.stdout, "reconfigure"):
            try:
                sys.stdout.reconfigure(encoding="utf-8")
            except Exception:
                pass
        sys.stdout.write(payload)
        if not payload.endswith("\n"):
            sys.stdout.write("\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
