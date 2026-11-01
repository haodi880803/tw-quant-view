"""Parameters, manual adoption and the weekly walk-forward tuner (spec §6).

``params_json(params)`` must reproduce the byte-exact strings of spec §6.2 / §6.5
(``json.dumps(params)`` with default settings).  The tuner never touches
``fund_cap``, ``use_*``, ``exit`` or ``sizing`` (spec §6.9).
"""
from __future__ import annotations

from datetime import datetime

from .state import State

V9_PARAMS_JSON = ('{"buy_th": 3.0, "strong_th": 5.0, "sell_th": -3.0, "strong_sell_th": -5.0, '
                  '"weights": {"ma_align": 1.5, "ma_cross": 1.0, "rsi": 0.5, "macd": 1.0, "kd": 0.5, '
                  '"bb": 0.625, "volume": 1.5}, "fund_cap": 1.5, "use_market": true, '
                  '"use_fundamentals": true, "exit": {"stop_pct": 0.08, "trail_pct": 0.12}}')

V10_PARAMS_JSON = ('{"buy_th": 3.0, "strong_th": 5.0, "sell_th": -3.0, "strong_sell_th": -5.0, '
                   '"weights": {"ma_align": 1.8490543082236912, "ma_cross": 0.45138791133375156, '
                   '"rsi": 0.7840884945834798, "macd": 1.2517538359316402, "kd": 0.24447732513006493, '
                   '"bb": 1.2827766433755723, "volume": 1.4532856064819977}, "fund_cap": 1.5, '
                   '"use_market": true, "use_fundamentals": true, '
                   '"exit": {"stop_pct": 0.08300581937609232, "trail_pct": 0.206062542287206}, '
                   '"sizing": {"risk_frac": 0.008025956907855073, "strong_mult": 1.487336088988674, '
                   '"caution_scale": 0.5500015169427086, "persistence": 2.0}}')

# SAFE constants for params objects without a "sizing" key (v9 and earlier, spec §6.2)
SAFE_SIZING = {"risk_frac": 0.005, "strong_mult": 1.5, "caution_scale": 0.5, "persistence": 2.0}

ADOPT_THRESHOLD = 1.02
N_CANDIDATES = 64


def params_json(params: dict) -> str:
    """``json.dumps(params)`` (ASCII, default separators) — the ``params_history[].params_json`` string."""
    raise NotImplementedError


def sizing(params: dict) -> dict:
    """``params["sizing"]`` or the SAFE constants."""
    raise NotImplementedError


def active_params(st: State) -> dict:
    raise NotImplementedError


def adopt_manual(st: State, params: dict, reason: str, at: datetime) -> dict:
    """Prepend an adopted ``params_history`` row (next id, version + 1), set ``st.params``,
    ``engine.params_version`` and log ``調參採用新參數 v{n}:{reason}`` (spec §6.6)."""
    raise NotImplementedError


def reward_points(equity_curve: list) -> float:
    """Σ round(daily_ret × 1000) + 10 per new equity high (spec §6.9 default metric)."""
    raise NotImplementedError


def backtest(bars: list, ind: dict, params: dict) -> list:
    """Daily long-only equity curve of one symbol under ``params`` (tech signals only)."""
    raise NotImplementedError


def candidates(params: dict, seed: str, n: int = N_CANDIDATES) -> list:
    """Single-coordinate perturbations of the incumbent (spec §6.9), de-duplicated."""
    raise NotImplementedError


def tune(st: State, bars_all: dict, ind_all: dict, at: datetime, extra_candidate: dict | None = None) -> dict:
    """Walk-forward champion/challenger run; always writes a ``params_history`` row and the
    ``tuner`` result event; adopts when ``valid > champion × 1.02`` (spec §6.9).  Returns the row."""
    raise NotImplementedError
