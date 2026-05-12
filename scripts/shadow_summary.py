#!/usr/bin/env python3
"""shadow_summary.py - Phase 5 shadow mode metric report generator.

Reads vault_governance_shadow.jsonl (one record per non-PASS write that
shadow mode let through) and produces a Morgan-readable markdown / JSON
report covering:
  1. Window 統計 (count / verdict / mode / date span / skipped corrupt lines)
  2. Top 10 rules by hit count
  3. Top 10 file paths by hit count
  4. By-day distribution

Phase 5 scope: local hook output only. No cron, no rotation, no cross-
machine merge — those live in Phase 6/9.

Imports limited to Python stdlib (per Phase 5 補3, Phase 4 Office PC pyyaml
incident). No pyyaml / pandas / requests.

Exit codes:
  0 - report generated (even if log empty / missing)
  1 - bad CLI args / unreadable log target
  2 - internal error
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional

SCRIPT_VERSION = "phase5-v1"
DEFAULT_LOG_PATH = os.path.expanduser("~/.claude/logs/vault_governance_shadow.jsonl")

WINDOW_DELTAS: dict[str, Optional[timedelta]] = {
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
    "all": None,
}


# ----------------------------------------------------------------------------
# Log parse
# ----------------------------------------------------------------------------

def _parse_timestamp(ts) -> Optional[datetime]:
    """Tolerant UTC ISO8601 parse. Returns None on any failure."""
    if not isinstance(ts, str):
        return None
    raw = ts.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None
    return dt.astimezone(timezone.utc)


def parse_log(log_path: Path) -> tuple[list[dict], int]:
    """Read jsonl; tolerate corrupt lines (count them, skip the line).

    Returns (records, skipped_line_count). Missing file -> ([], 0).
    """
    records: list[dict] = []
    skipped = 0
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    skipped += 1
    except FileNotFoundError:
        return [], 0
    return records, skipped


def filter_window(records: list[dict], window: str,
                  now: datetime) -> list[dict]:
    """Filter records to within window. 'all' returns a copy."""
    delta = WINDOW_DELTAS.get(window)
    if delta is None:
        return list(records)
    cutoff = now - delta
    out: list[dict] = []
    for r in records:
        ts = _parse_timestamp(r.get("timestamp", ""))
        if ts is None:
            continue
        if ts >= cutoff:
            out.append(r)
    return out


# ----------------------------------------------------------------------------
# Aggregations
# ----------------------------------------------------------------------------

def _rule_counter(records: Iterable[dict]) -> Counter:
    return Counter(r.get("fail_at_rule", "?") for r in records)


def _path_counter(records: Iterable[dict]) -> Counter:
    return Counter(r.get("target_path", "?") for r in records)


def _verdict_counter(records: Iterable[dict]) -> Counter:
    return Counter(r.get("verdict", "?") for r in records)


def _mode_counter(records: Iterable[dict]) -> Counter:
    return Counter(r.get("mode", "?") for r in records)


def _by_day(records: Iterable[dict]) -> Counter:
    out: Counter = Counter()
    for r in records:
        ts = _parse_timestamp(r.get("timestamp", ""))
        if ts is None:
            continue
        out[ts.strftime("%Y-%m-%d")] += 1
    return out


def _date_span(records: Iterable[dict]) -> tuple[Optional[datetime], Optional[datetime]]:
    ts_list = []
    for r in records:
        ts = _parse_timestamp(r.get("timestamp", ""))
        if ts is not None:
            ts_list.append(ts)
    if not ts_list:
        return None, None
    return min(ts_list), max(ts_list)


# ----------------------------------------------------------------------------
# Rendering
# ----------------------------------------------------------------------------

def render_markdown(records: list[dict], *, window: str, now: datetime,
                    log_path: Path, skipped: int,
                    total_in_log: int) -> str:
    rule_top = _rule_counter(records).most_common(10)
    path_top = _path_counter(records).most_common(10)
    verdict_dist = _verdict_counter(records)
    mode_dist = _mode_counter(records)
    by_day = _by_day(records)
    earliest, latest = _date_span(records)

    verdict_summary = ", ".join(f"{k}={v}" for k, v in verdict_dist.most_common()) or "(none)"
    mode_summary = ", ".join(f"{k}={v}" for k, v in mode_dist.most_common()) or "(none)"

    parts: list[str] = []
    parts.append(f"# Shadow Mode Summary — window: {window}")
    parts.append("")
    parts.append(f"> Generated {now.strftime('%Y-%m-%dT%H:%M:%SZ')} by `shadow_summary.py` {SCRIPT_VERSION}")
    parts.append(f"> Log: `{log_path}`")
    parts.append("")
    parts.append("## 1. Window 統計")
    parts.append("")
    parts.append(f"- Records in log (total): **{total_in_log}**")
    parts.append(f"- Records in window: **{len(records)}**")
    if skipped:
        parts.append(f"- Skipped corrupt lines: {skipped}")
    if earliest and latest:
        parts.append(
            f"- Date span: {earliest.strftime('%Y-%m-%dT%H:%M:%SZ')} → "
            f"{latest.strftime('%Y-%m-%dT%H:%M:%SZ')} (UTC)"
        )
    else:
        parts.append("- Date span: (no parseable records in window)")
    parts.append(f"- Verdicts: {verdict_summary}")
    parts.append(f"- Modes: {mode_summary}")
    parts.append("")

    parts.append("## 2. Top 10 Rules")
    parts.append("")
    if not rule_top:
        parts.append("_(no records)_")
    else:
        parts.append("| Rule | Hits |")
        parts.append("|---|---|")
        for rule, count in rule_top:
            parts.append(f"| `{rule}` | {count} |")
    parts.append("")

    parts.append("## 3. Top 10 File Paths")
    parts.append("")
    if not path_top:
        parts.append("_(no records)_")
    else:
        parts.append("| Target Path | Hits |")
        parts.append("|---|---|")
        for path, count in path_top:
            parts.append(f"| `{path}` | {count} |")
    parts.append("")

    parts.append("## 4. By Day")
    parts.append("")
    if not by_day:
        parts.append("_(no records)_")
    else:
        parts.append("| Date (UTC) | Hits |")
        parts.append("|---|---|")
        for day in sorted(by_day.keys()):
            parts.append(f"| {day} | {by_day[day]} |")
    parts.append("")

    parts.append("---")
    parts.append("")
    parts.append("**怎麼用這份報告**")
    parts.append("")
    parts.append("- Top rules 命中極端 → 規則可能太嚴 / 太鬆，重評 `schema_lint.py`")
    parts.append("- Top paths 命中極端 → 該檔型可能要進 routine 白名單 / status 修正")
    parts.append("- By Day 觀察治理切換期 false positive 趨勢")
    parts.append("- Phase 6 metric-driven shadow → enforce 切換依據")
    parts.append("")
    return "\n".join(parts)


def render_json(records: list[dict], *, window: str, now: datetime,
                log_path: Path, skipped: int,
                total_in_log: int) -> str:
    earliest, latest = _date_span(records)
    payload = {
        "meta": {
            "script_version": SCRIPT_VERSION,
            "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "log_path": str(log_path),
            "window": window,
            "total_records_in_log": total_in_log,
            "records_in_window": len(records),
            "skipped_corrupt_lines": skipped,
            "earliest": earliest.strftime("%Y-%m-%dT%H:%M:%SZ") if earliest else None,
            "latest": latest.strftime("%Y-%m-%dT%H:%M:%SZ") if latest else None,
        },
        "verdict_distribution": dict(_verdict_counter(records)),
        "mode_distribution": dict(_mode_counter(records)),
        "rule_top": _rule_counter(records).most_common(10),
        "path_top": _path_counter(records).most_common(10),
        "by_day": dict(sorted(_by_day(records).items())),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------

def _parse_args(argv: Optional[list]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="shadow_summary - Phase 5 shadow mode metric report",
    )
    p.add_argument("--log", default=DEFAULT_LOG_PATH,
                   help=f"Path to jsonl log (default: {DEFAULT_LOG_PATH})")
    p.add_argument("--window", choices=("7d", "30d", "all"), default="7d",
                   help="Time window (default: 7d)")
    p.add_argument("--output", choices=("markdown", "json"), default="markdown",
                   help="Report format (default: markdown)")
    p.add_argument("--write", default=None,
                   help="Write report to file (auto mkdir -p); default stdout")
    p.add_argument("--dry-run", action="store_true",
                   help="Read + filter only; do not emit / write")
    return p.parse_args(argv)


def main(argv: Optional[list] = None) -> int:
    args = _parse_args(argv)

    log_path = Path(args.log).expanduser()
    if not log_path.exists():
        print(f"[shadow_summary] log not found: {log_path} (empty report)",
              file=sys.stderr)
        records_all: list[dict] = []
        skipped = 0
    else:
        records_all, skipped = parse_log(log_path)
        if skipped:
            print(f"[shadow_summary] skipped {skipped} corrupt jsonl line(s)",
                  file=sys.stderr)

    now = datetime.now(timezone.utc)
    records = filter_window(records_all, args.window, now)

    print(
        f"[shadow_summary] window={args.window} total={len(records_all)} "
        f"in_window={len(records)} format={args.output}",
        file=sys.stderr,
    )

    if args.dry_run:
        return 0

    if args.output == "markdown":
        report = render_markdown(
            records, window=args.window, now=now, log_path=log_path,
            skipped=skipped, total_in_log=len(records_all),
        )
    else:
        report = render_json(
            records, window=args.window, now=now, log_path=log_path,
            skipped=skipped, total_in_log=len(records_all),
        )

    if args.write:
        target = Path(args.write).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(report, encoding="utf-8", newline="\n")
        print(f"[shadow_summary] wrote {target}", file=sys.stderr)
    else:
        if hasattr(sys.stdout, "reconfigure"):
            try:
                sys.stdout.reconfigure(encoding="utf-8")
            except Exception:
                pass
        sys.stdout.write(report)
        if not report.endswith("\n"):
            sys.stdout.write("\n")

    return 0


if __name__ == "__main__":
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
