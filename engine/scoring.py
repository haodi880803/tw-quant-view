"""Signal items, market tilt, composition and sizing (spec §4.2–§4.8, §4.11).

Every function is pure (no I/O).  Signal items have the published shape
``{"indicator", "label", "score", "note"}`` with ``score`` a float rounded to 2 dp
(``round(base × weight, 2)``, spec §4.2).  Chinese strings are byte-exact per the spec
(ASCII ``,`` ``(`` ``)`` inside notes, full-width only where the spec shows it).

Base scores live here (spec §6.1); the weights live in the params object, so the
published score is ``round(base × weights[key], 2)`` with Python's half-even ``round``
(``round(1.0 × 0.625, 2) == 0.62`` is load-bearing).

Defaults chosen where the spec leaves a question open (§10.2 Q-A1…Q-A17) are marked
``*default*`` in the docstrings so the integrator can find them.
"""
from __future__ import annotations

import math
from datetime import datetime
from zoneinfo import ZoneInfo

_TZ = ZoneInfo("Asia/Taipei")

REC_TEXT = {"STRONG_BUY": "強力買進", "BUY": "買進", "HOLD": "觀望", "SELL": "賣出", "STRONG_SELL": "強力賣出"}
STRONG_GAP = 2.0

# Base scores of the technical groups (spec §6.1 / §4.2); weights come from params["weights"].
BASE_MA_ALIGN = 2.0
BASE_MA_CROSS = 1.0
BASE_RSI = 1.5
BASE_MACD = 0.5
BASE_KD_CROSS = 1.5
BASE_KD_ZONE = 1.0
BASE_BB = 1.0
BASE_VOLUME = 1.0

RSI_LOW, RSI_HIGH = 30.0, 70.0
KD_LOW, KD_HIGH = 20.0, 80.0
VOLUME_WINDOW = 20            # bars, including today (spec §4.2, Q-A5)
VOLUME_RATIO_TH = 1.5         # *default* ∈ (1.25, 1.55]

FUND_CAP_DEFAULT = 1.5
CHIPS_CAP = 1.5
CHIPS_STREAK_STRONG = 5       # n ≥ 5 → ±1.5
CHIPS_STREAK_WEAK = 3         # 3 ≤ n < 5 → ±1.0 (Q-A13)
CHIPS_INVTRUST_DAYS = 5
CHIPS_Z_WINDOW = 60           # trading days of 3-day sums the z-score is measured against
CHIPS_Z_MIN_DAYS = 10         # *default*: fewer days of T86 history → no 法人動能 signal
CHIPS_Z_TH = 1.0

NEWS_MAX_ITEMS = 8
NEWS_DIVISOR = 6.0
NEWS_HALF_LIFE_HOURS = 24.0
NEWS_CAP = 3.0

KD60_LOW, KD60_HIGH = 20.0, 80.0

# Market tilt (spec §4.3, Q-A1).  ``MARKET_FOUR_STATE`` is the config switch for the
# unobserved ±1.0 states; with it off they collapse to the observed ±0.5 labels.
MARKET_FOUR_STATE = True
HALT_1D_PCT = -2.0            # Q-A2
HALT_5D_PCT = -3.5

# Sizing (spec §4.11 / §6.2): SAFE constants for params objects without a "sizing" key.
SAFE_SIZING = {"risk_frac": 0.005, "strong_mult": 1.5, "caution_scale": 0.5, "persistence": 2.0}
ORDER_CASH_CAP = 0.30

# Title-sentiment lexicon (spec §4.5, Q-A11; *default* — the original lexicon is lost).
LEXICON = {
    "跌停": -2, "重挫": -2, "慘跌": -2, "崩": -2,
    "砍目標價": -1, "虧損": -1, "下殺": -1,
    "創新高": 2, "漲停": 2,
    "大賺": 1, "買點": 1, "利多": 1,
}


# ----------------------------------------------------------------------------- helpers

def _r(x: float, n: int) -> float:
    """``round`` (half-even) that never returns ``-0.0``."""
    return round(float(x), n) + 0.0


def _item(indicator: str, label: str, score: float, note: str) -> dict:
    return {"indicator": indicator, "label": label, "score": float(score), "note": note}


