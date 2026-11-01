"""Signal items, market tilt, composition and sizing (spec §4.2–§4.8, §4.11).

Every function is pure (no I/O).  Signal items have the published shape
``{"indicator", "label", "score", "note"}`` with ``score`` a float rounded to 2 dp
(``round(base × weight, 2)``, spec §4.2).  Chinese strings are byte-exact per the spec.
"""
from __future__ import annotations

from datetime import datetime

REC_TEXT = {"STRONG_BUY": "強力買進", "BUY": "買進", "HOLD": "觀望", "SELL": "賣出", "STRONG_SELL": "強力賣出"}
STRONG_GAP = 2.0


def tech_signals(bars: list, ind: dict, params: dict) -> tuple:
    """``(signals, tech_total)`` from the published 250-bar window (spec §4.2):
    均線排列, 均線交叉, RSI, MACD, KD, 布林通道, 成交量 — ``tech_total = Σ score`` (per-item rounding, no clipping)."""
    raise NotImplementedError


def fund_signals(info: dict | None, params: dict) -> tuple:
    """``(fund_signals, fund_total)`` from the fundamentals dict (spec §4.4); ``fund_total``
    1 dp and capped by ``params["fund_cap"]``; a metric whose source field is ``None`` is skipped."""
    raise NotImplementedError


def lexicon_score(title: str) -> int:
    """Rule-based title sentiment −3…+3 (spec §4.5 lexicon; AI fallback path)."""
    raise NotImplementedError


def news_block(items: list, at: datetime) -> dict:
    """Symbol-file ``news`` object ``{"score": 2 dp, "items": [...]}`` from scored items
    (each item already carries ``sentiment``/``score``); aggregation per spec Q-A12."""
    raise NotImplementedError


def chips_block(t86_hist: list) -> dict:
    """``{"score": 1 dp, "signals": [...], "recent": [10 newest first]}`` from
    ``[(date, {"foreign","invtrust","dealer","total"}), ...]`` ascending (spec §4.6, Q-A13)."""
    raise NotImplementedError


def kd60_block(k: float, d: float, k_prev: float, d_prev: float) -> dict:
    """``{"score","k","d","label","note"}`` (spec §4.7, Q-A14)."""
    raise NotImplementedError


def market_block(twii_bars: list, at: datetime, is_open: bool, index_now: float | None = None) -> dict:
    """``overview.market`` ``{"is_open","label","index","pct","regime_label","score"}`` (spec §4.3, Q-A1)."""
    raise NotImplementedError


def market_state(twii_bars: list) -> str:
    """``"halt"`` when 1-day ≤ −2.0 % or 5-day ≤ −3.5 %, else ``"normal"`` (spec §4.3, Q-A2)."""
    raise NotImplementedError


def compose(tech_total: float, mkt_score: float, fund_total: float, news_total: float,
            chips_total: float, kd60_total: float, params: dict) -> tuple:
    """``(total 1 dp, rec_code, rec_text)`` (spec §4.8; inclusive thresholds)."""
    raise NotImplementedError


def suggest_qty(cash: float, price: float, atr14: float, params: dict) -> int:
    """``floor(min(risk_frac×strong_mult×cash/atr14, 0.30×cash/price))`` (spec §4.11)."""
    raise NotImplementedError
