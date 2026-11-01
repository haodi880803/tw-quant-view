"""Golden tests for engine/scoring.py against the frozen 2026-10-31 snapshot (spec §4.2–§4.8, §4.11).

Every reproduction claim below is checked byte-for-byte on the serialized objects
(``json.dumps(..., ensure_ascii=False)`` compares key order as well as values).
Where the snapshot does not hold enough history (chips streaks beyond 10 rows, the 60-day
z-score window, the lost news refresh times) the test says so in its name and asserts only
what the data determines.
"""
from __future__ import annotations

import copy
import json
import math
from datetime import datetime, timedelta

import pytest

from engine import scoring, tuner
from tests.conftest import CODES

SNAPSHOT_AT = datetime.fromisoformat("2026-10-31T14:15:22+08:00")

# 2308/2454 published volume notes (2.1 / 1.7) came from a realtime volume at scan time while
# the baked bars were refreshed by the 10-31 EOD (spec §4.2, [04 §3.3.6]).  These are the
# scan-time volumes implied by the published ratios under volume[-1] / mean(volume[-20:]);
# 0050's bar is the same object the scan used and needs no substitution.
SCAN_TIME_VOLUME = {"2308": 23_003_745, "2454": 12_476_069}

# Fundamentals reconstructed from the published labels (yfinance ``Ticker.info`` keys, fractions;
# spec §4.4 thresholds: ROE ≥0.20→0.7 / >0→0.3; revenue ≥0.20→0.7 / >0→0.3 / <0→−0.5;
# earnings >0→0.4 / <0→−0.4; gross margin ≥0.25→0.3; PE >50→−0.3).  A ``None`` field is skipped;
# values that must stay silent (PE ≤ 50, margin < 0.25) are set to show the non-firing branch.
FUNDAMENTALS = {
    "2330": {"returnOnEquity": 0.42, "revenueGrowth": 0.51, "earningsGrowth": 0.69, "grossMargins": 0.51, "trailingPE": 28.0},
    "2317": {"returnOnEquity": 0.13, "revenueGrowth": 0.41, "earningsGrowth": 0.34, "grossMargins": 0.06, "trailingPE": 20.0},
    "2454": {"returnOnEquity": 0.24, "revenueGrowth": 0.01, "earningsGrowth": -0.13, "grossMargins": None, "trailingPE": 65.0},
    "2308": {"returnOnEquity": 0.29, "revenueGrowth": 0.31, "earningsGrowth": 0.26, "grossMargins": None, "trailingPE": None},
    "2882": {"returnOnEquity": 0.25, "revenueGrowth": -0.62, "earningsGrowth": None, "grossMargins": 0.26, "trailingPE": None},
    "0050": {"returnOnEquity": None, "revenueGrowth": None, "earningsGrowth": None, "grossMargins": None, "trailingPE": None},
    "6789": {"returnOnEquity": None, "revenueGrowth": 0.10, "earningsGrowth": 0.68, "grossMargins": None, "trailingPE": 78.0},
    "3481": {"returnOnEquity": None, "revenueGrowth": 0.13, "earningsGrowth": None, "grossMargins": None, "trailingPE": 55.3},
    "2881": {"returnOnEquity": 0.26, "revenueGrowth": -0.25, "earningsGrowth": None, "grossMargins": 0.28, "trailingPE": None},
}

# ^TWII values implied by the snapshot: index 45211.828125, pct -2.4941593686153634 → the
# previous close 46368.328125 (float32-representable, as yfinance's column is).
TWII_INDEX = 45211.828125
TWII_PREV = 46368.328125
TWII_PCT = -2.4941593686153634


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


@pytest.fixture(scope="session")
def v10_params() -> dict:
    return json.loads(tuner.V10_PARAMS_JSON)


@pytest.fixture(scope="session")
def rows(data) -> dict:
    return {r["code"]: r for r in data["overview"]["rows"]}


def atr14_sma(bars: list) -> float:
    """Local SMA-14 of the true range on the published daily bars (spec §4.1 / §4.11)."""
    trs = []
    for i in range(1, len(bars)):
        high, low, prev_close = bars[i][2], bars[i][3], bars[i - 1][4]
        trs.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    return sum(trs[-14:]) / 14