def _wscore(base: float, weights: dict, key: str) -> float:
    """``round(base × weights[key], 2)`` — a missing weight counts as 1.0."""
    return _r(base * float(weights.get(key, 1.0)), 2)


def _last(ind: dict, key: str, offset: int = -1) -> float:
    seq = ind[key]
    v = float(seq[offset])
    if not math.isfinite(v):
        raise ValueError(f"non-finite indicator {key}[{offset}]")
    return v


def _num(x) -> float | None:
    """Finite float or ``None`` (missing / non-numeric source field is skipped, Q-A9)."""
    if x is None or isinstance(x, bool):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _mean(xs: list) -> float:
    return sum(xs) / len(xs)


def _pstd(xs: list) -> float:
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / len(xs))


def sizing(params: dict) -> dict:
    """``params["sizing"]`` or the SAFE constants (v9 and earlier have no ``sizing`` key)."""
    sz = params.get("sizing") if isinstance(params, dict) else None
    out = dict(SAFE_SIZING)
    if isinstance(sz, dict):
        out.update({k: float(v) for k, v in sz.items() if _num(v) is not None})
    return out


def sentiment(score: float) -> str:
    """``"pos"`` if ``score > 0``, ``"neg"`` if ``< 0``, ``"neu"`` otherwise (spec §4.5)."""
    return "pos" if score > 0 else "neg" if score < 0 else "neu"


# --------------------------------------------------------------------- technical signals

