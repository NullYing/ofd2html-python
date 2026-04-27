"""Pytest fixtures: parameterise across every OFD in repo-root ``tests_ofd/``."""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_DIR = REPO_ROOT / "tests_ofd"
SAMPLES = sorted(SAMPLE_DIR.glob("*.ofd"))


@pytest.fixture(params=SAMPLES, ids=lambda p: p.name)
def ofd_path(request) -> Path:
    return request.param


@pytest.fixture
def ofd_bytes(ofd_path: Path) -> bytes:
    return ofd_path.read_bytes()
