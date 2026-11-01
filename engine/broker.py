"""Paper broker: fills, fees, cost basis, positions, account, monthly reward (spec §5.1–§5.3, §8.6).

Account state lives in ``st.account`` (shape in ``state.py``).  Quotes are passed as
``{code: price}``.  All money is unrounded internally; published rounding is applied in
the view functions only.
"""
from __future__ import annotations

from datetime import datetime

from .state import State

INITIAL_CASH = 1000000.0
SLIPPAGE = 0.0005
FEE_RATE = 0.001425 * 0.6
FEE_MIN = 20
TAX_RATE = 0.003


def fill_price(side: str, price_hint: float) -> float:
    """BUY ``round(hint×1.0005, 2)``, SELL ``round(hint×0.9995, 2)`` (spec §5.2)."""
    raise NotImplementedError


def fee(gross: float) -> float:
    """``max(20, round(gross × 0.001425 × 0.6))`` as a float (spec §5.2)."""
    raise NotImplementedError


def tax(side: str, gross: float) -> float:
    """SELL ``round(gross × 0.003)``; BUY ``0.0``."""
    raise NotImplementedError


def fill(st: State, side: str, code: str, qty: int, price_hint: float, note: str,
         at: datetime, source: str = "autopilot") -> dict:
    """Execute a paper order: appends the order row (spec §7.3 shape), updates cash /
    positions / realized_pnl / peak, logs the ``broker`` event (spec §5.2) and returns the row."""
    raise NotImplementedError


def reject(st: State, side: str, code: str, qty: int, price_hint: float, reason: str,
           at: datetime, source: str = "autopilot") -> dict:
    """Write a ``REJECTED`` order row (spec §5.2 default) and return it."""
    raise NotImplementedError


def mark(st: State, quotes: dict) -> None:
    """``peak = max(peak, price)`` for every held symbol (spec §5.3)."""
    raise NotImplementedError


def exit_levels(pos: dict, params: dict) -> tuple:
    """``(stop_price, trail_price)`` 2 dp from the unrounded average and the peak (spec §5.3)."""
    raise NotImplementedError


def positions_view(st: State, quotes: dict, params: dict, rows_by_code: dict | None = None,
                   autopilot_on: bool = True) -> list:
    """``overview.positions[]`` in insertion order with ``verdict``/``reasons`` (spec §5.3, §7.1)."""
    raise NotImplementedError


def account_view(st: State, quotes: dict) -> dict:
    """``overview.account`` (spec §5.1, §7.1); ``unrealized`` uses the 2-dp average."""
    raise NotImplementedError


def equity(st: State, quotes: dict) -> float:
    raise NotImplementedError


def record_eod_equity(st: State, date: str, eq: float) -> None:
    raise NotImplementedError


def settle_month(st: State, at: datetime, twii_bars: list) -> dict | None:
    """Settle the previous month at the first EOD of a new month (spec §8.6); returns the history row."""
    raise NotImplementedError


def reward_view(st: State, equity_now: float, at: datetime) -> dict:
    """``overview.reward`` ``{"total","provisional","history"}`` (spec §7.1, §8.6)."""
    raise NotImplementedError
