"""Test config for schema_lint tests.

Adds ``scripts/`` to sys.path so ``import schema_lint`` resolves, and
provides shared fixtures for building valid request payloads.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


@pytest.fixture
def fixed_now():
    """Stable ``now`` for date-sensitive tests (R11)."""
    return datetime(2026, 5, 10, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def stub_mutex_no_conflict():
    """Default R10 mutex checker: no conflict, gh available."""
    def _checker(target):
        return None, None
    return _checker


def _build_content(fm_lines, body="# Hello\n"):
    fm_block = "\n".join(fm_lines)
    return f"---\n{fm_block}\n---\n{body}"


@pytest.fixture
def make_content():
    """Helper to assemble markdown content with frontmatter lines."""
    return _build_content


@pytest.fixture
def valid_frontmatter_lines():
    """Baseline frontmatter for executor writing pattern_trader notes."""
    return [
        "status: current",
        "valid_from: 2026-05-10",
        "owner: morgan",
        "project_id: pattern_trader",
    ]


@pytest.fixture
def valid_request(valid_frontmatter_lines, make_content):
    """Minimal valid request that should PASS all 15 rules."""
    return {
        "writer_role": "executor",
        "writer_engine": "claude",
        "target_path": "projects/pattern_trader/notes/slice_03.md",
        "operation": "create",
        "content": make_content(valid_frontmatter_lines),
        "branch": "main",
    }
