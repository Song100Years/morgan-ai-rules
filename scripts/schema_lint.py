#!/usr/bin/env python3
"""schema_lint.py - Phase 2a hard gate for AI Vault writes.

Implements 15 deterministic rules from schema/RULES.md (v2.2.0).
Runs before guardian LLM. Fails closed on rule violation.

Input: JSON via stdin (or --input-file <path>).
Output: strict JSON to stdout matching guardian.md section B output schema.

Exit code: 0 on PASS, 1 on REJECT / NEEDS_HUMAN / input error.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import yaml

# ----------------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------------

WRITER_ROLE_PATHS = {
    "executor": {
        "allow": ["projects/", "decisions/"],
        "deny": ["00-Morgan/", "archive/legacy_", "99-rules/", "agents/"],
    },
    "advisor": {
        "allow": ["decisions/concerns/", "decisions/verdicts/"],
        "deny": [],
    },
    "auditor": {
        "allow": ["00-Morgan/", "audit_logs/"],
        "deny": [],
    },
    "desktop": {"allow": [], "deny": ["*"]},
    "human_only": {"allow": ["*"], "deny": []},
    "other": {"allow": [], "deny": ["*"]},
}

VALID_WRITER_ROLES = set(WRITER_ROLE_PATHS.keys())
VALID_OPERATIONS = {"create", "update"}

STATUS_ENUM = {"current", "draft", "superseded", "archived", "legacy"}
REQUIRED_FRONTMATTER = ("status", "valid_from", "owner", "project_id")

VACUOUS_NAMES = {"untitled", "new", "temp", "draft", "test"}
NAME_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_\-\.]*\.md$")
SUFFIX_VERSIONING = re.compile(r"_v\d+\.md$|\(\d+\)\.md$")

DATE_FIELDS = ("valid_from",)
DATETIME_FIELDS = ("expires_at", "wip_since", "promoted_at", "generated_at")

VALID_PROJECT_IDS = {
    "pretest_system",
    "solar_dashboard",
    "pattern_trader",
    "codex_multi_agent",
    "ai_governance",
}

STOPWORK_PATH_MARKER = "handoff/stop_work_"
STOPWORK_MINIMAL_REQUIRED = ("commit_hash", "task_summary", "next_step", "emergency", "wip_since")
STOPWORK_FULL_REQUIRED = (
    "current_task", "status", "next_tasks", "next_command",
    "registry_note", "session_id", "machine_id", "vault_context_hash",
)

ADR_CHAIN_MAX_DEPTH = 10
DRAFT_EXPIRES_MAX_DAYS = 30

ALLOWED_PATHS_MSG = {
    "executor": "executor allowed: projects/, decisions/ (forbidden: 00-Morgan/, archive/legacy_, 99-rules/, agents/)",
    "advisor": "advisor allowed: decisions/concerns/, decisions/verdicts/",
    "auditor": "auditor allowed: 00-Morgan/, audit_logs/",
    "desktop": "desktop has no write permission",
    "human_only": "human_only bypasses guardian via admin token",
    "other": "writer_role 'other' has no write permission",
}


# ----------------------------------------------------------------------------
# Verdict builders
# ----------------------------------------------------------------------------

def _reject(code: str, fix: str, rule: str) -> dict:
    return {
        "verdict": "REJECT",
        "error_code": code,
        "suggested_fix": fix,
        "fail_at_rule": rule,
        "flags": [],
    }


def _needs_human(code: str, summary_zh: str, rule: str) -> dict:
    return {
        "verdict": "NEEDS_HUMAN",
        "error_code": code,
        "human_summary_zh": summary_zh,
        "fail_at_rule": rule,
        "flags": [],
    }


def _pass(flags: Optional[list] = None) -> dict:
    return {"verdict": "PASS", "flags": list(flags) if flags else []}


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def _path_allowed(path: str, role: str) -> bool:
    rules = WRITER_ROLE_PATHS.get(role)
    if rules is None:
        return False
    for d in rules["deny"]:
        if d == "*":
            return False
        if path.startswith(d):
            return False
    if "*" in rules["allow"]:
        return True
    for a in rules["allow"]:
        if path.startswith(a):
            return True
    return False


def _parse_frontmatter(content: str) -> dict:
    """Parse YAML frontmatter delimited by --- ... ---. Returns {} if none."""
    if not content.startswith("---"):
        return {}
    body = content[3:]
    if body.startswith("\n"):
        body = body[1:]
    elif body.startswith("\r\n"):
        body = body[2:]
    end_match = re.search(r"(?m)^---\s*$", body)
    if not end_match:
        return {}
    fm_str = body[:end_match.start()]
    parsed = yaml.safe_load(fm_str)
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise yaml.YAMLError("frontmatter is not a YAML mapping")
    return parsed


def _required_missing(fm: dict) -> list:
    return [f for f in REQUIRED_FRONTMATTER if f not in fm or fm[f] in (None, "")]


def _conditional_missing(fm: dict) -> Optional[str]:
    status = fm.get("status")
    if status == "superseded" and not fm.get("superseded_by"):
        return "status: superseded requires field 'superseded_by'"
    if status == "draft" and not fm.get("expires_at"):
        return "status: draft requires field 'expires_at'"
    return None


def _check_naming(name: str) -> Optional[str]:
    if not NAME_PATTERN.match(name):
        return f"filename '{name}' must be ASCII [a-zA-Z0-9_-.]+\\.md"
    if SUFFIX_VERSIONING.search(name):
        return f"filename '{name}' uses suffix versioning; use frontmatter 'supersedes' instead"
    stem = name[:-3]
    if stem.lower() in VACUOUS_NAMES:
        return f"filename '{name}' is vacuous; use a descriptive name"
    return None


def _is_adr_path(path: str) -> bool:
    return (
        "/decisions/" in path
        or path.startswith("decisions/")
        or "/ADR/" in path
        or path.startswith("ADR/")
        or "/ADR_" in path
        or path.startswith("ADR_")
    )


def parse_utc_iso(value) -> datetime:
    """Parse an ISO 8601 UTC timestamp. Accept Z suffix or +00:00 only."""
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError(f"datetime is not UTC: {value}")
        return value
    if not isinstance(value, str):
        raise ValueError(f"not a string or datetime: {value!r}")
    original = value
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError(f"invalid ISO8601: {original}")
    if dt.tzinfo is None:
        raise ValueError(f"naive timestamp not allowed (need UTC Z): {original}")
    if dt.utcoffset() != timedelta(0):
        raise ValueError(f"only UTC (Z or +00:00) allowed: {original}")
    return dt


def _validate_timestamp_field(field: str, value, *, allow_date: bool) -> Optional[str]:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return f"{field}: naive datetime not allowed (need UTC Z)"
        if value.utcoffset() != timedelta(0):
            return f"{field}: only UTC allowed, got offset {value.utcoffset()}"
        return None
    if isinstance(value, date):
        if allow_date:
            return None
        return f"{field}: expected datetime with time + UTC, got date-only"
    if isinstance(value, str):
        if allow_date and re.match(r"^\d{4}-\d{2}-\d{2}$", value):
            return None
        try:
            parse_utc_iso(value)
            return None
        except ValueError as e:
            return f"{field}: {e}"
    return f"{field}: unexpected type {type(value).__name__}"


def _check_all_timestamps_utc(fm: dict) -> Optional[str]:
    for field in DATETIME_FIELDS:
        if field in fm:
            err = _validate_timestamp_field(field, fm[field], allow_date=False)
            if err:
                return err
    for field in DATE_FIELDS:
        if field in fm:
            err = _validate_timestamp_field(field, fm[field], allow_date=True)
            if err:
                return err
    return None


def _check_expires_at(fm: dict, now: Optional[datetime]) -> Optional[str]:
    raw = fm.get("expires_at")
    if not raw:
        return "expires_at missing"
    try:
        if isinstance(raw, datetime):
            if raw.tzinfo is None or raw.utcoffset() != timedelta(0):
                return "expires_at not UTC"
            dt = raw
        else:
            dt = parse_utc_iso(str(raw))
    except ValueError as e:
        return f"expires_at invalid: {e}"
    now = now or datetime.now(timezone.utc)
    if dt <= now:
        return f"expires_at already passed: {raw}"
    if dt > now + timedelta(days=DRAFT_EXPIRES_MAX_DAYS):
        return f"expires_at must be within {DRAFT_EXPIRES_MAX_DAYS} days, got {raw}"
    return None


def _validate_chain(start: str, vault_files: Optional[dict],
                    max_depth: int = ADR_CHAIN_MAX_DEPTH) -> Optional[str]:
    # vault_files is None -> wrapper did not provide a snapshot, skip check.
    # vault_files == {} -> wrapper says vault is empty, so target is missing.
    if vault_files is None:
        return None
    visited = set()
    current = start
    for _ in range(max_depth):
        if current in visited:
            return f"circular superseded_by chain at: {current}"
        visited.add(current)
        if current not in vault_files:
            return f"superseded_by target not found in vault: {current}"
        target = vault_files[current]
        if not isinstance(target, dict):
            return f"vault_files[{current}] is not a mapping"
        target_status = target.get("status")
        if target_status not in ("current", "superseded"):
            return f"superseded_by target '{current}' has invalid status: {target_status}"
        next_target = target.get("superseded_by")
        if not next_target:
            return None
        current = next_target
    return f"superseded_by chain exceeds max depth ({max_depth})"


def _adr_mutex_check(supersedes_target: str):
    """Returns (other_pr_number_or_None, fallback_reason_or_None).

    fallback_reason is set when gh CLI is unavailable; caller should treat
    as a flag (not a hard fail).
    """
    try:
        result = subprocess.run(
            ["gh", "pr", "list", "--state", "open", "--json", "number,body,title"],
            capture_output=True, text=True, timeout=15,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None, "gh_unavailable"
    if result.returncode != 0:
        return None, "gh_unavailable"
    try:
        prs = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        return None, "gh_unavailable"
    for pr in prs:
        body = pr.get("body") or ""
        title = pr.get("title") or ""
        if supersedes_target in body or supersedes_target in title:
            return pr.get("number"), None
    return None, None


def _check_stopwork_schema(fm: dict, *, minimal: bool) -> Optional[str]:
    if minimal:
        for f in STOPWORK_MINIMAL_REQUIRED:
            if f not in fm:
                return f"minimal stop_work missing field: {f}"
        if fm.get("emergency") is not True:
            return "minimal stop_work requires emergency: true"
        return None
    for f in STOPWORK_FULL_REQUIRED:
        if f not in fm:
            return f"full stop_work missing field: {f}"
    if not isinstance(fm.get("next_tasks"), list):
        return "full stop_work field 'next_tasks' must be a list"
    if "wip_since" not in fm and "promoted_at" not in fm:
        return "full stop_work requires 'wip_since' or 'promoted_at'"
    return None


def _registered_projects_msg() -> str:
    return f"valid project_id: {sorted(VALID_PROJECT_IDS)}"


# ----------------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------------

def lint(req: dict, *, now: Optional[datetime] = None,
         adr_mutex_checker=_adr_mutex_check) -> dict:
    """Run rules R1-R15 in order. First failure short-circuits.

    R12 returns flags (not fail).
    R10 returns NEEDS_HUMAN on conflict; degrades to flag if gh unavailable.
    """
    role = req.get("writer_role")
    engine = req.get("writer_engine")
    path = req.get("target_path")
    op = req.get("operation")
    content = req.get("content", "") or ""
    branch = req.get("branch", "") or ""
    vault_files = req.get("vault_files")
    previous_frontmatter = req.get("previous_frontmatter")

    if role not in VALID_WRITER_ROLES:
        return _reject(
            "PATH_PERMISSION",
            f"unknown writer_role: {role!r}; valid: {sorted(VALID_WRITER_ROLES)}",
            "R1",
        )
    if not isinstance(path, str) or not path:
        return _reject("PATH_PERMISSION", "target_path missing or not a string", "R1")
    if op not in VALID_OPERATIONS:
        return _reject(
            "PATH_PERMISSION",
            f"unknown operation: {op!r}; valid: {sorted(VALID_OPERATIONS)}",
            "R1",
        )

    # R1
    if not _path_allowed(path, role):
        return _reject("PATH_PERMISSION", ALLOWED_PATHS_MSG.get(role, ""), "R1")

    # R2
    if engine == "codex" and role == "executor":
        return _reject(
            "CODEX_EXECUTOR_FORBIDDEN",
            "use writer_engine 'claude', or change writer_role to advisor/auditor",
            "R2",
        )

    # R3-R5
    try:
        fm = _parse_frontmatter(content)
    except yaml.YAMLError as e:
        return _reject("FRONTMATTER_MISSING", f"YAML parse error: {e}", "R3")

    if not fm:
        return _reject(
            "FRONTMATTER_MISSING",
            f"frontmatter missing; required: {list(REQUIRED_FRONTMATTER)}",
            "R3",
        )

    missing = _required_missing(fm)
    if missing:
        return _reject(
            "FRONTMATTER_MISSING",
            f"missing fields: {missing}; required: {list(REQUIRED_FRONTMATTER)}",
            "R3",
        )

    if fm["status"] not in STATUS_ENUM:
        return _reject(
            "FRONTMATTER_INVALID_STATUS",
            f"got status={fm['status']!r}; valid: {sorted(STATUS_ENUM)}",
            "R4",
        )

    cond_err = _conditional_missing(fm)
    if cond_err:
        return _reject("FRONTMATTER_CONDITIONAL_MISSING", cond_err, "R5")

    # R6
    name = Path(path).name
    name_err = _check_naming(name)
    if name_err:
        return _reject(
            "NAMING_VIOLATION",
            f"{name_err}; suggested format: <topic>_<descriptor>.md",
            "R6",
        )

    # R7
    if path.startswith("archive/legacy_"):
        return _reject(
            "LEGACY_READONLY",
            "legacy region is read-only; write to current path and reference legacy source",
            "R7",
        )

    # R8
    if _is_adr_path(path) and op == "update":
        return _reject(
            "ADR_IMMUTABLE",
            "ADR is immutable; create a new ADR with frontmatter 'supersedes: <old_id>'",
            "R8",
        )

    # R9
    if fm.get("superseded_by"):
        chain_err = _validate_chain(str(fm["superseded_by"]), vault_files)
        if chain_err:
            return _reject("ADR_CHAIN_BROKEN", chain_err, "R9")

    # R10 - NEEDS_HUMAN; flag if gh unavailable
    flags = []
    if fm.get("supersedes"):
        other_pr, fallback = adr_mutex_checker(str(fm["supersedes"]))
        if other_pr is not None:
            return _needs_human(
                "ADR_MUTEX_CONFLICT",
                f"writer_role {role} 與 PR #{other_pr} 都想取代 ADR {fm['supersedes']}，需要你裁決保留哪份",
                "R10",
            )
        if fallback:
            flags.append("ADR_MUTEX_CHECK_SKIPPED_GH_UNAVAILABLE")

    # R11
    if fm["status"] == "draft":
        exp_err = _check_expires_at(fm, now=now)
        if exp_err:
            return _reject(
                "DRAFT_EXPIRES_INVALID",
                f"{exp_err}; expires_at must be UTC ISO8601 within {DRAFT_EXPIRES_MAX_DAYS} days",
                "R11",
            )

    # R12 - flag, not fail
    if op == "update" and isinstance(previous_frontmatter, dict):
        if previous_frontmatter.get("status") == "draft" and fm["status"] == "current":
            flags.append("PROMOTE_DRAFT_STRICT_GUARDIAN")

    # R13
    if STOPWORK_PATH_MARKER in path:
        is_emergency = branch.startswith("hotfix/") or fm.get("emergency") is True
        sw_err = _check_stopwork_schema(fm, minimal=is_emergency)
        if sw_err:
            return _reject("STOPWORK_SCHEMA", sw_err, "R13")

    # R14
    ts_err = _check_all_timestamps_utc(fm)
    if ts_err:
        return _reject(
            "TIMESTAMP_NOT_UTC",
            f"{ts_err}; require UTC ISO8601 (e.g. 2026-06-08T00:00:00Z)",
            "R14",
        )

    # R15
    pid = fm.get("project_id")
    if pid not in VALID_PROJECT_IDS:
        return _reject("PROJECT_ID_NOT_FOUND", _registered_projects_msg(), "R15")

    return _pass(flags=flags)


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------

def _read_input(args) -> dict:
    if args.input_file:
        text = Path(args.input_file).read_text(encoding="utf-8")
    else:
        text = sys.stdin.read()
    return json.loads(text)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="schema_lint - Phase 2a hard gate")
    parser.add_argument("--input-file", help="Read JSON request from file (default: stdin)")
    args = parser.parse_args(argv)
    try:
        req = _read_input(args)
    except json.JSONDecodeError as e:
        result = {
            "verdict": "REJECT",
            "error_code": "INPUT_INVALID_JSON",
            "suggested_fix": f"input must be valid JSON: {e}",
            "fail_at_rule": "INPUT",
            "flags": [],
        }
        print(json.dumps(result, ensure_ascii=False))
        return 1
    result = lint(req)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