def tech_signals(bars: list, ind: dict, params: dict) -> tuple:
    """``(signals, tech_total)`` from the published 250-bar window (spec §4.2):
    均線排列, 均線交叉, RSI, MACD, KD, 布林通道, 成交量 — ``tech_total = Σ score`` (per-item rounding, no clipping).

    ``bars`` rows are ``[date, open, high, low, close, volume]`` (oldest first); ``ind`` holds the
    aligned indicator arrays ``ma5, ma20, ma60, bb_up, bb_low, rsi, macd_hist, k, d`` (finite
    values; the indicators module guarantees that).  The volume ratio is
    ``volume[-1] / mean(volume[-20:])`` (20 bars including today, *default* Q-A5) — to score a
    live scan with a realtime volume, substitute it into ``bars[-1][5]`` before calling.
    """
    if len(bars) < 2:
        raise ValueError("tech_signals needs at least two bars")
    w = params.get("weights", {})
    close = float(bars[-1][4])
    prev_close = float(bars[-2][4])
    ma5, ma20, ma60 = _last(ind, "ma5"), _last(ind, "ma20"), _last(ind, "ma60")
    rsi = _last(ind, "rsi")
    hist = _last(ind, "macd_hist")
    k, d = _last(ind, "k"), _last(ind, "d")
    bb_up, bb_low = _last(ind, "bb_up"), _last(ind, "bb_low")
    have_prev = len(ind["ma5"]) >= 2 and len(ind["k"]) >= 2
    ma5_p = _last(ind, "ma5", -2) if have_prev else None
    ma20_p = _last(ind, "ma20", -2) if have_prev else None
    k_p = _last(ind, "k", -2) if have_prev else None
    d_p = _last(ind, "d", -2) if have_prev else None

    signals: list[dict] = []

    # 均線排列 — always (strict inequalities, Q-A7)
    if ma5 > ma20 > ma60:
        signals.append(_item("均線排列", "多頭排列", _wscore(BASE_MA_ALIGN, w, "ma_align"), "MA5>MA20>MA60,趨勢偏多"))
    elif ma5 < ma20 < ma60:
        signals.append(_item("均線排列", "空頭排列", _wscore(-BASE_MA_ALIGN, w, "ma_align"), "MA5<MA20<MA60,趨勢偏空"))
    else:
        signals.append(_item("均線排列", "糾結", _wscore(0.0, w, "ma_align"), "均線糾結,方向不明"))

    # 均線交叉 — same-day MA5/MA20 cross only (*default* Q-A4; strings unverified)
    if have_prev:
        if ma5_p <= ma20_p and ma5 > ma20:
            signals.append(_item("均線交叉", "黃金交叉", _wscore(BASE_MA_CROSS, w, "ma_cross"), "MA5 上穿 MA20,短線轉強"))
        elif ma5_p >= ma20_p and ma5 < ma20:
            signals.append(_item("均線交叉", "死亡交叉", _wscore(-BASE_MA_CROSS, w, "ma_cross"), "MA5 下穿 MA20,短線轉弱"))

    # RSI — always; %d = round()
    rsi_i = round(rsi)
    if rsi < RSI_LOW:
        signals.append(_item("RSI", "超賣", _wscore(BASE_RSI, w, "rsi"), f"RSI={rsi_i}<30,跌深可能反彈"))
    elif rsi > RSI_HIGH:
        signals.append(_item("RSI", "超買", _wscore(-BASE_RSI, w, "rsi"), f"RSI={rsi_i}>70,漲多可能回檔"))
    else:
        signals.append(_item("RSI", "中性", _wscore(0.0, w, "rsi"), f"RSI={rsi_i}"))

    # MACD — always; hist ≥ 0 → 紅柱 (Q-A7)
    if hist >= 0:
        signals.append(_item("MACD", "紅柱", _wscore(BASE_MACD, w, "macd"), "柱狀體在零軸上,動能偏多"))
    else:
        signals.append(_item("MACD", "綠柱", _wscore(-BASE_MACD, w, "macd"), "柱狀體在零軸下,動能偏空"))

    # KD — conditional; cross before zone; one item per group
    k_i, d_i = round(k), round(d)
    if have_prev and k_p >= d_p and k < d:
        signals.append(_item("KD", "死亡交叉", _wscore(-BASE_KD_CROSS, w, "kd"), f"K={k_i} 下穿 D={d_i}"))
    elif have_prev and k_p <= d_p and k > d:
        signals.append(_item("KD", "黃金交叉", _wscore(BASE_KD_CROSS, w, "kd"), f"K={k_i} 上穿 D={d_i}"))
    elif k < KD_LOW:
        signals.append(_item("KD", "低檔", _wscore(BASE_KD_ZONE, w, "kd"), f"K={k_i}<20,低檔區"))
    elif k > KD_HIGH:
        signals.append(_item("KD", "高檔", _wscore(-BASE_KD_ZONE, w, "kd"), f"K={k_i}>80,高檔區"))

    # 布林通道 — conditional, on close (*default* Q-A7)
    if close < bb_low:
        signals.append(_item("布林通道", "觸下軌", _wscore(BASE_BB, w, "bb"), "跌破下軌,偏弱但可能超跌反彈"))
    elif close > bb_up:
        signals.append(_item("布林通道", "觸上軌", _wscore(-BASE_BB, w, "bb"), "突破上軌,偏強但可能過熱"))

    # 成交量 — conditional
    ratio = volume_ratio(bars)
    if ratio >= VOLUME_RATIO_TH and close < prev_close:
        signals.append(_item("成交量", "帶量下跌", _wscore(-BASE_VOLUME, w, "volume"), f"量為均量 {ratio:.1f} 倍,量增價跌"))
    elif ratio >= VOLUME_RATIO_TH and close > prev_close:
        signals.append(_item("成交量", "帶量上漲", _wscore(BASE_VOLUME, w, "volume"), f"量為均量 {ratio:.1f} 倍,量增價漲"))

    tech_total = _r(sum(s["score"] for s in signals), 2)
    return signals, tech_total


def volume_ratio(bars: list, window: int = VOLUME_WINDOW) -> float:
    """``volume[-1] / mean(volume[-window:])`` (window includes today); ``0.0`` when undefined."""
    vols = [float(b[5] or 0) for b in bars[-window:]]
    if not vols:
        return 0.0
    mean = _mean(vols)
    return vols[-1] / mean if mean > 0 else 0.0


# ------------------------------------------------------------------------- fundamentals

