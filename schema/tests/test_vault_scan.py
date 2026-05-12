"""Tests for vault_scan (Phase 4 — Vault passive scan).

Covers:
- file discovery + exclude filtering (substring + glob, case behaviour)
- per-file scan (PASS / NEEDS_HUMAN / REJECT / ENCODING_FAILED)
- collect_violations (limit, exclude integration)
- render_markdown / render_json structure
- main() CLI flags (--dry-run / --limit / --exclude / --include-meta / --write)
- DEFAULT_META_EXCLUDES auto-applies unless --include-meta
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

# conftest.py adds scripts/ to sys.path
import vault_scan as vs
import schema_lint as sl


# ----------------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------------

VALID_FRONTMATTER = """---
status: current
valid_from: 2026-05-10
owner: morgan
project_id: pattern_trader
---
# valid doc
"""

# routine workspace path; status: current; ceremony filename not required
ROUTINE_VALID = """---
status: current
valid_from: 2026-05-10
owner: morgan
project_id: pattern_trader
---
# routine project doc, no rule-language keywords
"""

# scan-output stub: lives under INBOX, frontmatter ok for self-scan
INBOX_VALID = """---
status: current
valid_from: 2026-05-12
owner: morgan
project_id: ai_governance
generated_at: 2026-05-12T00:00:00Z
generator: vault_scan.py phase4-v1
---
# Vault scan inbox
"""

# Missing frontmatter -> R3 REJECT
NO_FRONTMATTER = "just text, no frontmatter at all\n"

# draft + invalid expires_at format (no Z) -> R11 REJECT
BAD_DRAFT = """---
status: draft
valid_from: 2026-05-10
owner: morgan
project_id: pattern_trader
expires_at: 2026-06-08
---
# draft with bad expires_at
"""


@pytest.fixture
def vault_root(tmp_path: Path) -> Path:
    """Build a small fake vault with mixed valid/violating files."""
    # ROUTINE region (projects/ prefix matches ROUTINE_WORKSPACE_PREFIXES)
    proj = tmp_path / "projects" / "pattern_trader"
    proj.mkdir(parents=True)
    (proj / "valid_routine.md").write_text(ROUTINE_VALID, encoding="utf-8")
    (proj / "no_fm.md").write_text(NO_FRONTMATTER, encoding="utf-8")
    (proj / "bad_draft.md").write_text(BAD_DRAFT, encoding="utf-8")

    # INBOX (auto-excluded by default)
    inbox = tmp_path / "99-System" / "AI_Governance" / "INBOX"
    inbox.mkdir(parents=True)
    (inbox / "scan_2026-05-12.md").write_text(INBOX_VALID, encoding="utf-8")

    # QUARTERLY (auto-excluded by default)
    quarterly = tmp_path / "99-System" / "AI_Governance" / "QUARTERLY"
    quarterly.mkdir(parents=True)
    (quarterly / "audit_2026-Q2.md").write_text(INBOX_VALID, encoding="utf-8")

    # Personal-notes lookalike for --exclude testing
    notes = tmp_path / "00-INBOX"
    notes.mkdir()
    (notes / "Morgan note.md").write_text(NO_FRONTMATTER, encoding="utf-8")

    return tmp_path


# ----------------------------------------------------------------------------
# _match_any_exclude
# ----------------------------------------------------------------------------

class TestMatchAnyExclude:
    def test_substring_match(self):
        assert vs._match_any_exclude("a/b/Morgan note.md", ["Morgan"])

    def test_substring_no_match(self):
        assert not vs._match_any_exclude("a/b/c.md", ["Morgan"])

    def test_glob_match(self):
        assert vs._match_any_exclude("phase1_draft/x.md", ["phase1_draft/*"])

    def test_glob_no_match(self):
        assert not vs._match_any_exclude("projects/x.md", ["phase1_draft/*"])

    def test_multiple_patterns_any_hits(self):
        assert vs._match_any_exclude("a/x.md", ["foo", "*/x.md"])

    def test_empty_patterns(self):
        assert not vs._match_any_exclude("anything.md", [])


# ----------------------------------------------------------------------------
# iter_md_files
# ----------------------------------------------------------------------------

class TestIterMdFiles:
    def test_finds_all_md(self, vault_root):
        rels = sorted(rel for _, rel in vs.iter_md_files(vault_root, []))
        # all 6 md files: projects/3 + INBOX/1 + QUARTERLY/1 + 00-INBOX/1
        assert len(rels) == 6

    def test_exclude_substring(self, vault_root):
        rels = [rel for _, rel in vs.iter_md_files(vault_root, ["Morgan"])]
        assert "00-INBOX/Morgan note.md" not in rels
        assert len(rels) == 5

    def test_exclude_glob(self, vault_root):
        rels = [rel for _, rel in vs.iter_md_files(vault_root, ["projects/*"])]
        assert not any(r.startswith("projects/") for r in rels)

    def test_returns_posix_paths(self, vault_root):
        rels = [rel for _, rel in vs.iter_md_files(vault_root, [])]
        assert all("\\" not in rel for rel in rels), "rel paths must be posix"


# ----------------------------------------------------------------------------
# scan_one
# ----------------------------------------------------------------------------

class TestScanOne:
    def test_pass_on_valid(self, vault_root):
        abs_path = vault_root / "projects" / "pattern_trader" / "valid_routine.md"
        result = vs.scan_one(abs_path, "projects/pattern_trader/valid_routine.md")
        assert result["verdict"] == "PASS"
        assert result["path"] == "projects/pattern_trader/valid_routine.md"
        assert result["file_mtime"] is not None

    def test_reject_on_missing_frontmatter(self, vault_root):
        abs_path = vault_root / "projects" / "pattern_trader" / "no_fm.md"
        result = vs.scan_one(abs_path, "projects/pattern_trader/no_fm.md")
        assert result["verdict"] == "REJECT"
        assert result["fail_at_rule"] == "R3"

    def test_reject_on_bad_draft(self, vault_root):
        abs_path = vault_root / "projects" / "pattern_trader" / "bad_draft.md"
        result = vs.scan_one(abs_path, "projects/pattern_trader/bad_draft.md")
        assert result["verdict"] == "REJECT"
        assert result["fail_at_rule"] in ("R11", "R14")

    def test_encoding_failed_on_non_utf8(self, tmp_path: Path):
        bad = tmp_path / "non_utf8.md"
        bad.write_bytes(b"\xff\xfe not utf-8 bytes here")
        result = vs.scan_one(bad, "non_utf8.md")
        assert result["verdict"] == "ERROR"
        assert result["error_code"] == "ENCODING_FAILED"
        assert result["fail_at_rule"] == "INPUT"

    def test_mtime_iso_format(self, vault_root):
        abs_path = vault_root / "projects" / "pattern_trader" / "valid_routine.md"
        result = vs.scan_one(abs_path, "x.md")
        mtime = result["file_mtime"]
        # parse YYYY-MM-DDTHH:MM:SSZ
        assert mtime is not None
        datetime.strptime(mtime, "%Y-%m-%dT%H:%M:%SZ")


# ----------------------------------------------------------------------------
# collect_violations
# ----------------------------------------------------------------------------

class TestCollectViolations:
    def test_counts_match(self, vault_root):
        violations, seen = vs.collect_violations(vault_root, exclude=[], limit=None)
        # 6 files scanned, 3 violations (no_fm + bad_draft + Morgan note)
        # The two INBOX/QUARTERLY files pass schema_lint scan mode (they have
        # valid frontmatter); valid_routine.md passes.
        assert seen == 6
        # Real violations: no_fm.md, bad_draft.md, Morgan note.md (all R3 or R11)
        assert len(violations) >= 3
        assert all(v["verdict"] != "PASS" for v in violations)

    def test_limit_caps_seen(self, vault_root):
        _, seen = vs.collect_violations(vault_root, exclude=[], limit=2)
        assert seen == 2

    def test_exclude_skips_files(self, vault_root):
        _, seen = vs.collect_violations(vault_root, exclude=["Morgan"], limit=None)
        assert seen == 5  # one fewer than 6

    def test_default_meta_excludes_filter_inbox_quarterly(self, vault_root):
        """When DEFAULT_META_EXCLUDES applied, INBOX + QUARTERLY skipped."""
        excludes = list(vs.DEFAULT_META_EXCLUDES)
        _, seen = vs.collect_violations(vault_root, exclude=excludes, limit=None)
        # 6 - 2 (INBOX + QUARTERLY) = 4
        assert seen == 4


# ----------------------------------------------------------------------------
# Rendering
# ----------------------------------------------------------------------------

class TestRenderMarkdown:
    def test_markdown_has_frontmatter(self, vault_root):
        violations, seen = vs.collect_violations(vault_root, exclude=[], limit=None)
        scan_dt = datetime(2026, 5, 12, 0, 0, tzinfo=timezone.utc)
        md = vs.render_markdown(
            violations, root=vault_root, scan_dt=scan_dt,
            files_seen=seen, user_exclude=[], auto_exclude=[],
            limit=None,
        )
        # frontmatter present
        assert md.startswith("---\n")
        assert "status: current" in md
        assert "project_id: ai_governance" in md
        assert "generated_at: 2026-05-12T00:00:00Z" in md

    def test_markdown_shows_summary(self, vault_root):
        violations, seen = vs.collect_violations(vault_root, exclude=[], limit=None)
        scan_dt = datetime(2026, 5, 12, 0, 0, tzinfo=timezone.utc)
        md = vs.render_markdown(
            violations, root=vault_root, scan_dt=scan_dt,
            files_seen=seen, user_exclude=[],
            auto_exclude=list(vs.DEFAULT_META_EXCLUDES),
            limit=None,
        )
        assert "## 摘要" in md
        assert "## 違規清單" in md
        assert "## 怎麼處理" in md
        assert "是" in md  # auto-exclude active

    def test_markdown_no_auto_exclude_shows_negative(self, vault_root):
        violations, seen = vs.collect_violations(vault_root, exclude=[], limit=None)
        scan_dt = datetime(2026, 5, 12, 0, 0, tzinfo=timezone.utc)
        md = vs.render_markdown(
            violations, root=vault_root, scan_dt=scan_dt,
            files_seen=seen, user_exclude=[],
            auto_exclude=[],
            limit=None,
        )
        assert "--include-meta" in md

    def test_markdown_empty_violations(self, tmp_path: Path):
        scan_dt = datetime(2026, 5, 12, 0, 0, tzinfo=timezone.utc)
        md = vs.render_markdown(
            [], root=tmp_path, scan_dt=scan_dt,
            files_seen=0, user_exclude=[], auto_exclude=[],
            limit=None,
        )
        assert "(無違規)" in md

    def test_markdown_self_scan_passes_schema(self, vault_root):
        """INBOX markdown itself should pass schema_lint(mode='scan')."""
        violations, seen = vs.collect_violations(vault_root, exclude=[], limit=None)
        scan_dt = datetime(2026, 5, 12, 0, 0, tzinfo=timezone.utc)
        md = vs.render_markdown(
            violations, root=vault_root, scan_dt=scan_dt,
            files_seen=seen, user_exclude=[],
            auto_exclude=list(vs.DEFAULT_META_EXCLUDES),
            limit=None,
        )
        # Feed back through schema_lint as if it lived at the INBOX path
        req = {
            "writer_role": None,
            "writer_engine": None,
            "target_path": "99-system/AI_Governance/INBOX/scan_2026-05-12.md",
            "operation": "update",
            "content": md,
            "branch": None,
            "morgan_ai_rules_root": None,
            "previous_frontmatter": None,
            "vault_files": None,
        }
        # Note: INBOX content may quote rule-language keywords inside violation
        # messages. That R16 hit on the meta doc itself is the *exact* reason
        # DEFAULT_META_EXCLUDES exists. So we accept either PASS or R16
        # NEEDS_HUMAN here — both prove the design holds.
        result = sl.lint(req, mode="scan")
        assert result["verdict"] in ("PASS", "NEEDS_HUMAN")
        if result["verdict"] == "NEEDS_HUMAN":
            assert result["fail_at_rule"] == "R16"


class TestRenderJson:
    def test_json_structure(self, vault_root):
        violations, seen = vs.collect_violations(vault_root, exclude=[], limit=None)
        scan_dt = datetime(2026, 5, 12, 0, 0, tzinfo=timezone.utc)
        out = vs.render_json(
            violations, root=vault_root, scan_dt=scan_dt,
            files_seen=seen, user_exclude=["foo"],
            auto_exclude=list(vs.DEFAULT_META_EXCLUDES),
            limit=10,
        )
        payload = json.loads(out)
        meta = payload["scan_meta"]
        assert meta["scan_date"] == "2026-05-12T00:00:00Z"
        assert meta["files_seen"] == seen
        assert meta["violations_count"] == len(violations)
        assert meta["user_exclude_patterns"] == ["foo"]
        assert meta["auto_exclude_patterns"] == list(vs.DEFAULT_META_EXCLUDES)
        assert meta["limit"] == 10
        assert meta["generator_version"] == vs.SCRIPT_VERSION
        assert isinstance(meta["rules_summary"], dict)
        assert isinstance(meta["verdict_summary"], dict)
        assert isinstance(payload["violations"], list)


# ----------------------------------------------------------------------------
# CLI main()
# ----------------------------------------------------------------------------

class TestMainCli:
    def test_missing_root_arg_errors(self):
        with pytest.raises(SystemExit) as exc:
            vs.main([])  # argparse exits 2 on missing required
        assert exc.value.code != 0

    def test_nonexistent_root_returns_1(self, tmp_path: Path, capsys):
        fake = tmp_path / "does_not_exist"
        rc = vs.main(["--root", str(fake), "--dry-run"])
        assert rc == 1

    def test_negative_limit_returns_1(self, vault_root, capsys):
        rc = vs.main(["--root", str(vault_root), "--limit", "-5", "--dry-run"])
        assert rc == 1

    def test_dry_run_no_payload_to_stdout(self, vault_root, capsys):
        rc = vs.main(["--root", str(vault_root), "--dry-run"])
        captured = capsys.readouterr()
        assert rc == 0
        assert captured.out == ""           # payload suppressed
        assert "scanned" in captured.err    # summary on stderr

    def test_default_auto_excludes_inbox_quarterly(self, vault_root, capsys):
        """Default run excludes INBOX/QUARTERLY (no --include-meta)."""
        rc = vs.main(["--root", str(vault_root), "--output", "json", "--dry-run"])
        captured = capsys.readouterr()
        assert rc == 0
        # Summary says scanned 4 (6 - 2 auto-excluded)
        assert "scanned 4 files" in captured.err

    def test_include_meta_scans_inbox_quarterly(self, vault_root, capsys):
        rc = vs.main(["--root", str(vault_root), "--include-meta",
                      "--output", "json", "--dry-run"])
        captured = capsys.readouterr()
        assert rc == 0
        assert "scanned 6 files" in captured.err

    def test_write_creates_file(self, vault_root, tmp_path, capsys):
        out_path = tmp_path / "out" / "scan.md"
        rc = vs.main([
            "--root", str(vault_root),
            "--output", "markdown",
            "--write", str(out_path),
        ])
        assert rc == 0
        assert out_path.exists()
        text = out_path.read_text(encoding="utf-8")
        assert text.startswith("---\n")
        assert "Vault 掃描收件匣" in text

    def test_stdout_payload_when_no_write(self, vault_root, capsys):
        rc = vs.main([
            "--root", str(vault_root),
            "--output", "json",
            "--limit", "1",
        ])
        captured = capsys.readouterr()
        assert rc == 0
        payload = json.loads(captured.out)
        assert "scan_meta" in payload
        assert "violations" in payload

    def test_user_exclude_combines_with_auto(self, vault_root, capsys):
        rc = vs.main([
            "--root", str(vault_root),
            "--exclude", "Morgan",
            "--output", "json",
        ])
        captured = capsys.readouterr()
        assert rc == 0
        payload = json.loads(captured.out)
        meta = payload["scan_meta"]
        assert meta["user_exclude_patterns"] == ["Morgan"]
        assert "99-System/AI_Governance/INBOX/" in meta["auto_exclude_patterns"]
        # 6 files - 2 auto - 1 user = 3 seen
        assert meta["files_seen"] == 3