def twii_bars(closes: list) -> list:
    return [[f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}", c, c, c, c, 1000] for i, c in enumerate(closes)]


# ------------------------------------------------------------------ §4.2 technical signals

@pytest.mark.parametrize("code", CODES)
def test_tech_signals_reproduce_snapshot_v9(code, symbols, rows, v9_params):
    sym = symbols[code]
    bars = copy.deepcopy(sym["bars"])
    if code in SCAN_TIME_VOLUME:
        bars[-1][5] = SCAN_TIME_VOLUME[code]
    signals, tech_total = scoring.tech_signals(bars, sym["indicators"], v9_params)
    assert dumps(signals) == dumps(sym["signals"])
    assert tech_total == rows[code]["tech_total"]
    assert all(isinstance(s["score"], float) for s in signals)


@pytest.mark.parametrize("code", ["2308", "2454"])
def test_tech_signals_from_baked_bars_differ_only_in_volume_note(code, symbols, rows, v9_params):
    """With the baked (post-EOD) bars the ratio prints 1.7 / 1.6 instead of 2.1 / 1.7; label,
    score, order and tech_total are unchanged (spec §4.2 default: ratio from the same bar)."""
    sym = symbols[code]
    signals, tech_total = scoring.tech_signals(sym["bars"], sym["indicators"], v9_params)
    assert tech_total == rows[code]["tech_total"]
    for got, exp in zip(signals, sym["signals"]):
        assert (got["indicator"], got["label"], got["score"]) == (exp["indicator"], exp["label"], exp["score"])
        if exp["indicator"] != "成交量":
            assert got["note"] == exp["note"]
    vol = next(s for s in signals if s["indicator"] == "成交量")
    assert vol["note"] == {"2308": "量為均量 1.7 倍,量增價跌", "2454": "量為均量 1.6 倍,量增價跌"}[code]


def test_tech_total_is_sum_of_rounded_items_3481(symbols, v9_params):
    """3481: 0 + 0.75 − 0.5 + 0.5 + 0.62 = 1.37 — per-item rounding (0.625 → 0.62), not 1.375 → 1.38."""
    sym = symbols["3481"]
    signals, tech_total = scoring.tech_signals(sym["bars"], sym["indicators"], v9_params)
    bb = next(s for s in signals if s["indicator"] == "布林通道")
    assert bb["score"] == 0.62
    assert tech_total == 1.37


def _synthetic(close, prev_close, *, ma5, ma20, ma60, ma5_p=None, ma20_p=None, rsi=50.0, hist=1.0,
               k=50.0, d=50.0, k_p=50.0, d_p=50.0, bb_up=200.0, bb_low=1.0, vol_today=100, vol_hist=100):
    bars = [[f"2026-01-{i + 1:02d}", prev_close, prev_close, prev_close, prev_close, vol_hist] for i in range(19)]
    bars[-1][4] = prev_close
    bars.append(["2026-01-20", close, close, close, close, vol_today])
    ind = {
        "ma5": [ma5 if ma5_p is None else ma5_p, ma5], "ma20": [ma20 if ma20_p is None else ma20_p, ma20],
        "ma60": [ma60, ma60], "bb_up": [bb_up, bb_up], "bb_low": [bb_low, bb_low], "rsi": [rsi, rsi],
        "macd": [0.0, 0.0], "macd_sig": [0.0, 0.0], "macd_hist": [hist, hist], "k": [k_p, k], "d": [d_p, d],
    }
    return bars, ind


def test_tech_unobserved_branches_v9(v9_params):
    """Q-A4/Q-A6 default strings and symmetric scores (golden cross, 超買, KD 黃金交叉/高檔, 觸上軌, 帶量上漲)."""
    bars, ind = _synthetic(110.0, 100.0, ma5=101.0, ma20=100.0, ma60=90.0, ma5_p=99.0, ma20_p=100.0,
                           rsi=75.0, hist=0.0, k=25.0, d=20.0, k_p=10.0, d_p=12.0, bb_up=105.0, bb_low=95.0,
                           vol_today=200, vol_hist=100)
    signals, total = scoring.tech_signals(bars, ind, v9_params)
    assert dumps(signals) == dumps([
        {"indicator": "均線排列", "label": "多頭排列", "score": 3.0, "note": "MA5>MA20>MA60,趨勢偏多"},
        {"indicator": "均線交叉", "label": "黃金交叉", "score": 1.0, "note": "MA5 上穿 MA20,短線轉強"},
        {"indicator": "RSI", "label": "超買", "score": -0.75, "note": "RSI=75>70,漲多可能回檔"},
        {"indicator": "MACD", "label": "紅柱", "score": 0.5, "note": "柱狀體在零軸上,動能偏多"},
        {"indicator": "KD", "label": "黃金交叉", "score": 0.75, "note": "K=25 上穿 D=20"},
        {"indicator": "布林通道", "label": "觸上軌", "score": -0.62, "note": "突破上軌,偏強但可能過熱"},
        {"indicator": "成交量", "label": "帶量上漲", "score": 1.5, "note": "量為均量 1.9 倍,量增價漲"},
    ])
    assert total == round(3.0 + 1.0 - 0.75 + 0.5 + 0.75 - 0.62 + 1.5, 2)

    bars, ind = _synthetic(100.0, 100.0, ma5=99.0, ma20=100.0, ma60=110.0, ma5_p=101.0, ma20_p=100.0,
                           k=85.0, d=83.0, k_p=84.0, d_p=82.0, hist=-0.1)
    signals, _ = scoring.tech_signals(bars, ind, v9_params)
    assert [s["label"] for s in signals] == ["空頭排列", "死亡交叉", "中性", "綠柱", "高檔"]
    assert signals[1] == {"indicator": "均線交叉", "label": "死亡交叉", "score": -1.0, "note": "MA5 下穿 MA20,短線轉弱"}
    assert signals[4] == {"indicator": "KD", "label": "高檔", "score": -0.5, "note": "K=85>80,高檔區"}


def test_tech_boundaries_q_a7(v9_params):
    """rsi == 30 → 中性; macd_hist == 0 → 紅柱; k == 20 → no KD item; close == band → no BB item; ratio == 1.5 fires."""
    _, ind = _synthetic(99.0, 100.0, ma5=100.0, ma20=100.0, ma60=100.0, rsi=30.0, hist=0.0,
                        k=20.0, d=25.0, k_p=19.0, d_p=25.0, bb_low=99.0, bb_up=101.0)
    bars = [[f"2026-01-{i + 1:02d}", 100.0, 100.0, 100.0, 100.0, 100] for i in range(19)] + [["2026-01-20", 99.0, 99.0, 99.0, 99.0, 100]]
    # today's volume V with V / ((1900 + V) / 20) == 1.5  →  V = 1.5 × 1900 / 18.5
    bars[-1][5] = 1.5 * 1900 / 18.5
    signals, total = scoring.tech_signals(bars, ind, v9_params)
    assert [s["label"] for s in signals] == ["糾結", "中性", "紅柱", "帶量下跌"]
    assert signals[1]["note"] == "RSI=30"
    assert signals[3]["note"] == "量為均量 1.5 倍,量增價跌"
    assert signals[2]["score"] == 0.5 and total == -1.0


def test_rsi_note_uses_round_not_truncation(v9_params):
    bars, ind = _synthetic(100.0, 100.0, ma5=100.0, ma20=100.0, ma60=100.0, rsi=19.84)
    signals, _ = scoring.tech_signals(bars, ind, v9_params)
    assert signals[1]["note"] == "RSI=20<30,跌深可能反彈"


# --------------------------------------------------------------------- §6.8 v10 numbers

def test_v10_weighted_scores_on_snapshot(symbols, v10_params):
    expected = {
        ("均線排列", "多頭排列"): 3.7, ("均線排列", "空頭排列"): -3.7, ("均線排列", "糾結"): 0.0,
        ("RSI", "超賣"): 1.18, ("RSI", "中性"): 0.0,
        ("MACD", "紅柱"): 0.63, ("MACD", "綠柱"): -0.63,
        ("KD", "死亡交叉"): -0.37, ("KD", "低檔"): 0.24,
        ("布林通道", "觸下軌"): 1.28, ("成交量", "帶量下跌"): -1.45,
    }
    seen = set()
    for code in CODES:
        sym = symbols[code]
        signals, total = scoring.tech_signals(sym["bars"], sym["indicators"], v10_params)
        for s in signals:
            key = (s["indicator"], s["label"])
            assert s["score"] == expected[key], (code, s)
            seen.add(key)
        assert total == round(sum(s["score"] for s in signals), 2)
    assert seen == set(expected)


def test_v10_unobserved_branches(v10_params):
    bars, ind = _synthetic(110.0, 100.0, ma5=101.0, ma20=100.0, ma60=90.0, ma5_p=99.0, ma20_p=100.0,
                           rsi=75.0, hist=0.0, k=25.0, d=20.0, k_p=10.0, d_p=12.0, bb_up=105.0, bb_low=95.0,
                           vol_today=200, vol_hist=100)
    signals, _ = scoring.tech_signals(bars, ind, v10_params)
    assert [s["score"] for s in signals] == [3.7, 0.45, -1.18, 0.63, 0.37, -1.28, 1.45]
    bars, ind = _synthetic(100.0, 100.0, ma5=99.0, ma20=100.0, ma60=110.0, ma5_p=101.0, ma20_p=100.0,
                           k=85.0, d=83.0, k_p=84.0, d_p=82.0, hist=-0.1)
    signals, _ = scoring.tech_signals(bars, ind, v10_params)
    assert [s["score"] for s in signals] == [-3.7, -0.45, 0.0, -0.63, -0.24]


def test_v10_sizing_constant(v10_params):
    sz = scoring.sizing(v10_params)
    assert sz["risk_frac"] * sz["strong_mult"] == 0.011937295357720796
    assert sz["caution_scale"] == 0.5500015169427086
    assert scoring.sizing({"buy_th": 3.0}) == {"risk_frac": 0.005, "strong_mult": 1.5, "caution_scale": 0.5, "persistence": 2.0}
    assert 0.005 * 1.5 == 0.0075


# --------------------------------------------------------------------- §4.4 fundamentals

@pytest.mark.parametrize("code", CODES)
def test_fund_signals_reproduce_snapshot(code, symbols, rows, v9_params):
    items, total = scoring.fund_signals(FUNDAMENTALS[code], v9_params)
    assert dumps(items) == dumps(symbols[code]["fund_signals"])
    assert total == rows[code]["fund_total"]


def test_fund_total_cap_and_rounding(v9_params):
    _, total = scoring.fund_signals(FUNDAMENTALS["2330"], v9_params)
    assert total == 1.5                      # Σ 2.1 capped
    _, total = scoring.fund_signals(FUNDAMENTALS["2317"], v9_params)
    assert total == 1.4                      # Σ 1.4000000000000001 rounded
    items, total = scoring.fund_signals(None, v9_params)
    assert items == [{"indicator": "基本面", "label": "中性", "score": 0.0, "note": "基本面無明顯偏多或偏空訊號"}]
    assert total == 0.0
    off = dict(v9_params, use_fundamentals=False)
    assert scoring.fund_signals(FUNDAMENTALS["2330"], off) == ([], 0.0)
    # zero growth fires nothing; negative ROE fires nothing; PE exactly 50 silent
    items, _ = scoring.fund_signals({"returnOnEquity": -0.1, "revenueGrowth": 0.0, "earningsGrowth": 0.0,
                                     "grossMargins": 0.249, "trailingPE": 50.0}, v9_params)
    assert items[0]["indicator"] == "基本面"
    _, total = scoring.fund_signals({"revenueGrowth": -0.3, "earningsGrowth": -0.2, "trailingPE": 99.0}, v9_params)
    assert total == -1.2


# ---------------------------------------------------------------------------- §4.5 news

def test_lexicon_score_headlines():
    assert scoring.lexicon_score("台達電法說後慘吞跌停！台股重挫雪上加霜毛利率、庫存成隱憂| 財經") == -3
    assert scoring.lexicon_score("面板雙虎慘跌！友達法說失靈觸跌停 群創也重挫逾9% 分析師：中長期買點浮現") == -3
    assert scoring.lexicon_score("金控9月獲利即將公布 富邦金一度觸及160元 再創新高") == 2
    assert scoring.lexicon_score("矽光子紅燈連發！「這檔」連2漲13%挾穩懋、全新、IET漲停 旺矽、日月光、上詮都攻6%") == 2
    assert scoring.lexicon_score("鴻海科技日發表 Model A+與 K+等三款電動車") == 0
    assert scoring.lexicon_score("台達電跌停能抄底？ 大和、花旗齊砍目標價卻喊買") == -3
    assert scoring.lexicon_score("存貨跳增至1535億新旗艦平台量產助攻 聯發科Q3單季大賺17.5元") == 1
    assert scoring.lexicon_score("法人看好利多 創新高 漲停") == 3
    assert scoring.lexicon_score("") == 0
    assert scoring.sentiment(2) == "pos" and scoring.sentiment(-1) == "neg" and scoring.sentiment(0.0) == "neu"


@pytest.mark.parametrize("code", CODES)
def test_news_block_items_shape_reproduces(code, symbols):
    """Items keep feed order and the exact key order/sentiment/float score (9/9)."""
    block = scoring.news_block(symbols[code]["news"]["items"], SNAPSHOT_AT)
    assert dumps(block["items"]) == dumps(symbols[code]["news"]["items"])
    assert list(block.keys()) == ["score", "items"]


NEWS_SCORE_REPRODUCED = {"2317", "3481"}


@pytest.mark.parametrize("code", CODES)
def test_news_score_default_formula_q_a12(code, symbols, rows):
    """Q-A12 default (Σ 0.5^(age_h/24)·s_i / 6, clipped ±3) at the snapshot time reproduces
    2317 (0.0) and 3481 (−1.07); the other seven keep the sign but not the value (the refresh
    times are lost and the original aggregate was never fully determined — spec §4.5)."""
    block = scoring.news_block(symbols[code]["news"]["items"], SNAPSHOT_AT)
    published = symbols[code]["news"]["score"]
    assert published == rows[code]["news_total"]
    if code in NEWS_SCORE_REPRODUCED:
        assert block["score"] == published
    else:
        assert block["score"] != published
        assert math.copysign(1, block["score"]) == math.copysign(1, published)
        assert abs(block["score"]) <= abs(published)


def test_news_block_edge_cases():
    assert scoring.news_block([], SNAPSHOT_AT) == {"score": 0.0, "items": []}
    assert scoring.news_block(None, SNAPSHOT_AT) == {"score": 0.0, "items": []}
    fresh = {"title": "t", "link": "https://x", "source": "s", "published": "2026-10-31T14:15:22+08:00", "score": 3}
    day_old = dict(fresh, published="2026-10-30T14:15:22+08:00")
    block = scoring.news_block([fresh, day_old], SNAPSHOT_AT)
    assert block["score"] == round((3 + 1.5) / 6, 2)
    assert block["items"][0]["score"] == 3.0 and block["items"][0]["sentiment"] == "pos"
    # clip ±3 and cap at 8 items in feed order
    many = [dict(fresh, title=str(i)) for i in range(12)]
    block = scoring.news_block(many, SNAPSHOT_AT)
    assert len(block["items"]) == 8 and [it["title"] for it in block["items"]] == [str(i) for i in range(8)]
    assert block["score"] == 3.0
    # future-dated item has weight 1; unparsable date → weight 1; naive `at` is Taipei
    block = scoring.news_block([dict(fresh, published="2026-11-01T09:00:00+08:00", score=-2),
                                dict(fresh, published="n/a", score=-1)], SNAPSHOT_AT.replace(tzinfo=None))
    assert block["score"] == -0.5
    assert math.copysign(1, scoring.news_block([dict(fresh, score=0)], SNAPSHOT_AT)["score"]) == 1


# ---------------------------------------------------------------------------- §4.6 chips

def _hist_from_recent(recent: list, prefix: list | None = None) -> list:
    rows_asc = [(r["date"], {k: r[k] for k in ("foreign", "invtrust", "dealer", "total")}) for r in reversed(recent)]
    return (prefix or []) + rows_asc


def _streak_prefix(recent: list) -> list:
    """One buying day, then 6 foreign-selling days with dispersed totals (±max |total| of the
    published window), so the 16-day streak forms while the 3-day-sum z stays inside (−1, 1)."""
    scale = max(abs(r["total"]) for r in recent)
    pre = [("2026-09-01", {"foreign": 5_000_000, "invtrust": 100_000, "dealer": 0, "total": 5_100_000})]
    for i in range(6):
        t = scale if i % 2 else -scale
        f, iv = -3_000_000, 500_000
        pre.append((f"2026-09-{10 + i:02d}", {"foreign": f, "invtrust": iv, "dealer": t - f - iv, "total": t}))
    return pre


def _prefix(n: int, foreign: int, invtrust: int, dealer: int, start: str = "2026-09-01") -> list:
    """``n`` synthetic trading days before the published window (all identical)."""
    base = datetime.fromisoformat(start)
    out = []
    for i in range(n):
        d = base + timedelta(days=i)
        out.append((d.strftime("%Y-%m-%d"), {"foreign": foreign, "invtrust": invtrust, "dealer": dealer,
                                              "total": foreign + invtrust + dealer}))
    return out


@pytest.mark.parametrize("code", CODES)
def test_chips_recent_and_invtrust_reproduce(code, symbols, rows):
    """recent[] (10 newest first, ints) and 投信動向 are fully determined by the 10 published rows (9/9)."""
    sym = symbols[code]
    block = scoring.chips_block(_hist_from_recent(sym["chips"]["recent"]))
    assert dumps(block["recent"]) == dumps(sym["chips"]["recent"])
    assert list(block.keys()) == ["score", "signals", "recent"]
    got = [s for s in block["signals"] if s["indicator"] == "投信動向"]
    exp = [s for s in sym["chips"]["signals"] if s["indicator"] == "投信動向"]
    assert dumps(got) == dumps(exp)
    assert sym["chips"]["score"] == rows[code]["chips_total"]


@pytest.mark.parametrize("code", ["2317", "2882", "2881", "2308"])
def test_chips_block_reproduces_from_10_rows(code, symbols):
    """Symbols whose published block is determined by the 10 rows: no streak ≥ 3, and the
    法人動能 z of 2308 (−2.06, population std over the rolling 3-day sums) reproduces byte-exactly."""
    sym = symbols[code]
    block = scoring.chips_block(_hist_from_recent(sym["chips"]["recent"]))
    assert dumps(block) == dumps(sym["chips"])


@pytest.mark.parametrize("code", ["2330", "2454"])
def test_chips_foreign_streak_16_needs_older_history(code, symbols):
    """外資連賣16日 needs 6 selling days before the published window; with them (and a buying
    day to end the streak) the whole block reproduces; the 10 rows alone give 外資連賣10日."""
    sym = symbols[code]
    short = scoring.chips_block(_hist_from_recent(sym["chips"]["recent"]))
    assert short["signals"][0]["label"] == "外資連賣10日" and short["signals"][0]["score"] == -1.5
    full = scoring.chips_block(_hist_from_recent(sym["chips"]["recent"], _streak_prefix(sym["chips"]["recent"])))
    assert dumps(full) == dumps(sym["chips"])


def test_chips_0050_streak_and_invtrust_reproduce_z_needs_60_days(symbols):
    """0050: 外資連賣16日 and 投信買超 reproduce with the extended history; its 法人賣壓動能
    (z −1.08) is measured against 60 trading days that the snapshot does not hold (10 rows give +0.08)."""
    sym = symbols["0050"]
    block = scoring.chips_block(_hist_from_recent(sym["chips"]["recent"], _streak_prefix(sym["chips"]["recent"])))
    assert dumps(block["signals"]) == dumps(sym["chips"]["signals"][:2])
    assert block["score"] == -1.0 and sym["chips"]["score"] == -1.5
    assert sym["chips"]["signals"][2]["note"] == "近 3 日三大法人合計 z 分數 -1.08(相對近 60 日)"
    z10 = scoring.chips_zscore([r["total"] for r in reversed(sym["chips"]["recent"])])
    assert round(z10, 2) == 0.08


def test_chips_z_limits_of_10_rows(symbols):
    """6789 fires 法人賣壓動能 from 10 rows (z −1.26 vs published −1.02); 3481's 10-row z (−1.12)
    fires while the published 60-day window did not — both need the longer history."""
    b = scoring.chips_block(_hist_from_recent(symbols["6789"]["chips"]["recent"]))
    assert [(s["label"], s["score"]) for s in b["signals"]] == [("法人賣壓動能", -0.5)]
    assert b["signals"][0]["note"] == "近 3 日三大法人合計 z 分數 -1.26(相對近 60 日)"
    assert symbols["6789"]["chips"]["signals"][0]["note"] == "近 3 日三大法人合計 z 分數 -1.02(相對近 60 日)"
    b = scoring.chips_block(_hist_from_recent(symbols["3481"]["chips"]["recent"]))
    assert [s["label"] for s in b["signals"]] == ["法人賣壓動能"] and symbols["3481"]["chips"]["signals"] == []


def test_chips_rules_synthetic():
    assert scoring.chips_block([]) == {"score": 0.0, "signals": [], "recent": []}
    # 3-day buy streak → ±1.0 tier; 5-day sell streak with a 0 day breaking it
    hist = _prefix(4, -10, 5, 1) + _prefix(3, 10, 5, 1, "2026-09-10")
    b = scoring.chips_block(hist)
    assert b["signals"][0] == {"indicator": "外資動向", "label": "外資連買3日", "score": 1.0, "note": "外資連續 3 個交易日買超"}
    assert b["signals"][1]["label"] == "投信買超" and b["score"] == 1.5
    hist = _prefix(4, -10, -5, 1) + _prefix(1, 0, -5, 1, "2026-09-10")
    b = scoring.chips_block(hist)
    assert [s["label"] for s in b["signals"]] == ["投信賣超"] and b["score"] == -0.5
    hist = _prefix(2, -10, 0, 1) + _prefix(5, -10, 5, 1, "2026-09-10")
    b = scoring.chips_block(hist)
    assert b["signals"][0]["label"] == "外資連賣7日" and b["signals"][0]["score"] == -1.5
    assert [s["indicator"] for s in b["signals"]] == ["外資動向", "投信動向"]
    # cap at ±1.5 (1.5 + 0.5 + 0.5 → 1.5) and z-score buy side
    hist = _prefix(20, 1, 1, 1) + _prefix(5, 100, 100, 100, "2026-09-25")
    b = scoring.chips_block(hist)
    labels = [s["label"] for s in b["signals"]]
    assert labels == ["外資連買25日", "投信買超", "法人買盤動能"] and b["score"] == 1.5
    assert b["signals"][2]["note"].startswith("近 3 日三大法人合計 z 分數 +") and b["signals"][2]["note"].endswith("(相對近 60 日)")
    assert len(b["recent"]) == 10 and b["recent"][0]["date"] > b["recent"][-1]["date"]
    # fewer than CHIPS_Z_MIN_DAYS → no z; constant history → std 0 → no z
    assert scoring.chips_zscore([1, 2, 3, 4, 5]) is None
    assert scoring.chips_zscore([7] * 30) is None
    # total recomputed when missing
    b = scoring.chips_block([("2026-10-30", {"foreign": 1, "invtrust": 2, "dealer": 3})])
    assert b["recent"] == [{"date": "2026-10-30", "foreign": 1, "invtrust": 2, "dealer": 3, "total": 6}]


# ------------------------------------------------------------------------- §4.7 60-min KD

@pytest.mark.parametrize("code", CODES)
def test_kd60_block_reproduces_snapshot(code, symbols, rows):
    """Published k/d fed back (2881's raw d 47.46 → published 47.5 / note 47; 3481 with a fresh
    golden cross) reproduce label/score/note and the rows[].kd60 split (9/9)."""
    kd = symbols[code]["intraday_kd"]
    k_prev, d_prev = (14.0, 15.0) if code == "3481" else (kd["k"], kd["d"])
    d_raw = 47.46 if code == "2881" else kd["d"]
    block = scoring.kd60_block(kd["k"], d_raw, k_prev, d_prev)
    assert dumps(block) == dumps(kd)
    assert {k: v for k, v in block.items() if k != "score"} == rows[code]["kd60"]
    assert block["score"] == rows[code]["kd60_total"]


def test_kd60_unobserved_branches():
    assert scoring.kd60_block(85.2, 83.9, 84.0, 82.0) == {"score": -0.3, "k": 85.2, "d": 83.9, "label": "高檔", "note": "60分K線 K=85 D=84"}
    assert scoring.kd60_block(81.0, 83.0, 85.0, 84.0) == {"score": -0.5, "k": 81.0, "d": 83.0, "label": "高檔死亡交叉", "note": "60分K線 K=81 D=83"}
    assert scoring.kd60_block(55.0, 50.0, 45.0, 50.0)["label"] == "中性"          # mid-range cross carries nothing
    assert scoring.kd60_block(15.0, 18.0, 19.0, 18.0) == {"score": 0.3, "k": 15.0, "d": 18.0, "label": "低檔", "note": "60分K線 K=15 D=18"}
    assert scoring.kd60_block(16.0, 15.3, None, None)["label"] == "低檔"
    assert scoring.kd60_block(20.0, 10.0, 9.0, 10.0)["label"] == "中性"            # k == 20 is not 低檔
    assert scoring.kd60_block(20.46, 27.14, 20.0, 27.0)["note"] == "60分K線 K=20 D=27"


# --------------------------------------------------------------------- §4.3 market block

def test_market_block_reproduces_snapshot(data):
    """range & close < ma20 → 偏空震盪 −0.5; index/pct byte-exact from the implied previous close."""
    closes = [44000.0] * 40 + [47000.0] * 28 + [TWII_PREV, TWII_INDEX]
    at = datetime.fromisoformat("2026-10-31T14:15:22+08:00")
    block = scoring.market_block(twii_bars(closes), at, False)
    assert dumps(block) == dumps(data["overview"]["market"])
    assert block["pct"] == TWII_PCT
    assert all(r["mkt_score"] == block["score"] for r in data["overview"]["rows"])


def test_market_block_aug_observation_and_four_state_switch():
    at = datetime.fromisoformat("2026-08-15T14:15:32+08:00")
    # Aug: close > ma20, ma20 < ma60 → range → 偏多震盪 +0.5
    closes = [50000.0] * 40 + [44000.0] * 28 + [45000.0, 46000.0]
    block = scoring.market_block(twii_bars(closes), at, False)
    assert (block["regime_label"], block["score"], block["label"]) == ("偏多震盪", 0.5, "收盤")
    # bull / bear (*default* four-state) and the switch that collapses them to ±0.5
    bull = [40000.0] * 40 + [45000.0] * 18 + [47000.0, 48000.0]
    bear = [50000.0] * 40 + [45000.0] * 18 + [43000.0, 42000.0]
    assert scoring.market_block(twii_bars(bull), at, False)["regime_label"] == "多頭"
    assert scoring.market_block(twii_bars(bull), at, False)["score"] == 1.0
    assert scoring.market_block(twii_bars(bear), at, False)["score"] == -1.0
    assert scoring.market_block(twii_bars(bear), at, False)["regime_label"] == "空頭"
    assert scoring.market_block(twii_bars(bull), at, False, four_state=False)["regime_label"] == "偏多震盪"
    assert scoring.market_block(twii_bars(bear), at, False, four_state=False)["score"] == -0.5
    flat = [45000.0] * 60
    assert scoring.market_block(twii_bars(flat), at, False)["regime_label"] == "盤整"
    # intraday: index_now, previous close = last completed bar; label 盤中
    live = scoring.market_block(twii_bars(closes), datetime.fromisoformat("2026-08-17T10:00:00+08:00"), True, index_now=46460.0)
    assert live["is_open"] is True and live["label"] == "盤中" and live["index"] == 46460.0
    assert live["pct"] == (46460.0 - 46000.0) / 46000.0 * 100
    # intraday with today's partial bar already appended → previous close is the bar before it
    bars = twii_bars(closes)
    bars[-1][0] = "2026-08-17"
    live = scoring.market_block(bars, datetime.fromisoformat("2026-08-17T10:00:00+08:00"), True, index_now=46460.0)
    assert live["pct"] == (46460.0 - 45000.0) / 45000.0 * 100
    assert list(live.keys()) == ["is_open", "label", "index", "pct", "regime_label", "score"]
    assert scoring.market_block([], at, False)["index"] == 0.0


def test_market_state_q_a2():
    closes = [50000.0] * 10 + [TWII_PREV, TWII_INDEX]
    closes[-6] = TWII_INDEX / (1 - 0.036)
    pct1, pct5 = scoring.market_returns(twii_bars(closes))
    assert f"市場狀態:halt(大盤單日 {pct1:+.1f}%、5日 {pct5:+.1f}%)" == "市場狀態:halt(大盤單日 -2.5%、5日 -3.6%)"
    assert scoring.market_state(twii_bars(closes)) == "halt"
    assert scoring.market_state(twii_bars([100.0] * 5 + [98.1])) == "normal"          # −1.9 %
    assert scoring.market_state(twii_bars([100.0] * 5 + [98.0])) == "halt"            # −2.0 % inclusive
    assert scoring.market_state(twii_bars([100.0, 99.0, 98.5, 98.0, 97.5, 96.5])) == "halt"   # 5-day −3.5 %
    assert scoring.market_state(twii_bars([100.0, 99.0, 98.5, 98.0, 97.5, 96.6])) == "normal"
    assert scoring.market_state(twii_bars([100.0])) == "normal"


# --------------------------------------------------------------------------- §4.8 compose

@pytest.mark.parametrize("code", CODES)
def test_compose_reproduces_snapshot(code, rows, v9_params):
    r = rows[code]
    total, code_, text = scoring.compose(r["tech_total"], r["mkt_score"], r["fund_total"], r["news_total"],
                                         r["chips_total"], r["kd60_total"], v9_params)
    assert (total, code_, text) == (r["total"], r["rec_code"], r["rec_text"])


def test_compose_thresholds_inclusive(v9_params):
    p = v9_params
    assert scoring.compose(3.0, 0, 0, 0, 0, 0, p) == (3.0, "BUY", "買進")
    assert scoring.compose(5.0, 0, 0, 0, 0, 0, p) == (5.0, "STRONG_BUY", "強力買進")
    assert scoring.compose(4.9, 0, 0, 0, 0, 0, p)[1] == "BUY"
    assert scoring.compose(2.9, 0, 0, 0, 0, 0, p) == (2.9, "HOLD", "觀望")
    assert scoring.compose(-3.0, 0, 0, 0, 0, 0, p) == (-3.0, "SELL", "賣出")
    assert scoring.compose(-3.1, 0, 0, 0, 0, 0, p)[1] == "SELL"
    assert scoring.compose(-2.8, 0, 0, 0, 0, 0, p)[1] == "HOLD"
    assert scoring.compose(-5.0, 0, 0, 0, 0, 0, p) == (-5.0, "STRONG_SELL", "強力賣出")
    assert scoring.compose(-4.9, 0, 0, 0, 0, 0, p)[1] == "SELL"
    # rounding on the float sum (spec [05 §0]) and never −0.0
    assert scoring.compose(0.25, -0.5, 1.5, 0.5, -1.0, 0.0, p)[0] == 0.8
    assert scoring.compose(-1.25, -0.5, 0.3, -0.33, -1.0, 0.0, p)[0] == -2.8
    total = scoring.compose(-0.04, 0, 0, 0, 0, 0, p)[0]
    assert total == 0.0 and math.copysign(1, total) == 1
    # feature flags zero the component; strong thresholds derive from the gap when absent
    assert scoring.compose(3.0, -0.5, 0, 0, 0, 0, dict(p, use_market=False))[1] == "BUY"
    assert scoring.compose(3.0, 0, -1.0, 0, 0, 0, dict(p, use_fundamentals=False))[1] == "BUY"
    assert scoring.compose(5.0, 0, 0, 0, 0, 0, {"buy_th": 3.0, "sell_th": -3.0})[1] == "STRONG_BUY"
    assert scoring.STRONG_GAP == 2.0 and scoring.REC_TEXT["HOLD"] == "觀望"


# ---------------------------------------------------------------------- §4.11 suggest_qty

@pytest.mark.parametrize("code", CODES)
def test_suggest_qty_reproduces_snapshot(code, symbols, rows, data, v9_params):
    cash = data["overview"]["account"]["cash"]
    atr = atr14_sma(symbols[code]["bars"])
    assert scoring.suggest_qty(cash, rows[code]["price"], atr, v9_params) == rows[code]["suggest_qty"]


def test_suggest_qty_binding_sides_and_edges(symbols, rows, data, v9_params, v10_params):
    cash = data["overview"]["account"]["cash"]
    # cap binds for 2330/2317/0050, risk for the others (spec [05 §8.2])
    for code, side in {"2330": "cap", "2317": "cap", "0050": "cap", "2454": "risk", "3481": "risk"}.items():
        atr = atr14_sma(symbols[code]["bars"])
        q_risk = 0.0075 * cash / atr
        q_cap = 0.30 * cash / rows[code]["price"]
        assert (q_cap < q_risk) == (side == "cap")
    assert scoring.suggest_qty(0.0, 100.0, 2.0, v9_params) == 0
    assert scoring.suggest_qty(1000.0, 100.0, 0.0, v9_params) == 0
    assert scoring.suggest_qty(1000.0, 0.0, 2.0, v9_params) == 0
    assert scoring.suggest_qty(100.0, 1000.0, 1.0, v9_params) == 0      # floor → 0 shares
    assert scoring.suggest_qty(1_000_000.0, 100.0, 10.0, v9_params) == 750
    assert scoring.suggest_qty(1_000_000.0, 100.0, 10.0, v10_params) == math.floor(0.011937295357720796 * 1_000_000 / 10)
    assert isinstance(scoring.suggest_qty(cash, 100.0, 1.0, v9_params), int)