def fund_signals(info: dict | None, params: dict) -> tuple:
    """``(fund_signals, fund_total)`` from the fundamentals dict (spec §4.4); ``fund_total``
    1 dp and capped by ``params["fund_cap"]``; a metric whose source field is ``None`` is skipped.

    ``info`` uses the yfinance ``Ticker.info`` keys (fractions): ``returnOnEquity``,
    ``revenueGrowth``, ``earningsGrowth``, ``grossMargins`` and ``trailingPE`` (plain number).
    Thresholds (*default*, spec §4.4 / Q-A9): ROE ``≥ 0.20 → 0.7``, ``> 0 → 0.3``; revenue
    ``≥ 0.20 → 0.7``, ``> 0 → 0.3``, ``< 0 → −0.5``; earnings ``> 0 → 0.4``, ``< 0 → −0.4``;
    gross margin ``≥ 0.25 → 0.3``; PE ``> 50 → −0.3``.  Nothing fired → the single
    ``基本面/中性`` placeholder.  ``use_fundamentals`` false → ``([], 0.0)``.
    """
    if not params.get("use_fundamentals", True):
        return [], 0.0
    cap = _num(params.get("fund_cap"))
    cap = FUND_CAP_DEFAULT if cap is None else abs(cap)
    info = info or {}
    items: list[dict] = []

    roe = _num(info.get("returnOnEquity"))
    if roe is not None:
        if roe >= 0.20:
            items.append(_item("ROE", f"{roe * 100:.0f}%", 0.7, "股東權益報酬率高,獲利能力強"))
        elif roe > 0:
            items.append(_item("ROE", f"{roe * 100:.0f}%", 0.3, "ROE 尚可"))

    rev = _num(info.get("revenueGrowth"))
    if rev is not None:
        if rev >= 0.20:
            items.append(_item("營收成長", f"{rev * 100:.0f}%", 0.7, "營收年增率高,成長強"))
        elif rev > 0:
            items.append(_item("營收成長", f"{rev * 100:.0f}%", 0.3, "營收正成長"))
        elif rev < 0:
            items.append(_item("營收成長", f"{rev * 100:.0f}%", -0.5, "營收衰退"))

    earn = _num(info.get("earningsGrowth"))
    if earn is not None:
        if earn > 0:
            items.append(_item("盈餘成長", f"{earn * 100:.0f}%", 0.4, "獲利成長"))
        elif earn < 0:
            items.append(_item("盈餘成長", f"{earn * 100:.0f}%", -0.4, "獲利衰退"))

    gm = _num(info.get("grossMargins"))
    if gm is not None and gm >= 0.25:
        items.append(_item("毛利率", f"{gm * 100:.0f}%", 0.3, "高毛利,具競爭力"))

    pe = _num(info.get("trailingPE"))
    if pe is not None and pe > 50:
        items.append(_item("本益比", f"{pe:.0f}", -0.3, "本益比偏高,評價偏貴"))

    if not items:
        items.append(_item("基本面", "中性", 0.0, "基本面無明顯偏多或偏空訊號"))
    total = sum(it["score"] for it in items)
    return items, _r(min(max(total, -cap), cap), 1)


# --------------------------------------------------------------------------------- news

def lexicon_score(title: str) -> int:
    """Rule-based title sentiment −3…+3 (spec §4.5 lexicon; AI fallback path).

    Every occurrence of a lexicon keyword adds its weight; the sum is clipped to ±3.
    """
    text = title or ""
    total = sum(weight * text.count(word) for word, weight in LEXICON.items())
    return max(-3, min(3, int(total)))


def _age_hours(published, at: datetime) -> float:
    """Hours between ``published`` (ISO string or datetime) and ``at``; unparsable → 0."""
    if at.tzinfo is None:
        at = at.replace(tzinfo=_TZ)
    try:
        pub = published if isinstance(published, datetime) else datetime.fromisoformat(str(published))
    except (TypeError, ValueError):
        return 0.0
    if pub.tzinfo is None:
        pub = pub.replace(tzinfo=_TZ)
    return max(0.0, (at - pub).total_seconds() / 3600.0)


def news_block(items: list, at: datetime) -> dict:
    """Symbol-file ``news`` object ``{"score": 2 dp, "items": [...]}`` from scored items
    (each item already carries ``sentiment``/``score``); aggregation per spec Q-A12.

    Keeps the first ``NEWS_MAX_ITEMS`` items in feed order and re-emits each as
    ``{"title", "link", "source", "published", "sentiment", "score"}`` with ``score`` a float
    and ``sentiment`` derived from its sign.  ``score = round(clip(Σ w_i·s_i / 6, ±3), 2)``
    with ``w_i = 0.5 ** (age_hours_i / 24)`` measured from ``at`` (the refresh time) —
    *default*, not fully determined by the data.  Empty → ``{"score": 0.0, "items": []}``.
    """
    kept: list[dict] = []
    acc = 0.0
    for raw in list(items or [])[:NEWS_MAX_ITEMS]:
        s = _num(raw.get("score"))
        s = 0.0 if s is None else float(s)
        kept.append({
            "title": str(raw.get("title", "") or ""),
            "link": str(raw.get("link", "") or ""),
            "source": str(raw.get("source", "") or ""),
            "published": str(raw.get("published", "") or ""),
            "sentiment": sentiment(s),
            "score": s,
        })
        acc += (0.5 ** (_age_hours(raw.get("published"), at) / NEWS_HALF_LIFE_HOURS)) * s
    if not kept:
        return {"score": 0.0, "items": []}
    score = _r(min(max(acc / NEWS_DIVISOR, -NEWS_CAP), NEWS_CAP), 2)
    return {"score": score, "items": kept}


