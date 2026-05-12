"""Tests for schema_lint (Phase 2a).

Coverage: 15 rules R1-R15. Each rule has at least one PASS case, one
negative case (verdict REJECT/NEEDS_HUMAN with expected error_code), and
edge / boundary cases where applicable.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import schema_lint as sl


# ----------------------------------------------------------------------------
# R1 - Path × writer_role matching
# ----------------------------------------------------------------------------

class TestR1PathPermission:
    def test_executor_projects_path_passes(self, valid_request):
        result = sl.lint(valid_request)
        assert result["verdict"] == "PASS"

    def test_executor_decisions_path_passes(self, valid_request):
        valid_request["target_path"] = "decisions/ADR_2026-05-10_test_decision.md"
        valid_request["operation"] = "create"
        result = sl.lint(valid_request)
        assert result["verdict"] == "PASS"

    def test_executor_blocked_from_morgan_dir(self, valid_request):
        valid_request["target_path"] = "00-Morgan/private/foo.md"
        result = sl.lint(valid_request)
        assert result["verdict"] == "REJECT"
        assert result["error_code"] == "PATH_PERMISSION"
        assert result["fail_at_rule"] == "R1"

    def test_executor_blocked_from_archive_legacy(self, valid_request):
        valid_request["target_path"] = "archive/legacy_pretest_2025-Q4/foo.md"
        result = sl.lint(valid_request)
        assert result["verdict"] == "REJECT"
        assert result["error_code"] == "PATH_PERMISSION"

    def test_advisor_can_write_concerns(self, valid_request):
        valid_request["writer_role"] = "advisor"
        valid_request["target_path"] = "decisions/concerns/concern_2026-05-10.md"
        result = sl.lint(valid_request)
        assert result["verdict"] == "PASS"

    def test_advisor_blocked_from_projects(self, valid_request):
        valid_request["writer_role"] = "advisor"
        valid_request["target_path"] = "projects/pattern_trader/foo.md"
        result = sl.lint(valid_request)
        assert result["verdict"] == "REJECT"
        assert result["error_code"] == "PATH_PERMISSION"

    def test_auditor_can_write_morgan_dir(self, valid_request):
        valid_request["writer_role"] = "auditor"
        valid_request["target_path"] = "00-Morgan/audit/weekly_2026-W19.md"
        result = sl.lint(valid_request)
        assert result["verdict"] == "PASS"

    def test_desktop_blocked_everywhere(self, valid_request):
        valid_request["writer_role"] = "desktop"
        valid_request["target_path"] = "projects/pattern_trader/foo.md"
        result = sl.lint(valid_request)
        assert result["verdict"] == "REJECT"
        assert result["error_code"] == "PATH_PERMISSION"

    def test_human_only_passes_anywhere(self, valid_request):
        valid_request["writer_role"] = "human_only"
        valid_request["target_path"] = "projects/pattern_trader/foo.md"
        result = sl.lint(valid_request)
        assert result["verdict"] == "PASS"

    def test_unknown_role_rejected(self, valid_request):
        valid_request["writer_role"] = "rogue"
        result = sl.lint(valid_request)
        assert result["verdict"] == "REJECT"
        assert result["fail_at_rule"] == "R1"


# ----------------------------------------------------------------------------
# R2 - codex + executor forbidden
# ----------------------------------------------------------------------------

class TestR2CodexExecutorForbidden:
    def test_codex_advisor_passes(self, valid_request):
        valid_request["writer_role"] = "advisor"
        valid_request["writer_engine"] = "codex"
        valid_request["target_path"] = "decisions/concerns/c.md"
        result = sl.lint(valid_request)
        assert result["verdict"] == "PASS"

    def test_codex_executor_rejected(self, valid_request):
        valid_request["writer_engine"] = "codex"
        result = sl.lint(valid_request)
        assert result["verdict"] == "REJECT"
        assert result["error_code"] == "CODEX_EXECUTOR_FORBIDDEN"
        assert result["fail_at_rule"] == "R2"

    def test_claude_executor_passes(self, valid_request):
        result = sl.lint(valid_request)
        assert result["verdict"] == "PASS"

    def test_codex_auditor_passes(self, valid_request):
        valid_request["writer_role"] = "auditor"
        valid_request["writer_engine"] = "codex"
        valid_request["target_path"] = "audit_logs/log_2026-05-10.md"
        result = sl.lint(valid_request)
        assert result["verdict"] == "PASS"


# ----------------------------------------------------------------------------
# R3 - frontmatter required fields
# ----------------------------------------------------------------------------

class TestR3FrontmatterMissing:
    def test_full_frontmatter_passes(self, valid_request):
        result = sl.lint(valid_request)
        assert result["verdict"] == "PASS"

    def test_no_frontmatter_rejected(self, valid_request):
        valid_request["content"] = "# Just a body, no frontmatter\n"
        result = sl.lint(valid_request)
        assert result["verdict"] == "REJECT"
        assert result["error_code"] == "FRONTMATTER_MISSING"
        assert result["fail_at_rule"] == "R3"

    def test_missing_status_rejected(self, valid_request, make_content):
        valid_request["content"] = make_content([
            "valid_from: 2026-05-10",
            "owner: morgan",
            "project_id: pattern_trader",
        ])
        result = sl.lint(valid_request)
        assert result["verdict"] == "REJECT"
        assert result["error_code"] == "FRONTMATTER_MISSING"
        assert "status" in result["suggested_fix"]

    def test_missing_owner_rejected(self, valid_request, make_content):
        valid_request["content"] = make_content([
            "status: current",
            "valid_from: 2026-05-10",
            "project_id: pattern_trader",
        ])
        result = sl.lint(valid_request)
        assert result["verdict"] == "REJECT"
        assert result["error_code"] == "FRONTMATTER_MISSING"

    def test_yaml_parse_error_rejected(self, valid_request):
        valid_request["content"] = "---\nstatus: : : invalid\n---\n"
        result = sl.lint(valid_request)
        assert result["verdict"] == "REJECT"
        assert result["error_code"] == "FRONTMATTER_MISSING"


# ----------------------------------------------------------------------------
# R4 - status enum
# ----------------------------------------------------------------------------

class TestR4StatusEnum:
    def test_current_passes(self, valid_request):
        result = sl.lint(valid_request)
        assert result["verdict"] == "PASS"

    def test_archived_passes(self, valid_request, make_content):
        valid_request["content"] = make_content([
            "status: archived",
            "valid_from: 2026-05-10",
            "owner: morgan",
            "project_id: pattern_trader",
        ])
        result = sl.lint(valid_request)
        assert result["verdict"] == "PASS"

    def test_unknown_status_rejected(self, valid_request, make_content):
        valid_request["content"] = make_content([
            "status: pending",
            "valid_from: 2026-05-10",
            "owner: morgan",
            "project_id: pattern_trader",
        ])
        result = sl.lint(valid_request)
        assert result["verdict"] == "REJECT"
        assert result["error_code"] == "FRONTMATTER_INVALID_STATUS"
        assert result["fail_at_rule"] == "R4"

    def test_uppercase_status_rejected(self, valid_request, make_content):
        valid_request["content"] = make_content([
            "status: Current",
            "valid_from: 2026-05-10",
            "owner: morgan",
            "project_id: pattern_trader",
        ])
        result = sl.lint(valid_request)
        assert result["verdict"] == "REJECT"
        assert result["error_code"] == "FRONTMATTER_INVALID_STATUS"


# ----------------------------------------------------------------------------
# R5 - conditional fields
# ----------------------------------------------------------------------------

class TestR5ConditionalMissing:
    def test_current_no_extra_required(self, valid_request):
        result = sl.lint(valid_request)
        assert result["verdict"] == "PASS"

    def test_superseded_without_superseded_by_rejected(self, valid_request, make_content):
        valid_request["content"] = make_content([
            "status: superseded",
            "valid_from: 2026-05-10",
            "owner: morgan",
            "project_id: pattern_trader",
        ])
        result = sl.lint(valid_request)
        assert result["verdict"] == "REJECT"
        assert result["error_code"] == "FRONTMATTER_CONDITIONAL_MISSING"
        assert result["fail_at_rule"] == "R5"

    def test_superseded_with_superseded_by_passes(self, valid_request, make_content, fixed_now):
        valid_request["content"] = make_content([
            "status: superseded",
            "valid_from: 2026-05-10",
            "owner: morgan",
            "project_id: pattern_trader",
            "superseded_by: projects/pattern_trader/notes/new.md",
        ])
        result = sl.lint(valid_request, now=fixed_now)
        assert result["verdict"] == "PASS"

    def test_draft_without_expires_at_rejected(self, valid_request, make_content):
        valid_request["content"] = make_content([
            "status: draft",
            "valid_from: 2026-05-10",
            "owner: morgan",
            "project_id: pattern_trader",
        ])
        result = sl.lint(valid_request)
        assert result["verdict"] == "REJECT"
        assert result["error_code"] == "FRONTMATTER_CONDITIONAL_MISSING"


# ----------------------------------------------------------------------------
# R6 - naming
# ----------------------------------------------------------------------------

class TestR6Naming:
    def test_snake_case_passes(self, valid_request):
        result = sl.lint(valid_request)
        assert result["verdict"] == "PASS"

    def test_kebab_case_passes(self, valid_request):
        valid_request["target_path"] = "projects/pattern_trader/notes/slice-03-handoff.md"
        result = sl.lint(valid_request)
        assert result["verdict"] == "PASS"

    def test_vacuous_untitled_rejected(self, valid_request):
        valid_request["target_path"] = "projects/pattern_trader/notes/untitled.md"
        result = sl.lint(valid_request)
        assert result["verdict"] == "REJECT"
        assert result["error_code"] == "NAMING_VIOLATION"
        assert result["fail_at_rule"] == "R6"

    def test_vacuous_test_rejected(self, valid_request):
        valid_request["target_path"] = "projects/pattern_trader/notes/test.md"
        result = sl.lint(valid_request)
        assert result["verdict"] == "REJECT"
        assert result["error_code"] == "NAMING_VIOLATION"

    def test_v2_suffix_rejected(self, valid_request):
        valid_request["target_path"] = "projects/pattern_trader/notes/slice_v2.md"
        result = sl.lint(valid_request)
        assert result["verdict"] == "REJECT"
        assert result["error_code"] == "NAMING_VIOLATION"

    def test_paren_versioning_rejected(self, valid_request):
        valid_request["target_path"] = "projects/pattern_trader/notes/slice (1).md"
        result = sl.lint(valid_request)
        assert result["verdict"] == "REJECT"
        assert result["error_code"] == "NAMING_VIOLATION"

    def test_non_ascii_rejected(self, valid_request):
        valid_request["target_path"] = "projects/pattern_trader/notes/筆記.md"
        result = sl.lint(valid_request)
        assert result["verdict"] == "REJECT"
        assert result["error_code"] == "NAMING_VIOLATION"

    def test_uppercase_passes(self, valid_request):
        valid_request["target_path"] = "projects/pattern_trader/notes/Slice_03.md"
        result = sl.lint(valid_request)
        assert result["verdict"] == "PASS"


# ----------------------------------------------------------------------------
# R7 - legacy readonly
# ----------------------------------------------------------------------------

class TestR7LegacyReadonly:
    def test_archive_non_legacy_passes_for_role(self, valid_request):
        # auditor is allowed to write under audit_logs/, not archive.
        # The clearest R7 PASS demo: a path that doesn't begin with
        # archive/legacy_ but still satisfies role permissions.
        result = sl.lint(valid_request)
        assert result["verdict"] == "PASS"

    def test_archive_legacy_rejected_at_r1(self, valid_request):
        # executor cannot reach R7 because R1 deny-list catches archive/legacy_
        # first; this is the actual production behavior for this role.
        valid_request["target_path"] = "archive/legacy_2025/old.md"
        result = sl.lint(valid_request)
        assert result["verdict"] == "REJECT"
        assert result["error_code"] == "PATH_PERMISSION"

    def test_human_only_to_legacy_rejected_at_r7(self, valid_request, make_content):
        # human_only bypasses R1, so R7 is the rule that should fire.
        valid_request["writer_role"] = "human_only"
        valid_request["target_path"] = "archive/legacy_2025/old.md"
        valid_request["content"] = make_content([
            "status: legacy",
            "valid_from: 2025-01-01",
            "owner: morgan",
            "project_id: pattern_trader",
        ])
        result = sl.lint(valid_request)
        assert result["verdict"] == "REJECT"
        assert result["error_code"] == "LEGACY_READONLY"
        assert result["fail_at_rule"] == "R7"


# ----------------------------------------------------------------------------
# R8 - ADR immutable on update
# ----------------------------------------------------------------------------

class TestR8AdrImmutable:
    def test_create_new_adr_passes(self, valid_request, make_content):
        valid_request["target_path"] = "decisions/ADR_2026-05-10_new.md"
        valid_request["operation"] = "create"
        result = sl.lint(valid_request)
        assert result["verdict"] == "PASS"

    def test_update_adr_rejected(self, valid_request):
        valid_request["target_path"] = "decisions/ADR_2026-05-09_old.md"
        valid_request["operation"] = "update"
        result = sl.lint(valid_request)
        assert result["verdict"] == "REJECT"
        assert result["error_code"] == "ADR_IMMUTABLE"
        assert result["fail_at_rule"] == "R8"

    def test_update_non_adr_passes(self, valid_request):
        valid_request["target_path"] = "projects/pattern_trader/notes/log.md"
        valid_request["operation"] = "update"
        result = sl.lint(valid_request)
        assert result["verdict"] == "PASS"


# ----------------------------------------------------------------------------
# R9 - superseded_by chain integrity
# ----------------------------------------------------------------------------

class TestR9ChainIntegrity:
    def _make_superseded_request(self, valid_request, make_content, vault_files):
        valid_request["content"] = make_content([
            "status: superseded",
            "valid_from: 2026-05-10",
            "owner: morgan",
            "project_id: pattern_trader",
            "superseded_by: target_a.md",
        ])
        valid_request["vault_files"] = vault_files
        return valid_request

    def test_chain_target_active_passes(self, valid_request, make_content):
        req = self._make_superseded_request(valid_request, make_content, {
            "target_a.md": {"status": "current"},
        })
        result = sl.lint(req)
        assert result["verdict"] == "PASS"

    def test_chain_target_missing_rejected(self, valid_request, make_content):
        req = self._make_superseded_request(valid_request, make_content, {})
        result = sl.lint(req)
        assert result["verdict"] == "REJECT"
        assert result["error_code"] == "ADR_CHAIN_BROKEN"
        assert result["fail_at_rule"] == "R9"
        assert "not found" in result["suggested_fix"]

    def test_chain_target_archived_rejected(self, valid_request, make_content):
        req = self._make_superseded_request(valid_request, make_content, {
            "target_a.md": {"status": "archived"},
        })
        result = sl.lint(req)
        assert result["verdict"] == "REJECT"
        assert result["error_code"] == "ADR_CHAIN_BROKEN"
        assert "invalid status" in result["suggested_fix"]

    def test_chain_circular_rejected(self, valid_request, make_content):
        req = self._make_superseded_request(valid_request, make_content, {
            "target_a.md": {"status": "superseded", "superseded_by": "target_b.md"},
            "target_b.md": {"status": "superseded", "superseded_by": "target_a.md"},
        })
        result = sl.lint(req)
        assert result["verdict"] == "REJECT"
        assert result["error_code"] == "ADR_CHAIN_BROKEN"
        assert "circular" in result["suggested_fix"]

    def test_chain_too_deep_rejected(self, valid_request, make_content):
        # Build a 12-step linear chain (exceeds ADR_CHAIN_MAX_DEPTH=10)
        vault = {}
        for i in range(12):
            nxt = f"target_{i+1}.md" if i < 11 else None
            vault[f"target_{i}.md"] = {
                "status": "superseded",
                **({"superseded_by": nxt} if nxt else {"status": "current"}),
            }
        # Reset target_11.md to current with no further chain
        vault["target_11.md"] = {"status": "current"}
        valid_request["content"] = make_content([
            "status: superseded",
            "valid_from: 2026-05-10",
            "owner: morgan",
            "project_id: pattern_trader",
            "superseded_by: target_0.md",
        ])
        valid_request["vault_files"] = vault
        result = sl.lint(valid_request)
        assert result["verdict"] == "REJECT"
        assert result["error_code"] == "ADR_CHAIN_BROKEN"
        assert "max depth" in result["suggested_fix"]

    def test_no_superseded_by_skips_check(self, valid_request):
        # No superseded_by field in baseline -> R9 doesn't run, PASS overall.
        result = sl.lint(valid_request)
        assert result["verdict"] == "PASS"


# ----------------------------------------------------------------------------
# R10 - ADR ID mutex (NEEDS_HUMAN)
# ----------------------------------------------------------------------------

class TestR10AdrMutex:
    def test_no_other_pr_passes(self, valid_request, make_content, stub_mutex_no_conflict):
        valid_request["target_path"] = "decisions/ADR_2026-05-10_new.md"
        valid_request["content"] = make_content([
            "status: current",
            "valid_from: 2026-05-10",
            "owner: morgan",
            "project_id: pattern_trader",
            "supersedes: ADR_2026-04-01_old.md",
        ])
        result = sl.lint(valid_request, adr_mutex_checker=stub_mutex_no_conflict)
        assert result["verdict"] == "PASS"

    def test_conflict_returns_needs_human(self, valid_request, make_content):
        def conflicting_checker(target):
            return 42, None
        valid_request["target_path"] = "decisions/ADR_2026-05-10_new.md"
        valid_request["content"] = make_content([
            "status: current",
            "valid_from: 2026-05-10",
            "owner: morgan",
            "project_id: pattern_trader",
            "supersedes: ADR_2026-04-01_old.md",
        ])
        result = sl.lint(valid_request, adr_mutex_checker=conflicting_checker)
        assert result["verdict"] == "NEEDS_HUMAN"
        assert result["error_code"] == "ADR_MUTEX_CONFLICT"
        assert result["fail_at_rule"] == "R10"
        assert "PR #42" in result["human_summary_zh"]

    def test_gh_unavailable_flags_warning(self, valid_request, make_content):
        def unavailable_checker(target):
            return None, "gh_unavailable"
        valid_request["target_path"] = "decisions/ADR_2026-05-10_new.md"
        valid_request["content"] = make_content([
            "status: current",
            "valid_from: 2026-05-10",
            "owner: morgan",
            "project_id: pattern_trader",
            "supersedes: ADR_2026-04-01_old.md",
        ])
        result = sl.lint(valid_request, adr_mutex_checker=unavailable_checker)
        assert result["verdict"] == "PASS"
        assert "ADR_MUTEX_CHECK_SKIPPED_GH_UNAVAILABLE" in result["flags"]

    def test_no_supersedes_skips_check(self, valid_request):
        # Default checker would call gh, so use stub. Baseline has no supersedes.
        def boom(target):
            raise AssertionError("R10 should not be invoked when no supersedes")
        result = sl.lint(valid_request, adr_mutex_checker=boom)
        assert result["verdict"] == "PASS"


# ----------------------------------------------------------------------------
# R11 - draft expires_at validity
# ----------------------------------------------------------------------------

class TestR11DraftExpires:
    def _draft_request(self, valid_request, make_content, expires_at_str):
        valid_request["content"] = make_content([
            "status: draft",
            "valid_from: 2026-05-10",
            "owner: morgan",
            "project_id: pattern_trader",
            f"expires_at: {expires_at_str}",
        ])
        return valid_request

    def test_within_30_days_passes(self, valid_request, make_content, fixed_now):
        req = self._draft_request(valid_request, make_content, "2026-05-15T00:00:00Z")
        result = sl.lint(req, now=fixed_now)
        assert result["verdict"] == "PASS"

    def test_already_expired_rejected(self, valid_request, make_content, fixed_now):
        req = self._draft_request(valid_request, make_content, "2026-05-09T00:00:00Z")
        result = sl.lint(req, now=fixed_now)
        assert result["verdict"] == "REJECT"
        assert result["error_code"] == "DRAFT_EXPIRES_INVALID"
        assert result["fail_at_rule"] == "R11"

    def test_too_far_in_future_rejected(self, valid_request, make_content, fixed_now):
        req = self._draft_request(valid_request, make_content, "2026-07-15T00:00:00Z")
        result = sl.lint(req, now=fixed_now)
        assert result["verdict"] == "REJECT"
        assert result["error_code"] == "DRAFT_EXPIRES_INVALID"

    def test_boundary_exactly_30_days_passes(self, valid_request, make_content, fixed_now):
        # fixed_now = 2026-05-10T12:00:00Z -> +30d = 2026-06-09T12:00:00Z
        req = self._draft_request(valid_request, make_content, "2026-06-09T12:00:00Z")
        result = sl.lint(req, now=fixed_now)
        assert result["verdict"] == "PASS"

    def test_boundary_30_days_plus_one_minute_rejected(self, valid_request, make_content, fixed_now):
        req = self._draft_request(valid_request, make_content, "2026-06-09T12:01:00Z")
        result = sl.lint(req, now=fixed_now)
        assert result["verdict"] == "REJECT"
        assert result["error_code"] == "DRAFT_EXPIRES_INVALID"

    def test_plus_zero_offset_passes(self, valid_request, make_content, fixed_now):
        req = self._draft_request(valid_request, make_content, "2026-05-15T00:00:00+00:00")
        result = sl.lint(req, now=fixed_now)
        assert result["verdict"] == "PASS"


# ----------------------------------------------------------------------------
# R12 - promote draft flag (does not fail)
# ----------------------------------------------------------------------------

class TestR12PromoteFlag:
    def test_no_previous_no_flag(self, valid_request):
        result = sl.lint(valid_request)
        assert result["verdict"] == "PASS"
        assert "PROMOTE_DRAFT_STRICT_GUARDIAN" not in result["flags"]

    def test_promote_draft_to_current_now_blocked_by_r19(self, valid_request):
        # Phase 2c v2: R12 soft flag is superseded by R19 hard gate.
        # The flag is still computed internally (preserved for future flexibility)
        # but R19 short-circuits before it surfaces in the public verdict.
        valid_request["operation"] = "update"
        valid_request["previous_frontmatter"] = {"status": "draft"}
        result = sl.lint(valid_request)
        assert result["verdict"] == "NEEDS_HUMAN"
        assert result["fail_at_rule"] == "R19"
        assert result["error_code"] == "STATUS_UPGRADE_NEEDS_HUMAN"

    def test_current_to_current_no_flag(self, valid_request):
        valid_request["operation"] = "update"
        valid_request["previous_frontmatter"] = {"status": "current"}
        result = sl.lint(valid_request)
        assert result["verdict"] == "PASS"
        assert "PROMOTE_DRAFT_STRICT_GUARDIAN" not in result["flags"]

    def test_create_with_previous_no_flag(self, valid_request):
        # operation=create should not trigger promote even if previous_frontmatter given
        valid_request["operation"] = "create"
        valid_request["previous_frontmatter"] = {"status": "draft"}
        result = sl.lint(valid_request)
        assert result["verdict"] == "PASS"
        assert "PROMOTE_DRAFT_STRICT_GUARDIAN" not in result["flags"]


# ----------------------------------------------------------------------------
# R13 - stop_work schema
# ----------------------------------------------------------------------------

class TestR13StopworkSchema:
    def _stopwork_path(self):
        return "projects/pattern_trader/handoff/stop_work_2026-05-10T120000Z.md"

    def test_full_schema_passes(self, valid_request, make_content):
        valid_request["target_path"] = self._stopwork_path()
        valid_request["content"] = make_content([
            "status: current",
            "valid_from: 2026-05-10",
            "owner: morgan",
            "project_id: pattern_trader",
            "current_task: implement schema_lint",
            "next_tasks:",
            "  - write tests",
            "  - merge PR",
            "next_command: pytest schema/tests/",
            "registry_note: phase 2a in progress",
            "wip_since: 2026-05-10T11:00:00Z",
            "session_id: abc-123",
            "machine_id: home-pc",
            "vault_context_hash: deadbeef",
        ])
        result = sl.lint(valid_request)
        assert result["verdict"] == "PASS"

    def test_full_schema_missing_field_rejected(self, valid_request, make_content):
        valid_request["target_path"] = self._stopwork_path()
        valid_request["content"] = make_content([
            "status: current",
            "valid_from: 2026-05-10",
            "owner: morgan",
            "project_id: pattern_trader",
            "current_task: x",
            "next_tasks:",
            "  - a",
            "next_command: pytest",
            "registry_note: x",
            "wip_since: 2026-05-10T11:00:00Z",
            # missing: session_id, machine_id, vault_context_hash
        ])
        result = sl.lint(valid_request)
        assert result["verdict"] == "REJECT"
        assert result["error_code"] == "STOPWORK_SCHEMA"
        assert result["fail_at_rule"] == "R13"

    def test_minimal_schema_for_hotfix_branch_passes(self, valid_request, make_content):
        valid_request["target_path"] = self._stopwork_path()
        valid_request["branch"] = "hotfix/2026-05-10-bug"
        valid_request["content"] = make_content([
            "status: current",
            "valid_from: 2026-05-10",
            "owner: morgan",
            "project_id: pattern_trader",
            "commit_hash: deadbeef",
            "task_summary: hotfix lint output",
            "next_step: deploy to vps",
            "emergency: true",
            "wip_since: 2026-05-10T11:00:00Z",
        ])
        result = sl.lint(valid_request)
        assert result["verdict"] == "PASS"

    def test_minimal_schema_via_emergency_flag_passes(self, valid_request, make_content):
        valid_request["target_path"] = self._stopwork_path()
        valid_request["content"] = make_content([
            "status: current",
            "valid_from: 2026-05-10",
            "owner: morgan",
            "project_id: pattern_trader",
            "commit_hash: deadbeef",
            "task_summary: hotfix lint",
            "next_step: deploy",
            "emergency: true",
            "wip_since: 2026-05-10T11:00:00Z",
        ])
        result = sl.lint(valid_request)
        assert result["verdict"] == "PASS"

    def test_minimal_schema_missing_field_rejected(self, valid_request, make_content):
        valid_request["target_path"] = self._stopwork_path()
        valid_request["branch"] = "hotfix/2026-05-10-bug"
        valid_request["content"] = make_content([
            "status: current",
            "valid_from: 2026-05-10",
            "owner: morgan",
            "project_id: pattern_trader",
            "task_summary: hotfix",
            "next_step: deploy",
            "emergency: true",
            "wip_since: 2026-05-10T11:00:00Z",
            # missing: commit_hash
        ])
        result = sl.lint(valid_request)
        assert result["verdict"] == "REJECT"
        assert result["error_code"] == "STOPWORK_SCHEMA"

    def test_full_schema_next_tasks_not_list_rejected(self, valid_request, make_content):
        valid_request["target_path"] = self._stopwork_path()
        valid_request["content"] = make_content([
            "status: current",
            "valid_from: 2026-05-10",
            "owner: morgan",
            "project_id: pattern_trader",
            "current_task: x",
            "next_tasks: just_a_string",
            "next_command: pytest",
            "registry_note: x",
            "wip_since: 2026-05-10T11:00:00Z",
            "session_id: abc",
            "machine_id: pc",
            "vault_context_hash: cafe",
        ])
        result = sl.lint(valid_request)
        assert result["verdict"] == "REJECT"
        assert result["error_code"] == "STOPWORK_SCHEMA"


# ----------------------------------------------------------------------------
# R14 - timestamp UTC
# ----------------------------------------------------------------------------

class TestR14TimestampUtc:
    def test_valid_from_date_only_passes(self, valid_request):
        # valid_from: YYYY-MM-DD already in baseline.
        result = sl.lint(valid_request)
        assert result["verdict"] == "PASS"

    def test_expires_at_with_z_suffix_passes(self, valid_request, make_content, fixed_now):
        valid_request["content"] = make_content([
            "status: draft",
            "valid_from: 2026-05-10",
            "owner: morgan",
            "project_id: pattern_trader",
            "expires_at: 2026-05-15T00:00:00Z",
        ])
        result = sl.lint(valid_request, now=fixed_now)
        assert result["verdict"] == "PASS"

    def test_expires_at_with_plus_zero_passes(self, valid_request, make_content, fixed_now):
        valid_request["content"] = make_content([
            "status: draft",
            "valid_from: 2026-05-10",
            "owner: morgan",
            "project_id: pattern_trader",
            "expires_at: '2026-05-15T00:00:00+00:00'",
        ])
        result = sl.lint(valid_request, now=fixed_now)
        assert result["verdict"] == "PASS"

    def test_wip_since_non_utc_rejected(self, valid_request, make_content):
        valid_request["content"] = make_content([
            "status: current",
            "valid_from: 2026-05-10",
            "owner: morgan",
            "project_id: pattern_trader",
            "wip_since: '2026-05-10T15:30:00+08:00'",
        ])
        result = sl.lint(valid_request)
        assert result["verdict"] == "REJECT"
        assert result["error_code"] == "TIMESTAMP_NOT_UTC"
        assert result["fail_at_rule"] == "R14"

    def test_promoted_at_naive_rejected(self, valid_request, make_content):
        valid_request["content"] = make_content([
            "status: current",
            "valid_from: 2026-05-10",
            "owner: morgan",
            "project_id: pattern_trader",
            "promoted_at: '2026-05-10T11:00:00'",
        ])
        result = sl.lint(valid_request)
        assert result["verdict"] == "REJECT"
        assert result["error_code"] == "TIMESTAMP_NOT_UTC"

    def test_generated_at_garbage_rejected(self, valid_request, make_content):
        valid_request["content"] = make_content([
            "status: current",
            "valid_from: 2026-05-10",
            "owner: morgan",
            "project_id: pattern_trader",
            "generated_at: 'May 10, 2026'",
        ])
        result = sl.lint(valid_request)
        assert result["verdict"] == "REJECT"
        assert result["error_code"] == "TIMESTAMP_NOT_UTC"

    def test_valid_from_full_utc_passes(self, valid_request, make_content):
        valid_request["content"] = make_content([
            "status: current",
            "valid_from: '2026-05-10T00:00:00Z'",
            "owner: morgan",
            "project_id: pattern_trader",
        ])
        result = sl.lint(valid_request)
        assert result["verdict"] == "PASS"


# ----------------------------------------------------------------------------
# R15 - project_id registry
# ----------------------------------------------------------------------------

class TestR15ProjectIdRegistry:
    def test_known_project_passes(self, valid_request):
        result = sl.lint(valid_request)
        assert result["verdict"] == "PASS"

    def test_unknown_project_rejected(self, valid_request, make_content):
        valid_request["content"] = make_content([
            "status: current",
            "valid_from: 2026-05-10",
            "owner: morgan",
            "project_id: random_unknown",
        ])
        result = sl.lint(valid_request)
        assert result["verdict"] == "REJECT"
        assert result["error_code"] == "PROJECT_ID_NOT_FOUND"
        assert result["fail_at_rule"] == "R15"

    def test_each_registered_project_passes(self, valid_request, make_content):
        for pid in ("pretest_system", "solar_dashboard", "pattern_trader",
                    "codex_multi_agent", "ai_governance"):
            valid_request["content"] = make_content([
                "status: current",
                "valid_from: 2026-05-10",
                "owner: morgan",
                f"project_id: {pid}",
            ])
            result = sl.lint(valid_request)
            assert result["verdict"] == "PASS", f"failed for {pid}: {result}"


# ----------------------------------------------------------------------------
# Integration: CLI / main()
# ----------------------------------------------------------------------------

class TestCli:
    def test_cli_invalid_json_rejects(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("not json {{{", encoding="utf-8")
        rc = sl.main(["--input-file", str(bad)])
        assert rc == 1

    def test_cli_pass_returns_0(self, tmp_path, valid_request):
        path = tmp_path / "req.json"
        path.write_text(json.dumps(valid_request), encoding="utf-8")
        rc = sl.main(["--input-file", str(path)])
        assert rc == 0

    def test_cli_reject_returns_1(self, tmp_path, valid_request):
        valid_request["target_path"] = "00-Morgan/foo.md"
        path = tmp_path / "req.json"
        path.write_text(json.dumps(valid_request), encoding="utf-8")
        rc = sl.main(["--input-file", str(path)])
        assert rc == 1


# ----------------------------------------------------------------------------
# Helper sanity checks
# ----------------------------------------------------------------------------

class TestParseUtcIsoHelper:
    def test_z_suffix_parsed(self):
        dt = sl.parse_utc_iso("2026-05-10T12:00:00Z")
        assert dt.tzinfo is not None
        assert dt.utcoffset() == timedelta(0)

    def test_plus_zero_parsed(self):
        dt = sl.parse_utc_iso("2026-05-10T12:00:00+00:00")
        assert dt.utcoffset() == timedelta(0)

    def test_non_utc_rejected(self):
        with pytest.raises(ValueError):
            sl.parse_utc_iso("2026-05-10T12:00:00+08:00")

    def test_naive_rejected(self):
        with pytest.raises(ValueError):
            sl.parse_utc_iso("2026-05-10T12:00:00")

    def test_garbage_rejected(self):
        with pytest.raises(ValueError):
            sl.parse_utc_iso("not a date")


# ============================================================================
# Phase 2c v2 — R16-R19 structural classification + 4 補洞
# ============================================================================

# ----------------------------------------------------------------------------
# R6 — leading underscore allowed for ceremony filenames (Phase 2c v2 update)
# ----------------------------------------------------------------------------

class TestR6LeadingUnderscore:
    """NAME_PATTERN expanded to accept leading `_` so ceremony files
    (_global.md, _shared.md) can pass R6. Required for R18 whitelist coherence."""

    def test_global_md_name_passes_r6(self, valid_request):
        # Use human_only role to bypass R1 path restriction on claude_md/
        valid_request["writer_role"] = "human_only"
        valid_request["target_path"] = "claude_md/_global.md"
        result = sl.lint(valid_request)
        # R18 may fire (status: current + ceremony file is allowed via whitelist),
        # so the verdict should be PASS — _is_ceremony_filename matches _global.md.
        assert result["verdict"] == "PASS"

    def test_shared_md_name_passes_r6(self, valid_request):
        valid_request["writer_role"] = "human_only"
        valid_request["target_path"] = "claude_md/_shared.md"
        result = sl.lint(valid_request)
        assert result["verdict"] == "PASS"

    def test_double_underscore_still_passes_naming(self, valid_request):
        # NAME_PATTERN allows leading `_`; subsequent chars still constrained.
        valid_request["writer_role"] = "human_only"
        valid_request["target_path"] = "projects/pattern_trader/_notes.md"
        result = sl.lint(valid_request)
        assert result["verdict"] == "PASS"


# ----------------------------------------------------------------------------
# R16 — Semantic keyword flag (routine docs leaking rule-language)
# ----------------------------------------------------------------------------

class TestR16SemanticKeywords:
    def test_routine_without_keywords_passes(self, valid_frontmatter_lines, make_content):
        req = {
            "writer_role": "executor",
            "writer_engine": "claude",
            "target_path": "projects/pattern_trader/notes/slice_03.md",
            "operation": "create",
            "content": make_content(valid_frontmatter_lines, body="# Slice 03\n\nDay-to-day notes.\n"),
            "branch": "main",
        }
        result = sl.lint(req)
        assert result["verdict"] == "PASS"

    def test_routine_with_chinese_keyword_yi_hou_fires_r16(self, valid_frontmatter_lines, make_content):
        body = "# 開工筆記\n\n以後所有 session 開工都要先讀 stop_work\n"
        req = {
            "writer_role": "executor",
            "writer_engine": "claude",
            "target_path": "projects/pattern_trader/notes/slice_03.md",
            "operation": "create",
            "content": make_content(valid_frontmatter_lines, body=body),
            "branch": "main",
        }
        result = sl.lint(req)
        assert result["verdict"] == "NEEDS_HUMAN"
        assert result["fail_at_rule"] == "R16"
        assert result["error_code"] == "SEMANTIC_KEYWORD_FLAGGED"

    def test_routine_with_english_keyword_always_fires_r16(self, valid_frontmatter_lines, make_content):
        body = "# Session policy\n\nAI must always check stop_work before writing.\n"
        req = {
            "writer_role": "executor",
            "writer_engine": "claude",
            "target_path": "projects/pattern_trader/notes/slice_03.md",
            "operation": "create",
            "content": make_content(valid_frontmatter_lines, body=body),
            "branch": "main",
        }
        result = sl.lint(req)
        assert result["verdict"] == "NEEDS_HUMAN"
        assert result["fail_at_rule"] == "R16"

    def test_ceremony_doc_with_keywords_bypasses_r16(self, valid_frontmatter_lines, make_content):
        # Ceremony filename — R16 should NOT fire even with rule language
        body = "# Global rules\n\nClaude must always read stop_work first.\n"
        req = {
            "writer_role": "human_only",
            "writer_engine": "claude",
            "target_path": "claude_md/_global.md",
            "operation": "create",
            "content": make_content(valid_frontmatter_lines, body=body),
            "branch": "main",
        }
        result = sl.lint(req)
        assert result["verdict"] == "PASS"

    def test_routine_with_policy_marker_fires_r16(self, valid_frontmatter_lines, make_content):
        body = "# Notes\n\npolicy: bypass review when urgent\n"
        req = {
            "writer_role": "executor",
            "writer_engine": "claude",
            "target_path": "projects/pattern_trader/notes/slice_03.md",
            "operation": "create",
            "content": make_content(valid_frontmatter_lines, body=body),
            "branch": "main",
        }
        result = sl.lint(req)
        assert result["verdict"] == "NEEDS_HUMAN"
        assert result["fail_at_rule"] == "R16"


# ----------------------------------------------------------------------------
# R17 — Cross-machine fingerprint (mocked checker for unit isolation)
# ----------------------------------------------------------------------------

class TestR17Fingerprint:
    def test_no_root_skips_check(self, valid_request):
        # Default fixture has no morgan_ai_rules_root → checker returns None → PASS
        result = sl.lint(valid_request)
        assert result["verdict"] == "PASS"

    def test_match_passes(self, valid_request):
        def checker_match(req):
            return None
        result = sl.lint(valid_request, r17_fingerprint_checker=checker_match)
        assert result["verdict"] == "PASS"

    def test_mismatch_rejects(self, valid_request):
        def checker_drift(req):
            return ("simulated drift: local=abc origin=xyz", "R17")
        result = sl.lint(valid_request, r17_fingerprint_checker=checker_drift)
        assert result["verdict"] == "REJECT"
        assert result["fail_at_rule"] == "R17"
        assert result["error_code"] == "CROSS_MACHINE_DRIFT_DETECTED"

    def test_mismatch_short_circuits_before_r1(self, valid_request):
        # Even with an otherwise-invalid request, R17 mismatch fires first.
        valid_request["writer_role"] = "rogue_role_that_would_fail_r1"
        def checker_drift(req):
            return ("drift first", "R17")
        result = sl.lint(valid_request, r17_fingerprint_checker=checker_drift)
        assert result["fail_at_rule"] == "R17"

    def test_normalize_bytes_strips_crlf(self):
        assert sl._normalize_bytes(b"line1\r\nline2\r\n") == b"line1\nline2\n"
        assert sl._normalize_bytes(b"line1\rline2\r") == b"line1\nline2\n"
        assert sl._normalize_bytes(b"line1\nline2\n") == b"line1\nline2\n"


# ----------------------------------------------------------------------------
# R18 — Default upgrade fallback (current + non-whitelist filename)
# ----------------------------------------------------------------------------

class TestR18DefaultUpgrade:
    def test_whitelist_filename_in_ceremony_path_passes(self, valid_request):
        valid_request["writer_role"] = "human_only"
        valid_request["target_path"] = "claude_md/_global.md"
        result = sl.lint(valid_request)
        assert result["verdict"] == "PASS"

    def test_adr_filename_passes_via_pattern(self, valid_request):
        valid_request["writer_role"] = "executor"
        valid_request["target_path"] = "decisions/ADR_2026-05-11_topic.md"
        valid_request["operation"] = "create"
        result = sl.lint(valid_request)
        assert result["verdict"] == "PASS"

    def test_routine_workspace_bypasses_r18(self, valid_request):
        # status: current + projects/ path + unfamiliar name → routine workspace, no R18
        valid_request["target_path"] = "projects/pattern_trader/some_uncommon_name.md"
        result = sl.lint(valid_request)
        assert result["verdict"] == "PASS"

    def test_runbook_path_bypasses_r18(self, valid_request):
        # Phase 3: status: current Runbook is ops truth, classified routine not ceremony
        valid_request["target_path"] = "99-System/Runbook/claw/000_QUICK_STATUS.md"
        result = sl.lint(valid_request)
        assert result["verdict"] == "PASS"

    def test_non_whitelist_in_ceremony_path_fires_r18(self, valid_request):
        # human_only + ceremony-ish path + unknown filename → R18
        valid_request["writer_role"] = "human_only"
        valid_request["target_path"] = "claude_md/something_new.md"
        result = sl.lint(valid_request)
        assert result["verdict"] == "NEEDS_HUMAN"
        assert result["fail_at_rule"] == "R18"
        assert result["error_code"] == "DEFAULT_UPGRADE_FALLBACK"

    def test_draft_status_does_not_fire_r18(self, valid_frontmatter_lines, make_content):
        # status: draft + non-whitelist filename outside routine workspace → no R18
        # (R18 only triggers on status: current)
        draft_lines = [
            "status: draft",
            "valid_from: 2026-05-10",
            "owner: morgan",
            "project_id: ai_governance",
            "expires_at: 2026-05-25T00:00:00Z",
        ]
        req = {
            "writer_role": "human_only",
            "writer_engine": "claude",
            "target_path": "claude_md/draft_proposal.md",
            "operation": "create",
            "content": make_content(draft_lines),
            "branch": "main",
        }
        result = sl.lint(req)
        assert result["verdict"] == "PASS"


# ----------------------------------------------------------------------------
# R19 — Status upgrade gate (draft → current)
# ----------------------------------------------------------------------------

class TestR19StatusUpgrade:
    def test_draft_to_current_blocked(self, valid_request):
        valid_request["operation"] = "update"
        valid_request["previous_frontmatter"] = {"status": "draft"}
        result = sl.lint(valid_request)
        assert result["verdict"] == "NEEDS_HUMAN"
        assert result["fail_at_rule"] == "R19"
        assert result["error_code"] == "STATUS_UPGRADE_NEEDS_HUMAN"

    def test_current_to_current_passes(self, valid_request):
        valid_request["operation"] = "update"
        valid_request["previous_frontmatter"] = {"status": "current"}
        result = sl.lint(valid_request)
        assert result["verdict"] == "PASS"

    def test_create_with_previous_draft_does_not_fire_r19(self, valid_request):
        # R19 only triggers on update, not create
        valid_request["operation"] = "create"
        valid_request["previous_frontmatter"] = {"status": "draft"}
        result = sl.lint(valid_request)
        assert result["verdict"] == "PASS"

    def test_no_previous_no_r19(self, valid_request):
        result = sl.lint(valid_request)
        assert result["verdict"] == "PASS"

    def test_superseded_to_current_does_not_fire_r19(self, valid_request):
        # Only draft → current trips R19 (rename/delete to be handled at hook layer)
        valid_request["operation"] = "update"
        valid_request["previous_frontmatter"] = {"status": "superseded"}
        result = sl.lint(valid_request)
        assert result["verdict"] == "PASS"


# ----------------------------------------------------------------------------
# Ceremony classification helpers (used by R16/R18)
# ----------------------------------------------------------------------------

class TestCeremonyHelpers:
    def test_is_ceremony_filename_exact(self):
        assert sl._is_ceremony_filename("RULES.md")
        assert sl._is_ceremony_filename("DESIGN.md")
        assert sl._is_ceremony_filename("_global.md")
        assert sl._is_ceremony_filename("_shared.md")
        assert sl._is_ceremony_filename("CLAUDE.md")
        assert sl._is_ceremony_filename("AGENTS.md")

    def test_is_ceremony_filename_adr_pattern(self):
        assert sl._is_ceremony_filename("ADR_2026-05-11_topic.md")
        assert sl._is_ceremony_filename("ADR_initial.md")

    def test_is_ceremony_filename_negative(self):
        assert not sl._is_ceremony_filename("notes.md")
        assert not sl._is_ceremony_filename("slice_03.md")
        assert not sl._is_ceremony_filename("stop_work_2026-05-11.md")

    def test_is_routine_workspace(self):
        assert sl._is_routine_workspace("projects/pattern_trader/x.md")
        assert sl._is_routine_workspace("archive/old.md")
        assert sl._is_routine_workspace("00-Morgan/notes.md")
        assert sl._is_routine_workspace("decisions/concerns/c.md")
        assert sl._is_routine_workspace("decisions/verdicts/v.md")
        assert sl._is_routine_workspace("99-System/Runbook/claw/000_QUICK_STATUS.md")
        assert sl._is_routine_workspace("99-system/Runbook/claw/01_SYSTEM_STATE.md")
        assert not sl._is_routine_workspace("claude_md/x.md")
        assert not sl._is_routine_workspace("agents/guardian.md")
        assert not sl._is_routine_workspace("decisions/ADR_x.md")
        assert not sl._is_routine_workspace("99-System/AI_Governance/DESIGN.md")
