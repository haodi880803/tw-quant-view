"""Forecasts, prediction ledger and model-health metrics (spec §4.10, §7.5, Q-F1…Q-F7, Q-P13).

Ledger rows live in ``state/predictions.jsonl`` (shape in ``state.py``); the frozen
aggregates recovered from the 2026-10-31 snapshot live in ``state/predictions_seed.json``
and are merged additively: n = n_seed + n_new, mae = (mae_seed·n_seed + Σ|err|_new)/n,
hit_rate = (hit_seed·n_seed + hits_new)/n; seed ``series`` rows are kept verbatim and a
new resolution week that collides with a seed week is merged the same way.
"""
from __future__ import annotations

from datetime import datetime

from .state import State

HORIZONS = (1, 5, 20)
MODELS = ("baseline", "ridge")


def baseline(bars: list) -> list:
    """Zero-drift horizons ``[{"horizon_days","pred_ret","ci68","ci95","prob_up","model"}]`` (exact, spec §4.10)."""
    raise NotImplementedError


def ridge(bars: list, ind: dict) -> list:
    """Ridge-regression horizons with the same shape (spec Q-F1 defaults; name stays ``"ridge"``)."""
    raise NotImplementedError


def fan(bars: list, horizons: list) -> dict:
    """21-point fan ``{"dates","median","lo68","hi68","lo95","hi95"}`` (spec §4.10, log-linear interpolation)."""
    raise NotImplementedError


def forecast_block(bars: list, ind: dict, model: str) -> dict:
    """Symbol-file ``forecast`` object for ``model`` (spec §7.2)."""
    raise NotImplementedError


def record(st: State, code: str, symbol: str, bars: list, ind: dict, at: datetime) -> int:
    """Upsert the 6 rows (2 models × 3 horizons) for ``made_date = bars[-1][0]``; returns rows written."""
    raise NotImplementedError


def resolve(st: State, code: str, bars: list, at: datetime) -> int:
    """Resolve every pending row whose target bar exists (spec Q-F4); returns the count."""
    raise NotImplementedError


def metrics(st: State) -> dict:
    """``model-health.json → metrics`` ``{"by_model_horizon","champion","series"}`` (spec §7.5)."""
    raise NotImplementedError


def ledger_block(st: State, code: str) -> dict:
    """Symbol-file ``ledger`` ``{"by_horizon": [...]}`` (spec §7.2; rows with n = 0 omitted)."""
    raise NotImplementedError


def brief(m: dict) -> dict:
    """``overview.model_health_brief`` from ``metrics()`` output (spec §4.10)."""
    raise NotImplementedError


def quality_drop(st: State, at: datetime) -> tuple:
    """``(triggered, hit5_pct, mae_worse_pct)`` per spec Q-F7."""
    raise NotImplementedError