# -------------------------------------------------------------------------------- chips

def _chips_row(date, rec: dict) -> dict:
    f = int(_num(rec.get("foreign")) or 0)
    iv = int(_num(rec.get("invtrust")) or 0)
    dl = int(_num(rec.get("dealer")) or 0)
    t = _num(rec.get("total"))
    return {"date": str(date), "foreign": f, "invtrust": iv, "dealer": dl,
            "total": int(t) if t is not None else f + iv + dl}


def chips_zscore(totals_asc: list) -> float | None:
    """z of the latest 3-day sum of ``total`` against the rolling 3-day sums over the last
    ``CHIPS_Z_WINDOW`` trading days (population std, *default* Q-A13); ``None`` when fewer than
    ``CHIPS_Z_MIN_DAYS`` days are available or the std is 0."""
    xs = [float(x) for x in totals_asc[-CHIPS_Z_WINDOW:]]
    if len(xs) < max(CHIPS_Z_MIN_DAYS, 3):
        return None
    sums = [xs[i - 2] + xs[i - 1] + xs[i] for i in range(2, len(xs))]
    std = _pstd(sums)
    if std <= 0:
        return None
    return (sums[-1] - _mean(sums)) / std


def chips_block(t86_hist: list) -> dict:
    """``{"score": 1 dp, "signals": [...], "recent": [10 newest first]}`` from
    ``[(date, {"foreign","invtrust","dealer","total"}), ...]`` ascending (spec §4.6, Q-A13).

    外資動向: streak of ``foreign > 0`` / ``< 0`` from the newest day backwards (a 0 day breaks
    it): ``n ≥ 5 → ±1.5``, ``3 ≤ n < 5 → ±1.0``.  投信動向: all of the last 5 days ``invtrust``
    strictly the same sign → ``±0.5``.  法人動能: ``chips_zscore`` ``≥ +1 / ≤ −1 → ±0.5``.
    ``score = round(clip(Σ, ±1.5), 1)``.  Empty history → ``{"score": 0.0, "signals": [], "recent": []}``.
    """
    rows = [_chips_row(dt, rec) for dt, rec in (t86_hist or [])]
    if not rows:
        return {"score": 0.0, "signals": [], "recent": []}
    desc = list(reversed(rows))
    recent = [dict(r) for r in desc[:10]]
    signals: list[dict] = []

    # 外資動向
    f0 = desc[0]["foreign"]
    n = 0
    if f0 > 0:
        for r in desc:
            if r["foreign"] > 0:
                n += 1
            else:
                break
    elif f0 < 0:
        for r in desc:
            if r["foreign"] < 0:
                n += 1
            else:
                break
    if n >= CHIPS_STREAK_WEAK:
        mag = 1.5 if n >= CHIPS_STREAK_STRONG else 1.0
        if f0 > 0:
            signals.append(_item("外資動向", f"外資連買{n}日", mag, f"外資連續 {n} 個交易日買超"))
        else:
            signals.append(_item("外資動向", f"外資連賣{n}日", -mag, f"外資連續 {n} 個交易日賣超"))

    # 投信動向
    if len(desc) >= CHIPS_INVTRUST_DAYS:
        last5 = [r["invtrust"] for r in desc[:CHIPS_INVTRUST_DAYS]]
        if all(v > 0 for v in last5):
            signals.append(_item("投信動向", "投信買超", 0.5, "近 5 日投信買賣超同向(無反向日)"))
        elif all(v < 0 for v in last5):
            signals.append(_item("投信動向", "投信賣超", -0.5, "近 5 日投信買賣超同向(無反向日)"))

    # 法人動能
    z = chips_zscore([r["total"] for r in rows])
    if z is not None:
        if z >= CHIPS_Z_TH:
            signals.append(_item("法人動能", "法人買盤動能", 0.5, f"近 3 日三大法人合計 z 分數 {z:+.2f}(相對近 60 日)"))
        elif z <= -CHIPS_Z_TH:
            signals.append(_item("法人動能", "法人賣壓動能", -0.5, f"近 3 日三大法人合計 z 分數 {z:+.2f}(相對近 60 日)"))

    total = sum(s["score"] for s in signals)
    return {"score": _r(min(max(total, -CHIPS_CAP), CHIPS_CAP), 1), "signals": signals, "recent": recent}


