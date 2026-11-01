"""Mode pipelines (spec §9.4): wire the modules in order for morning / scan / eod / tune / bake / replay.

``build_snapshot`` is the single place that assembles the publishable picture of the
watchlist from state + caches (+ fresh quotes when ``refresh`` is true); ``bake`` mode is
``build_snapshot(refresh=False)`` + ``publish.bake_all``.
"""
from __future__ import annotations

from datetime import datetime

from .state import State


def build_snapshot(st: State, at: datetime, kind: str, refresh: bool) -> dict:
    """See ``engine.publish`` for the snapshot shape."""
    raise NotImplementedError


def run_morning(st: State, at: datetime) -> dict:
    raise NotImplementedError


def run_scan(st: State, at: datetime, kind: str) -> dict:
    raise NotImplementedError


def run_eod(st: State, at: datetime) -> dict:
    raise NotImplementedError


def run_tune(st: State, at: datetime) -> dict:
    raise NotImplementedError


def run_bake(st: State, at: datetime) -> dict:
    raise NotImplementedError


def run(mode: str, kind: str, at: datetime | None = None) -> dict:
    """Entry point used by the CLI: loads state, runs the pipeline, saves state, bakes, commits."""
    raise NotImplementedError
