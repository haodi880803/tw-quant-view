"""Per-scan autopilot decision table (spec §5.4–§5.7, gates §5.5, sizing §5.6).

``rows`` are the freshly scored ``overview.rows[]`` dicts (watchlist order), ``quotes``
``{code: {"price","ts","fresh"}}``, ``atr`` ``{code: atr14}``; previous-EOD totals for
gate G4 come from ``st.eod["history"]``; market state from ``st.engine["market_state"]``.
Orders go through ``engine.broker.fill``.  Returns the list of order rows placed.
"""
from __future__ import annotations

from datetime import datetime

from .state import State

ORDERS_PER_SCAN = 3
STRONG_GAP = 2.0
SINGLE_POSITION_CAP = 0.40
CASH_CAP = 0.30


def size(cash_now: float, equity_now: float, pos_value: float, price_hint: float, atr14: float,
         prev_close: float, rec_code: str, market_state: str, params: dict) -> int:
    """Order quantity per spec §5.6 (strong_mult before the 0.30 cap, caution_scale after,
    minimum one share when affordable, 40 % single-position cap, round lots ≥ 1000)."""
    raise NotImplementedError


def run_scan(st: State, rows: list, quotes: dict, atr: dict, at: datetime) -> list:
    """Steps 0–9 of spec §5.4: mark peaks → exits (stop/trail/signal) → gates → swaps →
    entries/adds (descending ``total``, ≤ 3 orders per scan).  Logs every gate event."""
    raise NotImplementedError
