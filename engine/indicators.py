"""Indicators recomputed exactly as the lost engine did (spec §3.3, §4.1, §4.7, §4.9–§4.11).

Inputs are bar lists ``[[date, open, high, low, close, volume], ...]`` oldest first
(60-minute bars carry an ISO timestamp in column 0 but the same OHLCV layout).
All indicator functions compute on the FULL history and the caller slices the
last 250 bars for publication (spec §3.3: no warm-up NaN may reach a file).

Formulas (verified on the 9 published files, see ``tests/test_indicators.py``):
    ma5/ma20/ma60  simple rolling means of close                      (byte-exact)
    bb_up/bb_low   ma20 ± 2 × rolling std(20, ddof=1)                 (≤ 1.7e-11)
    rsi            Cutler RSI-14 (SMA of gains / SMA of losses)        (byte-exact)
                   loss-mean 0 → 100.0, both means 0 → 50.0 (spec Q-A8 defaults)
    macd/macd_sig/macd_hist   EMA 12/26 (pandas ewm adjust=False), signal EMA 9,
                   hist = macd − sig (plain difference)               (recursion exact)
    k/d            Taiwan KD(9,3,3): rsv = (c−L9)/(H9−L9)×100 (H9 == L9 → 50.0),
                   k = 2/3 k_prev + 1/3 rsv, d = 2/3 d_prev + 1/3 k; seeded with the
                   first rsv (pandas ``ewm(alpha=1/3, adjust=False)``, spec §4.1 /
                   04 §2.5).  Any seed converges to the published values after ≈ 70
                   bars; ``kd(bars, seed=50.0)`` gives the 50/50 convention.
    atr14          SMA-14 of the true range including the latest bar  (9/9 rows)
    sigma20        sample std (ddof=1) of the last 20 simple returns   (≤ 1e-16)
    trend          segments + summary of spec §4.9                     (9/9 exact)

Everything here is pure: no I/O, no clock, no state.  The published arrays are
produced by :func:`published`, which guarantees finite floats by back-filling
warm-up entries with the first finite value of the window (and a per-key neutral
fallback when a whole array is non-finite because the history is too short).
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

INDICATOR_KEYS = ("ma5", "ma20", "ma60", "bb_up", "bb_low", "rsi", "macd", "macd_sig", "macd_hist", "k", "d")
PUBLISH_BARS = 250

MA_WINDOWS = (5, 20, 60)
BB_WINDOW = 20
BB_MULT = 2.0
RSI_PERIOD = 14
MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9
KD_PERIOD = 9
KD_ALPHA = 1.0 / 3.0            # KD(9,3,3): K and D both smoothed with α = 1/3
ATR_PERIOD = 14
SIGMA_WINDOW = 20
TREND_MIN_RUN = 5               # spec §4.9 step 2: runs shorter than 5 bars are absorbed
TREND_LOOKBACK = 252            # spec Q-A15: high_252/low_252 over the trailing 252 closes
SLOPE_WINDOWS = (20, 60, 120)
TRADING_DAYS = 252

REGIME_BULL, REGIME_BEAR, REGIME_RANGE = "bull", "bear", "range"

# Neutral value used by ``published`` when a whole array is non-finite (history
# shorter than the indicator's warm-up).  ``None`` means "use the bar's close".
_FALLBACK = {
    "ma5": None, "ma20": None, "ma60": None, "bb_up": None, "bb_low": None,
    "rsi": 50.0, "macd": 0.0, "macd_sig": 0.0, "macd_hist": 0.0, "k": 50.0, "d": 50.0,
}

_COLUMNS = ("date", "open", "high", "low", "close", "volume")


# --------------------------------------------------------------------------- helpers

def _frame(bars: list) -> pd.DataFrame:
    """Bars → DataFrame with float OHLC columns (extra columns beyond 6 are ignored)."""
    rows = [list(b[:6]) for b in bars]
    df = pd.DataFrame(rows, columns=list(_COLUMNS)[: (len(rows[0]) if rows else 6)])
    for col in ("open", "high", "low", "close"):
        if col in df.columns:
            df[col] = df[col].astype(float)
    return df


def _finite(x) -> bool:
    try:
        return math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def _ema(x: pd.Series, span: int) -> pd.Series:
    """Recursive EMA, α = 2/(span+1), seeded with the first value (pandas adjust=False)."""
    return x.ewm(span=span, adjust=False).mean()


def _ols_slope(y: np.ndarray) -> float:
    """OLS slope of ``y`` against x = 0..len(y)-1; 0.0 when fewer than two points."""
    n = len(y)
    if n < 2:
        return 0.0
    x = np.arange(n, dtype=float)
    xm = x.mean()
    ym = y.mean()
    denom = float(((x - xm) ** 2).sum())
    if denom == 0.0:
        return 0.0
    return float(((x - xm) * (y - ym)).sum() / denom)


# --------------------------------------------------------------------------- building blocks

def rsi_series(close: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    """Cutler RSI: ``100 − 100/(1 + SMA(gain)/SMA(loss))`` with the Q-A8 guards."""
    diff = close.diff()
    gain = diff.clip(lower=0.0)
    loss = (-diff).clip(lower=0.0)
    g = gain.rolling(period).mean()
    l = loss.rolling(period).mean()
    with np.errstate(divide="ignore", invalid="ignore"):
        raw = 100.0 - 100.0 / (1.0 + g / l)
    gv = g.to_numpy()
    lv = l.to_numpy()
    out = raw.to_numpy(copy=True)
    warm = np.isnan(gv) | np.isnan(lv)
    zero_loss = (~warm) & (lv == 0.0)
    out[zero_loss & (gv > 0.0)] = 100.0
    out[zero_loss & (gv == 0.0)] = 50.0
    out[warm] = np.nan
    return pd.Series(out, index=close.index)


def kd(bars: list, seed: float | None = None) -> tuple:
    """KD(9,3,3) on any bar list → ``(k_list, d_list)`` aligned with ``bars``
    (NaN during the first 8 bars).  ``seed=None`` seeds K and D with the first rsv
    (pandas ``ewm(alpha=1/3, adjust=False)``); a number seeds both K and D with it
    (the 50/50 convention).  ``H9 == L9`` → rsv 50.0 (spec Q-A8)."""
    if not bars:
        return [], []
    df = _frame(bars)
    high, low, close = df["high"], df["low"], df["close"]
    h9 = high.rolling(KD_PERIOD).max()
    l9 = low.rolling(KD_PERIOD).min()
    denom = h9 - l9
    with np.errstate(divide="ignore", invalid="ignore"):
        rsv = (close - l9) / denom * 100.0
    rsv = rsv.where(~((denom == 0.0) & denom.notna()), 50.0)
    if seed is None:
        k = rsv.ewm(alpha=KD_ALPHA, adjust=False).mean()
        d = k.ewm(alpha=KD_ALPHA, adjust=False).mean()
        return k.tolist(), d.tolist()
    kp = dp = float(seed)
    ks, ds = [], []
    for v in rsv.tolist():
        if not _finite(v):
            ks.append(float("nan"))
            ds.append(float("nan"))
            continue
        kp = kp * (1.0 - KD_ALPHA) + v * KD_ALPHA
        dp = dp * (1.0 - KD_ALPHA) + kp * KD_ALPHA
        ks.append(kp)
        ds.append(dp)
    return ks, ds


def true_range(bars: list) -> list:
    """``TR[t] = max(h−l, |h−c[t−1]|, |l−c[t−1]|)``; the first bar uses ``h−l``."""
    out = []
    prev_close = None
    for b in bars:
        h, l, c = float(b[2]), float(b[3]), float(b[4])
        if prev_close is None:
            out.append(h - l)
        else:
            out.append(max(h - l, abs(h - prev_close), abs(l - prev_close)))
        prev_close = c
    return out


# --------------------------------------------------------------------------- public API

def compute(bars: list) -> dict:
    """``{key: [float] * len(bars)}`` for the 11 keys above (warm-up entries may be NaN)."""
    if not bars:
        return {key: [] for key in INDICATOR_KEYS}
    df = _frame(bars)
    close = df["close"]
    out: dict = {}
    for n in MA_WINDOWS:
        out[f"ma{n}"] = close.rolling(n).mean()
    sd = close.rolling(BB_WINDOW).std(ddof=1)
    out["bb_up"] = out["ma20"] + BB_MULT * sd
    out["bb_low"] = out["ma20"] - BB_MULT * sd
    out["rsi"] = rsi_series(close)
    macd = _ema(close, MACD_FAST) - _ema(close, MACD_SLOW)
    sig = _ema(macd, MACD_SIGNAL)
    out["macd"] = macd
    out["macd_sig"] = sig
    out["macd_hist"] = macd - sig
    k, d = kd(bars)
    result = {key: out[key].tolist() for key in INDICATOR_KEYS if key not in ("k", "d")}
    result["k"] = k
    result["d"] = d
    return {key: result[key] for key in INDICATOR_KEYS}


def _fill_finite(values: list, bars: list, key: str) -> list:
    """Replace non-finite entries: back-fill the head with the first finite value,
    forward-fill any later gap, and fall back to a neutral constant / the close
    when nothing finite exists at all."""
    n = len(bars)
    vals = [float(v) if _finite(v) else float("nan") for v in values]
    if len(vals) < n:
        vals = [float("nan")] * (n - len(vals)) + vals
    vals = vals[-n:] if n else []
    first = next((v for v in vals if _finite(v)), None)
    if first is None:
        fb = _FALLBACK.get(key)
        return [float(b[4]) if fb is None else fb for b in bars]
    out = []
    last = first
    for v in vals:
        if _finite(v):
            last = v
        out.append(last)
    return out


def published(bars: list, ind: dict, n: int = PUBLISH_BARS) -> tuple:
    """``(bars[-n:], {key: ind[key][-n:]})`` with every value a finite float (spec §3.3).

    ``ind`` must be aligned with ``bars`` (as returned by :func:`compute` on the same
    list).  When the history is shorter than an indicator's warm-up, the non-finite
    head of the window is back-filled with the first finite value; an array with no
    finite value at all becomes the bar closes (MA/BB keys), 50.0 (RSI, K, D) or 0.0
    (MACD family).  Published values are plain Python floats."""
    tail = list(bars[-n:]) if n else list(bars)
    out = {}
    for key in INDICATOR_KEYS:
        values = list(ind.get(key, []))
        out[key] = _fill_finite(values[-len(tail):] if tail else [], tail, key)
    return tail, out


def atr14(bars: list) -> float:
    """SMA-14 of the true range including the latest bar (spec §4.11).

    With fewer than 14 bars the mean of the available true ranges is used; an
    empty list gives 0.0."""
    tr = true_range(bars)
    if not tr:
        return 0.0
    window = tr[-ATR_PERIOD:]
    return float(sum(window) / len(window))


def sigma20(bars: list) -> float:
    """Sample std (ddof=1) of the last 20 simple daily returns (spec §4.10 baseline).

    Equals ``close.pct_change().tail(20).std(ddof=1)``; 0.0 when fewer than two
    returns are available or the result is not finite."""
    if len(bars) < 3:
        return 0.0
    close = pd.Series([float(b[4]) for b in bars])
    rets = close.pct_change().tail(SIGMA_WINDOW)
    if rets.notna().sum() < 2:
        return 0.0
    s = float(rets.std(ddof=1))
    return s if math.isfinite(s) else 0.0


def kd60(bars60: list) -> tuple:
    """KD(9,3,3) on 60-minute bars → ``(k, d, k_prev, d_prev)`` (spec §4.7, Q-A14).

    Unrounded values (``scoring.kd60_block`` rounds for publication).  Fewer than 9
    bars → ``(50.0, 50.0, 50.0, 50.0)``; when only one KD value exists the previous
    values repeat the current ones (no cross can fire)."""
    ks, ds = kd(bars60)
    pairs = [(k, d) for k, d in zip(ks, ds) if _finite(k) and _finite(d)]
    if not pairs:
        return 50.0, 50.0, 50.0, 50.0
    k, d = pairs[-1]
    kp, dp = pairs[-2] if len(pairs) >= 2 else (k, d)
    return float(k), float(d), float(kp), float(dp)


def regime_label(close: float, ma20: float, ma60: float) -> str:
    """Raw daily label (spec §4.9 step 1); any NaN input → ``range``."""
    if close > ma20 > ma60:
        return REGIME_BULL
    if close < ma20 < ma60:
        return REGIME_BEAR
    return REGIME_RANGE


def _segments(window: list, labels: list) -> list:
    """Run-length smoothing of spec §4.9 steps 2–3 on one window."""
    m = len(labels)
    final = list(labels)
    i = 0
    while i < m:
        j = i
        while j < m and labels[j] == labels[i]:
            j += 1
        if i > 0 and j - i < TREND_MIN_RUN:
            for t in range(i, j):
                final[t] = final[i - 1]
        i = j
    segs = []
    i = 0
    while i < m:
        j = i
        while j < m and final[j] == final[i]:
            j += 1
        c0 = float(window[i][4])
        c1 = float(window[j - 1][4])
        ret = round(c1 / c0 - 1.0, 4) if c0 != 0.0 else 0.0
        segs.append({"start": window[i][0], "end": window[j - 1][0], "regime": final[i], "ret": ret})
        i = j
    return segs


def trend(bars: list, ind: dict, n: int = PUBLISH_BARS) -> dict:
    """``{"segments": [{"start","end","regime","ret"}], "summary": {"regime","slope20","slope60",
    "slope120","dist_ma60","high_252","low_252","pos_252"}}`` on the published 250-bar window
    (spec §4.9; segments reproduce 9/9).

    ``ind`` is aligned with ``bars`` (either the full history with :func:`compute`'s
    output, or the published window with :func:`published`'s output).  Segments and
    the raw regime use the last ``n`` bars; ``high_252``/``low_252`` use the trailing
    252 closes of whatever history is given (spec Q-A15); slopes use the last 20/60/120
    closes (or all of them when the history is shorter).  Never emits NaN:
    ``dist_ma60`` is 0.0 when ``ma60`` is not finite, ``pos_252`` is 0.0 when
    ``high_252 == low_252``."""
    if not bars:
        return {"segments": [], "summary": {"regime": REGIME_RANGE, "slope20": 0.0, "slope60": 0.0,
                                            "slope120": 0.0, "dist_ma60": 0.0, "high_252": 0.0,
                                            "low_252": 0.0, "pos_252": 0.0}}
    total = len(bars)
    window = list(bars[-n:]) if n else list(bars)
    off = total - len(window)
    ma20 = list(ind.get("ma20", []))
    ma60 = list(ind.get("ma60", []))

    def _at(arr: list, i: int) -> float:
        j = i - (total - len(arr))
        if 0 <= j < len(arr) and _finite(arr[j]):
            return float(arr[j])
        return float("nan")

    labels = [regime_label(float(bars[i][4]), _at(ma20, i), _at(ma60, i)) for i in range(off, total)]
    segments = _segments(window, labels)

    closes = np.array([float(b[4]) for b in bars], dtype=float)
    last = float(closes[-1])
    summary = {"regime": labels[-1]}
    for w in SLOPE_WINDOWS:
        y = closes[-w:]
        y = y[y > 0.0]
        summary[f"slope{w}"] = round(_ols_slope(np.log(y)) * TRADING_DAYS * 100.0, 2)
    m60 = _at(ma60, total - 1)
    summary["dist_ma60"] = round(last / m60 - 1.0, 4) if _finite(m60) and m60 != 0.0 else 0.0
    tail = closes[-TREND_LOOKBACK:]
    hi = float(tail.max())
    lo = float(tail.min())
    summary["high_252"] = round(hi, 2)
    summary["low_252"] = round(lo, 2)
    summary["pos_252"] = round((last - lo) / (hi - lo), 4) if hi != lo else 0.0
    for key, val in summary.items():
        if isinstance(val, float) and not math.isfinite(val):
            summary[key] = 0.0
    return {"segments": segments, "summary": summary}