# ---------------------------------------------------------------------------- 60-min KD

def kd60_block(k: float, d: float, k_prev: float, d_prev: float) -> dict:
    """``{"score","k","d","label","note"}`` (spec §4.7, Q-A14).

    ``低檔黃金交叉 +0.5`` when ``K < 20`` and K crossed above D on the latest bar
    (``k_prev ≤ d_prev and k > d``), else ``低檔 +0.3`` when ``K < 20``; ``高檔死亡交叉 −0.5`` /
    ``高檔 −0.3`` mirrored above 80 (*default*); otherwise ``中性 0.0``.  ``k``/``d`` are
    published at 1 dp; the note is formatted from the unrounded values.  ``k_prev``/``d_prev``
    may be ``None`` (no previous bar → no cross).
    """
    k, d = float(k), float(d)
    have_prev = k_prev is not None and d_prev is not None
    golden = have_prev and float(k_prev) <= float(d_prev) and k > d
    death = have_prev and float(k_prev) >= float(d_prev) and k < d
    if k < KD60_LOW:
        label, score = ("低檔黃金交叉", 0.5) if golden else ("低檔", 0.3)
    elif k > KD60_HIGH:
        label, score = ("高檔死亡交叉", -0.5) if death else ("高檔", -0.3)
    else:
        label, score = "中性", 0.0
    return {"score": float(score), "k": _r(k, 1), "d": _r(d, 1), "label": label,
            "note": f"60分K線 K={k:.0f} D={d:.0f}"}


# --------------------------------------------------------------------------------- market

def _regime(closes: list, four_state: bool) -> tuple:
    """``(regime_label, score)`` from the raw daily label of the last bar (spec §4.3, §4.9)."""
    if not closes:
        return "盤整", 0.0
    close = closes[-1]
    ma20 = _mean(closes[-20:]) if len(closes) >= 20 else None
    ma60 = _mean(closes[-60:]) if len(closes) >= 60 else None
    if ma20 is None:
        return "盤整", 0.0
    if ma60 is not None and close > ma20 > ma60 and four_state:
        return "多頭", 1.0
    if ma60 is not None and close < ma20 < ma60 and four_state:
        return "空頭", -1.0
    if close > ma20:
        return "偏多震盪", 0.5
    if close < ma20:
        return "偏空震盪", -0.5
    return "盤整", 0.0


def market_block(twii_bars: list, at: datetime, is_open: bool, index_now: float | None = None,
                 four_state: bool = MARKET_FOUR_STATE) -> dict:
    """``overview.market`` ``{"is_open","label","index","pct","regime_label","score"}`` (spec §4.3, Q-A1).

    ``twii_bars`` are the ``^TWII`` daily bars (oldest first).  ``index`` is the last close, or
    ``index_now`` while open; ``pct = (index − prev_close) / prev_close × 100`` unrounded (this
    operand order reproduces the published ``-2.4941593686153634`` byte-exactly).  With
    ``index_now`` the previous close is the last bar's close unless that bar is dated ``at``'s
    day (then the bar before it).  The regime is the raw daily label of the last bar
    (``close`` vs MA20/MA60 of the closes): ``range`` & ``close > ma20 → 偏多震盪 +0.5``,
    ``range`` & ``close < ma20 → 偏空震盪 −0.5``, ``bull → 多頭 +1.0`` and ``bear → 空頭 −1.0``
    (only with ``four_state``, *default* on), ``close == ma20 → 盤整 0.0``.
    """
    closes = [float(b[4]) for b in (twii_bars or [])]
    label = "盤中" if is_open else "收盤"
    today = at.strftime("%Y-%m-%d") if isinstance(at, datetime) else None
    if index_now is not None and closes:
        index = float(index_now)
        last_date = str(twii_bars[-1][0])
        if today is not None and last_date >= today:
            prev = closes[-2] if len(closes) >= 2 else None
        else:
            prev = closes[-1]
    elif closes:
        index = closes[-1]
        prev = closes[-2] if len(closes) >= 2 else None
    else:
        index, prev = 0.0, None
    pct = (index - prev) / prev * 100 if prev else 0.0
    regime_label, score = _regime(closes, four_state)
    return {"is_open": bool(is_open), "label": label, "index": index, "pct": pct,
            "regime_label": regime_label, "score": float(score)}


