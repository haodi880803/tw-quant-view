"""Shared fixtures: the frozen 2026-10-31 snapshot (golden data for every module test).

The snapshot copy under ``fixtures/snapshot-2026-10-31/`` never changes; the repo-root
published files are overwritten by every bake, so tests must read the fixture copy.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SNAPSHOT = ROOT / "fixtures" / "snapshot-2026-10-31"
CODES = ["2330", "2317", "2454", "2308", "2882", "0050", "6789", "3481", "2881"]


def _load(name: str):
    return json.loads((SNAPSHOT / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def snapshot_dir() -> Path:
    return SNAPSHOT


@pytest.fixture(scope="session")
def data() -> dict:
    return _load("data.json")


@pytest.fixture(scope="session")
def orders() -> list:
    return _load("orders.json")["orders"]


@pytest.fixture(scope="session")
def events() -> dict:
    return _load("events.json")


@pytest.fixture(scope="session")
def model_health() -> dict:
    return _load("model-health.json")


@pytest.fixture(scope="session")
def shadow() -> dict:
    return _load("shadow.json")


@pytest.fixture(scope="session")
def simple_html() -> str:
    return (SNAPSHOT / "simple.html").read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def symbols() -> dict:
    """``{code: symbol-file object}`` for the 9 watchlist symbols."""
    return {c: _load(f"symbol/{c}.json") for c in CODES}


@pytest.fixture(scope="session")
def v9_params() -> dict:
    """The active v9 params object (model-health.json params_history id 12)."""
    mh = _load("model-health.json")
    row = next(r for r in mh["params_history"] if r["id"] == 12)
    return json.loads(row["params_json"])


@pytest.fixture
def tmp_state(tmp_path, monkeypatch):
    """An empty ``state/`` directory wired through ``TWQ_STATE_DIR``."""
    d = tmp_path / "state"
    d.mkdir()
    monkeypatch.setenv("TWQ_STATE_DIR", str(d))
    return d


@pytest.fixture
def frozen_now(monkeypatch):
    monkeypatch.setenv("TWQ_NOW", "2026-10-31T14:15:22+08:00")
    return "2026-10-31T14:15:22+08:00"
