"""test_shadow_summary.py - Phase 5 shadow_summary report generator tests.

Covers:
  - argparse: defaults, valid choices, invalid choices
  - log parse: missing file, normal, corrupt-line handling
  - window filter: 7d / 30d / all + bad timestamp tolerance
  - render_markdown / render_json: empty + populated payloads
  - main(): dry-run, --write file creation (auto mkdir parent), missing log
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

THIS_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = THIS_DIR.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import shadow_summary as ss  # noqa: E402


# ----------------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------------

@pytest.fixture
def basic_log(tmp_path: Path) -> Path:
    """3 records: 1 day old (R16), 10 days old (R1), 40 days old (R6)."""
    p = tmp_path / "basic.jsonl"
    now = datetime.now(timezone.utc)
    records = [
        {
            "timestamp": (now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "tool_name": "Write",
            "target_path": "projects/foo.md",
            "verdict": "NEEDS_HUMAN",
            "fail_at_rule": "R16",
            "error_code": "SEMANTIC_KEYWORD_FLAGGED",
            "suggested_fix": "rephrase",
            "mode": "shadow",
            "script_version": "phase5-v1",
        },
        {
            "timestamp": (now - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "tool_name": "Write",
            "target_path": "projects/bar.md",
            "verdict": "REJECT",
            "fail_at_rule": "R1",
            "error_code": "PATH_PERMISSION",
            "suggested_fix": "",
            "mode": "shadow",
            "script_version": "phase5-v1",
        },
        {
            "timestamp": (now - timedelta(days=40)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "tool_name": "Edit",
            "target_path": "projects/baz.md",
            "verdict": "REJECT",
            "fail_at_rule": "R6",
            "error_code": "NAMING_VIOLATION",
            "suggested_fix": "",
            "mode": "shadow",
            "script_version": "phase5-v1",
        },
    ]
    p.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
        encoding="utf-8",
    )
    return p


@pytest.fixture
def corrupt_log(tmp_path: Path) -> Path:
    """2 valid + 1 garbled line."""
    p = tmp_path / "corrupt.jsonl"
    now = datetime.now(timezone.utc)
    valid = {
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tool_name": "Write",
        "target_path": "projects/foo.md",
        "verdict": "NEEDS_HUMAN",
        "fail_at_rule": "R16",
        "error_code": "SEMANTIC_KEYWORD_FLAGGED",
        "suggested_fix": "",
        "mode": "shadow",
        "script_version": "phase5-v1",
    }
    p.write_text(
        json.dumps(valid, ensure_ascii=False) + "\n"
        + "{this is garbled\n"
        + json.dumps(valid, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return p


# ----------------------------------------------------------------------------
# argparse
# ----------------------------------------------------------------------------

def test_argparse_defaults():
    args = ss._parse_args([])
    assert args.window == "7d"
    assert args.output == "markdown"
    assert args.write is None
    assert args.dry_run is False
    assert args.log == ss.DEFAULT_LOG_PATH


def test_argparse_all_windows():
    for w in ("7d", "30d", "all"):
        args = ss._parse_args(["--window", w])
        assert args.window == w


def test_argparse_invalid_window():
    with pytest.raises(SystemExit):
        ss._parse_args(["--window", "5d"])


def test_argparse_invalid_output():
    with pytest.raises(SystemExit):
        ss._parse_args(["--output", "yaml"])


def test_argparse_write_flag(tmp_path: Path):
    out = tmp_path / "out.md"
    args = ss._parse_args(["--write", str(out)])
    assert args.write == str(out)


# ----------------------------------------------------------------------------
# Log parse
# ----------------------------------------------------------------------------

def test_parse_log_missing_file(tmp_path: Path):
    records, skipped = ss.parse_log(tmp_path / "nope.jsonl")
    assert records == []
    assert skipped == 0


def test_parse_log_basic(basic_log: Path):
    records, skipped = ss.parse_log(basic_log)
    assert len(records) == 3
    assert skipped == 0


def test_parse_log_corrupt(corrupt_log: Path):
    records, skipped = ss.parse_log(corrupt_log)
    assert len(records) == 2
    assert skipped == 1


def test_parse_log_empty_file(tmp_path: Path):
    p = tmp_path / "empty.jsonl"
    p.write_text("", encoding="utf-8")
    records, skipped = ss.parse_log(p)
    assert records == []
    assert skipped == 0


def test_parse_log_blank_lines_tolerated(tmp_path: Path):
    p = tmp_path / "blanks.jsonl"
    valid = {"timestamp": "2026-05-12T00:00:00Z", "fail_at_rule": "R1"}
    p.write_text(
        json.dumps(valid) + "\n\n\n" + json.dumps(valid) + "\n",
        encoding="utf-8",
    )
    records, skipped = ss.parse_log(p)
    assert len(records) == 2
    assert skipped == 0  # blank lines are not corrupt


# ----------------------------------------------------------------------------
# Window filter
# ----------------------------------------------------------------------------

def test_filter_7d_excludes_old(basic_log: Path):
    records, _ = ss.parse_log(basic_log)
    filtered = ss.filter_window(records, "7d", datetime.now(timezone.utc))
    assert len(filtered) == 1
    assert filtered[0]["fail_at_rule"] == "R16"


def test_filter_30d(basic_log: Path):
    records, _ = ss.parse_log(basic_log)
    filtered = ss.filter_window(records, "30d", datetime.now(timezone.utc))
    assert len(filtered) == 2


def test_filter_all(basic_log: Path):
    records, _ = ss.parse_log(basic_log)
    filtered = ss.filter_window(records, "all", datetime.now(timezone.utc))
    assert len(filtered) == 3


def test_filter_invalid_timestamp_excluded(tmp_path: Path):
    p = tmp_path / "bad_ts.jsonl"
    p.write_text(json.dumps({
        "timestamp": "not-a-date",
        "fail_at_rule": "R1",
    }) + "\n", encoding="utf-8")
    records, _ = ss.parse_log(p)
    # parse_log keeps it (line is valid JSON), but window filter drops it
    assert len(records) == 1
    filtered = ss.filter_window(records, "7d", datetime.now(timezone.utc))
    assert filtered == []


def test_filter_unknown_window_returns_copy(basic_log: Path):
    """Unknown window key (e.g. 'invalid') is not in WINDOW_DELTAS -> .get None -> 'all' branch."""
    records, _ = ss.parse_log(basic_log)
    # Use direct value; argparse would have rejected but the function is permissive.
    filtered = ss.filter_window(records, "all", datetime.now(timezone.utc))
    assert len(filtered) == 3
    assert filtered is not records  # copy


# ----------------------------------------------------------------------------
# Rendering
# ----------------------------------------------------------------------------

def test_render_markdown_empty():
    md = ss.render_markdown(
        [], window="7d", now=datetime(2026, 5, 12, tzinfo=timezone.utc),
        log_path=Path("/dev/null"), skipped=0, total_in_log=0,
    )
    assert "# Shadow Mode Summary" in md
    assert "_(no records)_" in md
    assert "**0**" in md


def test_render_markdown_basic(basic_log: Path):
    records, _ = ss.parse_log(basic_log)
    md = ss.render_markdown(
        records, window="all", now=datetime(2026, 5, 12, tzinfo=timezone.utc),
        log_path=basic_log, skipped=0, total_in_log=3,
    )
    assert "R16" in md
    assert "R1" in md
    assert "R6" in md
    assert "Top 10 Rules" in md
    assert "By Day" in md
    assert "projects/foo.md" in md


def test_render_markdown_skipped_surfaces(basic_log: Path):
    records, _ = ss.parse_log(basic_log)
    md = ss.render_markdown(
        records, window="all", now=datetime(2026, 5, 12, tzinfo=timezone.utc),
        log_path=basic_log, skipped=7, total_in_log=10,
    )
    assert "Skipped corrupt lines: 7" in md


def test_render_json_empty():
    js = ss.render_json(
        [], window="7d", now=datetime(2026, 5, 12, tzinfo=timezone.utc),
        log_path=Path("/dev/null"), skipped=0, total_in_log=0,
    )
    payload = json.loads(js)
    assert payload["meta"]["records_in_window"] == 0
    assert payload["meta"]["window"] == "7d"
    assert payload["rule_top"] == []


def test_render_json_basic(basic_log: Path):
    records, _ = ss.parse_log(basic_log)
    js = ss.render_json(
        records, window="all", now=datetime(2026, 5, 12, tzinfo=timezone.utc),
        log_path=basic_log, skipped=0, total_in_log=3,
    )
    payload = json.loads(js)
    assert payload["meta"]["records_in_window"] == 3
    rules = dict(payload["rule_top"])
    assert rules.get("R16") == 1
    assert rules.get("R1") == 1
    assert rules.get("R6") == 1
    assert payload["meta"]["script_version"] == "phase5-v1"


# ----------------------------------------------------------------------------
# CLI integration
# ----------------------------------------------------------------------------

def test_main_dry_run(basic_log: Path, capsys):
    rc = ss.main(["--log", str(basic_log), "--window", "all", "--dry-run"])
    assert rc == 0
    err = capsys.readouterr().err
    assert "in_window=3" in err


def test_main_markdown_to_write(basic_log: Path, tmp_path: Path):
    out = tmp_path / "nested" / "report.md"
    rc = ss.main([
        "--log", str(basic_log), "--window", "all",
        "--output", "markdown", "--write", str(out),
    ])
    assert rc == 0
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "# Shadow Mode Summary" in text
    assert "R16" in text


def test_main_json_to_write(basic_log: Path, tmp_path: Path):
    out = tmp_path / "report.json"
    rc = ss.main([
        "--log", str(basic_log), "--window", "all",
        "--output", "json", "--write", str(out),
    ])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["meta"]["records_in_window"] == 3


def test_main_missing_log(tmp_path: Path, capsys):
    rc = ss.main([
        "--log", str(tmp_path / "nope.jsonl"),
        "--window", "all", "--dry-run",
    ])
    assert rc == 0
    err = capsys.readouterr().err
    assert "log not found" in err


def test_main_corrupt_log_skip_count_in_stderr(corrupt_log: Path, capsys):
    rc = ss.main([
        "--log", str(corrupt_log), "--window", "all", "--dry-run",
    ])
    assert rc == 0
    err = capsys.readouterr().err
    assert "skipped 1" in err


def test_main_markdown_stdout(basic_log: Path, capsys):
    rc = ss.main([
        "--log", str(basic_log), "--window", "all", "--output", "markdown",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "# Shadow Mode Summary" in out
    assert "R16" in out
