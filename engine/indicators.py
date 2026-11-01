"""Indicators recomputed exactly as the lost engine did (spec §4.1, §4.9, §4.11).

Inputs are bar lists ``[[date, open, high, low, close, volume], ...]`` oldest first.
All indicator functions compute on the FULL history and the caller slices the
last 250 bars for publication (spec §3.3: no warm-up NaN may reach a file).
Formulas (verified ≤ 1e-11 on the 9 published files, spec §4.1):
    ma5/ma20/ma60  simple rolling means of close
    bb_up/bb_low   ma20 ± 2 × rolling std(20, ddof=1)
    rsi            Cutler RSI-14 (SMA of gains / SMA of losses); loss 0 → 100, both 0 → 50
    macd/macd_sig/macd_hist   EMA 12/26 (pandas ewm adjust=False), signal EMA 9
    k/d            Taiwan KD(9,3,3): rsv = (c-L9)/(H9-L9)×100 (H9==L9 → 50), k = 2/3 k_prev + 1/3 rsv (k0=d0=50), d likewise
"""
from __future__ import annotations

INDICATOR_KEYS = ("ma5", "ma20", "ma60", "bb_up", "bb_low", "rsi", "macd", "macd_sig", "macd_hist", "k", "d")
PUBLISH_BARS = 250


def compute(bars: list) -> dict:
    """``{key: [float] * len(bars)}`` for the 11 keys above (warm-up entries may be NaN)."""
    raise NotImplementedError


def published(bars: list, ind: dict, n: int = PUBLISH_BARS) -> tuple:
    """``(bars[-n:], {key: ind[key][-n:]})`` with every value a finite float (spec §3.3)."""
    raise NotImplementedError


def atr14(bars: list) -> float:
    """SMA-14 of the true range including the latest bar (spec §4.11)."""
    raise NotImplementedError


def sigma20(bars: list) -> float:
    """Sample std (ddof=1) of the last 20 simple daily returns (spec §4.10 baseline)."""
    raise NotImplementedError


def kd60(bars60: list) -> tuple:
    """KD(9,3,3) on 60-minute bars → ``(k, d, k_prev, d_prev)`` (spec §4.7, Q-A14)."""
    raise NotImplementedError


def trend(bars: list, ind: dict) -> dict:
    """``{"segments": [{"start","end","regime","ret"}], "summary": {"regime","slope20","slope60",
    "slope120","dist_ma60","high_252","low_252","pos_252"}}`` on the published 250-bar window
    (spec §4.9; segments reproduce 9/9)."""
    raise NotImplementedError