def market_returns(twii_bars: list) -> tuple:
    """``(pct_1d, pct_5d)`` of the last ``^TWII`` bar in percent, unrounded (``0.0`` when short)."""
    closes = [float(b[4]) for b in (twii_bars or [])]
    pct1 = (closes[-1] - closes[-2]) / closes[-2] * 100 if len(closes) >= 2 and closes[-2] else 0.0
    pct5 = (closes[-1] - closes[-6]) / closes[-6] * 100 if len(closes) >= 6 and closes[-6] else 0.0
    return pct1, pct5


def market_state(twii_bars: list) -> str:
    """``"halt"`` when 1-day ≤ −2.0 % or 5-day ≤ −3.5 %, else ``"normal"`` (spec §4.3, Q-A2)."""
    pct1, pct5 = market_returns(twii_bars)
    return "halt" if (pct1 <= HALT_1D_PCT or pct5 <= HALT_5D_PCT) else "normal"


# ------------------------------------------------------------------------------ compose

def compose(tech_total: float, mkt_score: float, fund_total: float, news_total: float,
            chips_total: float, kd60_total: float, params: dict) -> tuple:
    """``(total 1 dp, rec_code, rec_text)`` (spec §4.8; inclusive thresholds).

    ``use_market`` / ``use_fundamentals`` false zero the respective component.  Thresholds:
    ``buy_th`` / ``sell_th`` from params, ``strong_th = buy_th + STRONG_GAP`` and
    ``strong_sell_th = sell_th − STRONG_GAP`` unless given explicitly; compared on the 1-dp total.
    """
    if not params.get("use_market", True):
        mkt_score = 0.0
    if not params.get("use_fundamentals", True):
        fund_total = 0.0
    total = _r(float(tech_total) + float(mkt_score) + float(fund_total) + float(news_total)
               + float(chips_total) + float(kd60_total), 1)
    buy_th = float(params.get("buy_th", 3.0))
    sell_th = float(params.get("sell_th", -3.0))
    strong_th = float(params.get("strong_th", buy_th + STRONG_GAP))
    strong_sell_th = float(params.get("strong_sell_th", sell_th - STRONG_GAP))
    if total >= strong_th:
        code = "STRONG_BUY"
    elif total >= buy_th:
        code = "BUY"
    elif total <= strong_sell_th:
        code = "STRONG_SELL"
    elif total <= sell_th:
        code = "SELL"
    else:
        code = "HOLD"
    return total, code, REC_TEXT[code]


# -------------------------------------------------------------------------------- sizing

def suggest_qty(cash: float, price: float, atr14: float, params: dict) -> int:
    """``floor(min(risk_frac×strong_mult×cash/atr14, 0.30×cash/price))`` (spec §4.11).

    Shares (odd lots allowed), ``0`` when ``cash``, ``price`` or ``atr14`` is not positive.
    The published value is the strong-signal size regardless of ``rec_code``; ``risk_frac`` and
    ``strong_mult`` come from ``params["sizing"]`` or the SAFE constants (v9: 0.005 × 1.5 = 0.0075).
    """
    cash, price, atr14 = _num(cash), _num(price), _num(atr14)
    if cash is None or price is None or atr14 is None or cash <= 0 or price <= 0 or atr14 <= 0:
        return 0
    sz = sizing(params)
    q_risk = sz["risk_frac"] * sz["strong_mult"] * cash / atr14
    q_cap = ORDER_CASH_CAP * cash / price
    return max(0, math.floor(min(q_risk, q_cap)))
