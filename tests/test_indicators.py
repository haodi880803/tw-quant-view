"""Golden tests for ``engine.indicators`` against the frozen 2026-10-31 snapshot (spec §4.1,
§4.7, §4.9–§4.11; appendices 04 §1–§2 and 02 §9).

Every reproduction claim of the spec that can be checked from the published 250-bar
window is checked here on all 9 symbol files.  Claims that need history before the
window (MACD / KD seeds) are checked the way appendix 04 §2.4–§2.5 describes: the
recursions must hold on the published arrays, and once the pre-window EMA states are
back-solved, ``compute`` itself must reproduce the published MACD trio.
"""
from __future__ import annotations

import json
import math
import statistics

import numpy as np
import pytest

from engine import indicators as I
from tests.conftest import CODES

# atr14 values of spec appendix 05 §8.2 (4 dp), Oct snapshot
ATR_TABLE = {"2330": 39.2857, "2317": 6.0357, "2454": 197.1429, "2308": 86.4286, "2882": 3.3929,
             "0050": 2.0679, "6789": 21.9643, "3481": 2.3107, "2881": 4.6429}


def _max_err(a, b) -> float:
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    assert a.shape == b.shape
    return float(np.max(np.abs(a - b))) if a.size else 0.0


def _synthetic_bars(n: int, seed: int = 7, start: float = 100.0) -> list:
    """Deterministic random-walk daily bars ``[date, o, h, l, c, v]``."""
    rng = np.random.default_rng(seed)
    bars = []
    c = start
    for i in range(n):
        o = c
        c = max(1.0, c * (1.0 + rng.normal(0.0, 0.015)))
        h = max(o, c) * (1.0 + abs(rng.normal(0.0, 0.004)))
        l = min(o, c) * (1.0 - abs(rng.normal(0.0, 0.004)))
        bars.append([f"2025-{(i // 28) % 12 + 1:02d}-{i % 28 + 1:02d}", o, h, l, c, int(rng.integers(1000, 100000))])
    return bars


# --------------------------------------------------------------------------- shape

@pytest.mark.parametrize("code", CODES)
def test_compute_shape_and_key_order(symbols, code):
    bars = symbols[code]["bars"]
    ind = I.compute(bars)
    assert tuple(ind.keys()) == I.INDICATOR_KEYS
    assert tuple(symbols[code]["indicators"].keys()) == I.INDICATOR_KEYS
    for key in I.INDICATOR_KEYS:
        assert len(ind[key]) == len(bars)
        assert all(isinstance(v, float) for v in ind[key])


def test_compute_empty():
    assert I.compute([]) == {k: [] for k in I.INDICATOR_KEYS}
    bars, ind = I.published([], I.compute([]))
    assert bars == [] and ind == {k: [] for k in I.INDICATOR_KEYS}


# --------------------------------------------------------------------------- MA / BB / RSI (spec §4.1, 04 §2.1–§2.3)

@pytest.mark.parametrize("code", CODES)
def test_moving_averages_exact(symbols, code):
    bars, pub = symbols[code]["bars"], symbols[code]["indicators"]
    ind = I.compute(bars)
    for n in (5, 20, 60):
        key = f"ma{n}"
        assert _max_err(ind[key][n - 1:], pub[key][n - 1:]) == 0.0, key          # byte-exact, 04 §2.1
        assert _max_err(ind[key][59:], pub[key][59:]) <= 1e-9
        assert all(math.isnan(v) for v in ind[key][: n - 1])                     # min_periods = n


@pytest.mark.parametrize("code", CODES)
def test_bollinger_bands(symbols, code):
    bars, pub = symbols[code]["bars"], symbols[code]["indicators"]
    ind = I.compute(bars)
    assert _max_err(ind["bb_up"][19:], pub["bb_up"][19:]) <= 1e-9
    assert _max_err(ind["bb_low"][19:], pub["bb_low"][19:]) <= 1e-9
    # mid-line is ma20 (spec §4.1 edge fact) and the multiplier is 2.0 × sample std
    mid = (np.array(pub["bb_up"]) + np.array(pub["bb_low"])) / 2.0
    assert _max_err(mid, pub["ma20"]) <= 1e-9
    closes = [b[4] for b in bars]
    for i in (19, 100, 249):
        sd = statistics.stdev(closes[i - 19: i + 1])
        assert abs(pub["bb_up"][i] - (pub["ma20"][i] + 2.0 * sd)) <= 1e-9


@pytest.mark.parametrize("code", CODES)
def test_bollinger_rejects_population_std(symbols, code):
    bars, pub = symbols[code]["bars"], symbols[code]["indicators"]
    closes = [b[4] for b in bars]
    i = 249
    sd0 = statistics.pstdev(closes[i - 19: i + 1])
    assert abs(pub["bb_up"][i] - (pub["ma20"][i] + 2.0 * sd0)) > 1e-3


@pytest.mark.parametrize("code", CODES)
def test_rsi_cutler_exact(symbols, code):
    bars, pub = symbols[code]["bars"], symbols[code]["indicators"]
    ind = I.compute(bars)
    assert _max_err(ind["rsi"][14:], pub["rsi"][14:]) <= 1e-9
    assert _max_err(ind["rsi"][14:], pub["rsi"][14:]) == 0.0                      # byte-exact, 04 §2.3
    assert all(math.isnan(v) for v in ind["rsi"][:14])


def test_rsi_degenerate_guards():
    up = [[f"d{i}", 10 + i, 10 + i, 10 + i, 10.0 + i, 1] for i in range(40)]
    down = [[f"d{i}", 100 - i, 100 - i, 100 - i, 100.0 - i, 1] for i in range(40)]
    flat = [[f"d{i}", 50, 50, 50, 50.0, 1] for i in range(40)]
    assert I.compute(up)["rsi"][14:] == [100.0] * 26
    assert I.compute(down)["rsi"][14:] == [0.0] * 26
    assert I.compute(flat)["rsi"][14:] == [50.0] * 26


def test_rsi_fifty_is_genuine(symbols):
    """rsi == 50.0 exactly when mean gain == mean loss (2454 rsi[0] in the snapshot)."""
    bars = symbols["2454"]["bars"]
    assert symbols["2454"]["indicators"]["rsi"][0] == 50.0
    closes = [b[4] for b in bars]
    # bars[0] of the window depends on closes before the window; check the property
    # on every bar whose whole 14-day window is available, across all 9 files
    hits = 0
    for code in CODES:
        closes = [b[4] for b in symbols[code]["bars"]]
        pub = symbols[code]["indicators"]["rsi"]
        for i in range(14, 250):
            d = [closes[j] - closes[j - 1] for j in range(i - 13, i + 1)]
            g = sum(x for x in d if x > 0) / 14
            l = sum(-x for x in d if x < 0) / 14
            if pub[i] == 50.0:
                assert g == l
                hits += 1
    assert hits >= 1


# --------------------------------------------------------------------------- MACD (spec §4.1, 04 §2.4)

MACD_A, MACD_B, MACD_G = 2 / 13, 2 / 27, 0.2


def _partial_ema(x, alpha):
    """Window-only EMA started from state 0 (so full EMA = seed·(1−α)^(i+1) + partial)."""
    e = 0.0
    out = []
    for v in x:
        e = (1 - alpha) * e + alpha * v
        out.append(e)
    return np.array(out)


def _backsolve_states(bars, pub):
    """Least-squares pre-window EMA12/EMA26/signal states (appendix 04 §2.4)."""
    c = np.array([b[4] for b in bars], dtype=float)
    m = np.array(pub["macd"], dtype=float)
    s = np.array(pub["macd_sig"], dtype=float)
    i = np.arange(len(c))
    A = np.column_stack([(1 - MACD_A) ** (i + 1), -((1 - MACD_B) ** (i + 1))])
    rhs = m - (_partial_ema(c, MACD_A) - _partial_ema(c, MACD_B))
    (s12, s26), *_ = np.linalg.lstsq(A, rhs, rcond=None)
    resid_macd = float(np.max(np.abs(A @ np.array([s12, s26]) - rhs)))
    col = ((1 - MACD_G) ** (i + 1))[:, None]
    rhs9 = s - _partial_ema(m, MACD_G)
    s9 = float(np.linalg.lstsq(col, rhs9, rcond=None)[0][0])
    resid_sig = float(np.max(np.abs(col[:, 0] * s9 - rhs9)))
    return float(s12), float(s26), s9, resid_macd, resid_sig


@pytest.mark.parametrize("code", CODES)
def test_macd_signal_recursion_on_published(symbols, code):
    pub = symbols[code]["indicators"]
    m = np.array(pub["macd"])
    s = np.array(pub["macd_sig"])
    h = np.array(pub["macd_hist"])
    assert float(np.max(np.abs(s[1:] - (s[:-1] * 8 / 10 + m[1:] * 2 / 10)))) <= 1e-9
    assert _max_err(h, m - s) == 0.0                                              # plain difference, not ×2
    assert float(np.max(np.abs(h - 2 * (m - s)))) > 1e-3


@pytest.mark.parametrize("code", CODES)
def test_macd_ema_recursions_hold_with_backsolved_seeds(symbols, code):
    bars, pub = symbols[code]["bars"], symbols[code]["indicators"]
    s12, s26, s9, resid_macd, resid_sig = _backsolve_states(bars, pub)
    assert resid_macd <= 1e-9
    assert resid_sig <= 1e-9
    close0 = bars[0][4]
    assert 0.5 * close0 < s12 < 2.0 * close0 and 0.5 * close0 < s26 < 2.0 * close0   # plausible prices


@pytest.mark.parametrize("code", CODES)
def test_compute_reproduces_macd_given_prewindow_state(symbols, code):
    """Three synthetic pre-window bars put the module's EMA12/EMA26/signal states exactly
    at the back-solved values; ``compute`` must then reproduce the published trio."""
    bars, pub = symbols[code]["bars"], symbols[code]["indicators"]
    s12, s26, s9, _, _ = _backsolve_states(bars, pub)
    a, b, g = MACD_A, MACD_B, MACD_G
    M = np.array([
        [(1 - a) ** 2, a * (1 - a), a],
        [(1 - b) ** 2, b * (1 - b), b],
        [(1 - g) * g * (b - a) + g * ((1 - a) ** 2 - (1 - b) ** 2),
         (1 - g) * g * (a - b) + g * (a * (1 - a) - b * (1 - b)),
         g * (a - b)],
    ])
    x = np.linalg.solve(M, np.array([s12, s26, s9]))
    pre = [[f"pre{j}", float(v), float(v), float(v), float(v), 0] for j, v in enumerate(x)]
    ind = I.compute(pre + bars)
    for key in ("macd", "macd_sig", "macd_hist"):
        assert _max_err(ind[key][-250:], pub[key]) <= 1e-9, key


@pytest.mark.parametrize("code", CODES)
def test_macd_window_only_transient_decays(symbols, code):
    """Without pre-window history the error is a pure (25/27)^i transient (04 §2.4)."""
    bars, pub = symbols[code]["bars"], symbols[code]["indicators"]
    ind = I.compute(bars)
    err = np.abs(np.array(ind["macd"]) - np.array(pub["macd"]))
    assert err[249] <= 1e-5
    assert err[249] < err[200] < err[100] < err[0]


# --------------------------------------------------------------------------- KD (spec §4.1, 04 §2.5)

@pytest.mark.parametrize("code", CODES)
def test_kd_converges_after_warmup(symbols, code):
    bars, pub = symbols[code]["bars"], symbols[code]["indicators"]
    ind = I.compute(bars)                              # seed = first rsv (pandas ewm)
    assert _max_err(ind["k"][70:], pub["k"][70:]) <= 1e-6
    assert _max_err(ind["d"][70:], pub["d"][70:]) <= 1e-6
    k50, d50 = I.kd(bars, seed=50.0)                   # 50/50 convention converges too
    assert _max_err(k50[70:], pub["k"][70:]) <= 1e-6
    assert _max_err(d50[70:], pub["d"][70:]) <= 1e-6
    assert all(math.isnan(v) for v in ind["k"][:8]) and all(math.isnan(v) for v in ind["d"][:8])


@pytest.mark.parametrize("code", CODES)
def test_kd_recursion_seeded_from_published(symbols, code):
    """k[i] = ⅔k[i−1] + ⅓rsv[i], d likewise, with bar highs/lows over 9 bars (04 §2.5)."""
    bars, pub = symbols[code]["bars"], symbols[code]["indicators"]
    k, d = pub["k"][7], pub["d"][7]
    err_k = err_d = 0.0
    for i in range(8, 250):
        h9 = max(b[2] for b in bars[i - 8: i + 1])
        l9 = min(b[3] for b in bars[i - 8: i + 1])
        rsv = (bars[i][4] - l9) / (h9 - l9) * 100.0
        k = k * 2 / 3 + rsv / 3
        d = d * 2 / 3 + k / 3
        err_k = max(err_k, abs(k - pub["k"][i]))
        err_d = max(err_d, abs(d - pub["d"][i]))
    assert err_k <= 1e-9 and err_d <= 1e-9


def test_kd_flat_window_gives_fifty():
    flat = [[f"d{i}", 50, 50, 50, 50.0, 1] for i in range(20)]
    k, d = I.kd(flat)
    assert k[8:] == [50.0] * 12 and d[8:] == [50.0] * 12
    assert I.kd60(flat) == (50.0, 50.0, 50.0, 50.0)


# --------------------------------------------------------------------------- kd60 (spec §4.7)

def test_kd60_matches_hand_recursion():
    bars60 = [[f"2026-10-30T{9 + i % 5:02d}:00:00+08:00", 0.0, 0.0, 0.0, 0.0, 10] for i in range(14)]
    closes = [100, 101, 103, 102, 104, 106, 105, 107, 109, 108, 110, 107, 105, 104]
    for b, c in zip(bars60, closes):
        b[1], b[2], b[3], b[4] = c - 0.5, c + 1.0, c - 1.0, float(c)
    ks, ds = [], []
    kp = dp = None
    for i in range(8, 14):
        h9 = max(b[2] for b in bars60[i - 8: i + 1])
        l9 = min(b[3] for b in bars60[i - 8: i + 1])
        rsv = (bars60[i][4] - l9) / (h9 - l9) * 100.0
        kp = rsv if kp is None else kp * 2 / 3 + rsv / 3
        dp = kp if dp is None else dp * 2 / 3 + kp / 3
        ks.append(kp)
        ds.append(dp)
    k, d, k_prev, d_prev = I.kd60(bars60)
    assert (k, d, k_prev, d_prev) == pytest.approx((ks[-1], ds[-1], ks[-2], ds[-2]), abs=1e-12)
    # fewer than 9 bars → neutral; exactly 9 bars → prev == current
    assert I.kd60(bars60[:8]) == (50.0, 50.0, 50.0, 50.0)
    k1, d1, kp1, dp1 = I.kd60(bars60[:9])
    assert (k1, d1) == (kp1, dp1) and k1 == pytest.approx(ks[0])


def test_kd60_unrounded_values_round_like_snapshot(symbols):
    """The published intraday_kd rounds k/d to 1 dp and formats the note from the raw
    values (spec §4.7); kd60 must hand back raw floats so scoring can do both."""
    kd = symbols["2330"]["intraday_kd"]
    assert kd["k"] == round(kd["k"], 1) and kd["d"] == round(kd["d"], 1)
    k, d, *_ = I.kd60(symbols["2330"]["bars"])
    assert isinstance(k, float) and isinstance(d, float)
    assert f"60分K線 K={k:.0f} D={d:.0f}".startswith("60分K線 K=")


# --------------------------------------------------------------------------- published (spec §3.3)

@pytest.mark.parametrize("code", CODES)
def test_published_window_is_finite_and_matches_tail(symbols, code):
    bars, pub = symbols[code]["bars"], symbols[code]["indicators"]
    out_bars, out = I.published(bars, I.compute(bars))
    assert out_bars == bars[-250:] and len(out_bars) == 250
    assert tuple(out.keys()) == I.INDICATOR_KEYS
    for key in I.INDICATOR_KEYS:
        assert len(out[key]) == 250
        assert all(isinstance(v, float) and math.isfinite(v) for v in out[key])
    # tail where warm-up is complete on the 250-bar window alone
    for key, lo in (("ma5", 4), ("ma20", 19), ("ma60", 59), ("bb_up", 19), ("bb_low", 19), ("rsi", 14)):
        assert _max_err(out[key][lo:], pub[key][lo:]) <= 1e-9
    for key in ("k", "d"):
        assert _max_err(out[key][70:], pub[key][70:]) <= 1e-6
    json.dumps(out, ensure_ascii=False, allow_nan=False)                          # C4: never NaN


def test_published_backfills_short_history():
    bars = _synthetic_bars(30)
    ind = I.compute(bars)
    out_bars, out = I.published(bars, ind)
    assert out_bars == bars
    for key in I.INDICATOR_KEYS:
        assert len(out[key]) == 30 and all(math.isfinite(v) for v in out[key])
    # head is back-filled with the first finite value of the window
    assert out["rsi"][:14] == [ind["rsi"][14]] * 14 and out["rsi"][14:] == ind["rsi"][14:]
    assert out["ma20"][:19] == [ind["ma20"][19]] * 19
    assert out["k"][:8] == [ind["k"][8]] * 8
    # a whole array without a finite value falls back to the close (MA/BB keys)
    assert out["ma60"] == [b[4] for b in bars]
    assert all(math.isnan(v) for v in ind["ma60"])
    # very short history: neutral constants
    tiny = bars[:3]
    _, out3 = I.published(tiny, I.compute(tiny))
    assert out3["rsi"] == [50.0] * 3 and out3["k"] == [50.0] * 3 and out3["d"] == [50.0] * 3
    assert out3["ma20"] == [b[4] for b in tiny] and out3["bb_up"] == [b[4] for b in tiny]
    ind3 = I.compute(tiny)
    for key in ("macd", "macd_sig", "macd_hist"):                                  # finite from bar 0
        assert out3[key] == ind3[key] and all(math.isfinite(v) for v in ind3[key])
    assert out3["macd"][0] == 0.0 and out3["macd_sig"][0] == 0.0
    # the neutral MACD fallback only ever applies when nothing finite exists at all
    assert I._fill_finite([float("nan")] * 3, tiny, "macd") == [0.0] * 3


def test_published_slices_last_n_of_longer_history():
    bars = _synthetic_bars(400)
    ind = I.compute(bars)
    out_bars, out = I.published(bars, ind, n=250)
    assert out_bars == bars[-250:]
    for key in I.INDICATOR_KEYS:
        assert out[key] == ind[key][-250:]                                        # no fill needed


# --------------------------------------------------------------------------- trend (spec §4.9, 02 §9)

@pytest.mark.parametrize("code", CODES)
def test_trend_reproduces_published(symbols, code):
    sym = symbols[code]
    got = I.trend(sym["bars"], sym["indicators"])
    gold = sym["trend"]
    assert json.dumps(got["segments"], ensure_ascii=False) == json.dumps(gold["segments"], ensure_ascii=False)
    assert got["summary"] == gold["summary"]
    assert list(got.keys()) == ["segments", "summary"]
    assert list(got["summary"].keys()) == ["regime", "slope20", "slope60", "slope120",
                                           "dist_ma60", "high_252", "low_252", "pos_252"]
    assert all(list(s.keys()) == ["start", "end", "regime", "ret"] for s in got["segments"])


@pytest.mark.parametrize("code", CODES)
def test_trend_segments_tile_window_and_ret(symbols, code):
    sym = symbols[code]
    bars = sym["bars"]
    segs = I.trend(bars, sym["indicators"])["segments"]
    dates = [b[0] for b in bars]
    close = {b[0]: b[4] for b in bars}
    assert segs[0]["start"] == dates[0] and segs[-1]["end"] == dates[-1]
    for a, b in zip(segs, segs[1:]):
        assert dates.index(b["start"]) == dates.index(a["end"]) + 1
    for s in segs:
        assert s["regime"] in ("bull", "bear", "range")
        assert s["ret"] == round(close[s["end"]] / close[s["start"]] - 1, 4)


@pytest.mark.parametrize("code", CODES)
def test_trend_summary_from_own_indicators(symbols, code):
    """With indicators computed on the window alone the summary still reproduces (it only
    uses the last bar); head segments may differ because ma60[0..58] needs pre-window bars."""
    sym = symbols[code]
    bars = sym["bars"]
    _, own = I.published(bars, I.compute(bars))
    got = I.trend(bars, own)
    assert got["summary"] == sym["trend"]["summary"]
    assert got["segments"][-1] == sym["trend"]["segments"][-1]


def test_trend_regime_is_raw_label_of_last_bar(symbols):
    """2308: last segment is range but the summary regime is bear (02 §9.2)."""
    sym = symbols["2308"]
    got = I.trend(sym["bars"], sym["indicators"])
    assert got["segments"][-1]["regime"] == "range" and got["summary"]["regime"] == "bear"
    c, m20, m60 = sym["bars"][-1][4], sym["indicators"]["ma20"][-1], sym["indicators"]["ma60"][-1]
    assert c < m20 < m60


def test_trend_run_smoothing_rules():
    """Runs shorter than 5 bars adopt the previous (possibly relabelled) label; the first
    run is kept; the summary regime is the raw label of the last bar."""
    n = 30
    bars = [[f"d{i:02d}", 1.0, 1.0, 1.0, 1.0, 1] for i in range(n)]
    ma20 = [1.0] * n
    ma60 = [1.0] * n
    labels = ["bull"] * 10 + ["range"] * 3 + ["bear"] * 2 + ["bull"] * 5 + ["bear"] * 10
    triples = {"bull": (3.0, 2.0, 1.0), "bear": (0.5, 1.0, 2.0), "range": (1.0, 1.0, 1.0)}

    def _apply(labs):
        for i, lab in enumerate(labs):
            bars[i][4], ma20[i], ma60[i] = triples[lab]
            assert I.regime_label(bars[i][4], ma20[i], ma60[i]) == lab

    _apply(labels)
    got = I.trend(bars, {"ma20": ma20, "ma60": ma60})
    assert [(s["regime"], s["start"], s["end"]) for s in got["segments"]] == [
        ("bull", "d00", "d19"), ("bear", "d20", "d29")]
    assert got["summary"]["regime"] == "bear"
    assert got["segments"][0]["ret"] == round(3.0 / 3.0 - 1, 4)
    # a short first run is kept as is
    _apply(["range"] * 2 + ["bull"] * 28)
    got2 = I.trend(bars, {"ma20": ma20, "ma60": ma60})
    assert [s["regime"] for s in got2["segments"]] == ["range", "bull"]
    # a 4-bar run between two others adopts the (already relabelled) previous label
    _apply(["bull"] * 6 + ["range"] * 4 + ["bear"] * 4 + ["bull"] * 16)
    got3 = I.trend(bars, {"ma20": ma20, "ma60": ma60})
    assert [s["regime"] for s in got3["segments"]] == ["bull"]
    # exactly 5 bars start a new segment
    _apply(["bull"] * 6 + ["range"] * 5 + ["bull"] * 19)
    got4 = I.trend(bars, {"ma20": ma20, "ma60": ma60})
    assert [(s["regime"], s["start"], s["end"]) for s in got4["segments"]] == [
        ("bull", "d00", "d05"), ("range", "d06", "d10"), ("bull", "d11", "d29")]


def test_trend_uses_252_closes_of_full_history(symbols):
    """high_252/low_252 look back 252 closes of whatever history is given (Q-A15)."""
    sym = symbols["2330"]
    bars = sym["bars"]
    spike = ["pre0", 9999.0, 9999.0, 9999.0, 9999.0, 0]
    filler = ["pre1", 2000.0, 2000.0, 2000.0, 2000.0, 0]                           # inside [low, high]
    pre = [spike, filler]
    ind = I.compute(pre + bars)
    got = I.trend(pre + bars, ind)
    assert got["summary"]["high_252"] == 9999.0                                   # 252nd bar back counts
    assert got["summary"]["low_252"] == sym["trend"]["summary"]["low_252"]
    assert got["segments"][0]["start"] == bars[0][0] and got["segments"][-1]["end"] == bars[-1][0]
    pre3 = [spike, filler, ["pre2", 2000.0, 2000.0, 2000.0, 2000.0, 0]]
    got3 = I.trend(pre3 + bars, I.compute(pre3 + bars))
    assert got3["summary"]["high_252"] == sym["trend"]["summary"]["high_252"]     # 253rd bar back is ignored
    assert got3["summary"]["pos_252"] == sym["trend"]["summary"]["pos_252"]


def test_trend_short_history_is_finite():
    bars = _synthetic_bars(12)
    got = I.trend(bars, I.compute(bars))
    json.dumps(got, ensure_ascii=False, allow_nan=False)
    assert got["summary"]["regime"] == "range" and got["summary"]["dist_ma60"] == 0.0
    assert got["segments"][0]["start"] == bars[0][0] and got["segments"][-1]["end"] == bars[-1][0]
    assert I.trend([], {})["segments"] == []
    flat = [[f"d{i}", 5.0, 5.0, 5.0, 5.0, 1] for i in range(70)]
    got_flat = I.trend(flat, I.compute(flat))
    assert got_flat["summary"] == {"regime": "range", "slope20": 0.0, "slope60": 0.0, "slope120": 0.0,
                                   "dist_ma60": 0.0, "high_252": 5.0, "low_252": 5.0, "pos_252": 0.0}


def test_regime_label_nan_is_range():
    nan = float("nan")
    assert I.regime_label(2.0, 1.5, 1.0) == "bull"
    assert I.regime_label(1.0, 1.5, 2.0) == "bear"
    assert I.regime_label(1.0, nan, 2.0) == "range"
    assert I.regime_label(2.0, 1.5, 1.5) == "range"


# --------------------------------------------------------------------------- atr14 (spec §4.11)

@pytest.mark.parametrize("code", CODES)
def test_atr14_matches_appendix_table_and_suggest_qty(symbols, data, code):
    bars = symbols[code]["bars"]
    atr = I.atr14(bars)
    assert round(atr, 4) == ATR_TABLE[code]
    row = next(r for r in data["overview"]["rows"] if r["code"] == code)
    cash = data["overview"]["account"]["cash"]
    q = math.floor(min(0.0075 * cash / atr, 0.30 * cash / row["price"]))
    assert q == row["suggest_qty"]


def test_atr14_synthetic():
    bars = [["d0", 10, 12, 9, 11.0, 1], ["d1", 11, 15, 10, 14.0, 1], ["d2", 14, 14.5, 8, 9.0, 1]]
    tr = [12 - 9, max(15 - 10, abs(15 - 11), abs(10 - 11)), max(14.5 - 8, abs(14.5 - 14), abs(8 - 14))]
    assert I.true_range(bars) == tr
    assert I.atr14(bars) == pytest.approx(sum(tr) / 3)
    long = _synthetic_bars(40)
    trs = I.true_range(long)
    assert I.atr14(long) == pytest.approx(sum(trs[-14:]) / 14)
    assert I.atr14([]) == 0.0


# --------------------------------------------------------------------------- sigma20 (spec §4.10 baseline)

@pytest.mark.parametrize("code", CODES)
def test_sigma20_matches_published_baseline_bands(symbols, code):
    sym = symbols[code]
    assert sym["forecast"]["model"] == "baseline"
    sigma = I.sigma20(sym["bars"])
    by_h = {h["horizon_days"]: h for h in sym["forecast"]["horizons"]}
    for h in (1, 5, 20):
        assert abs(by_h[h]["ci68"][1] - sigma * math.sqrt(h)) <= 1e-15 * (1 + sigma * math.sqrt(h) * 1e3)
        assert abs(by_h[h]["ci95"][1] - 1.96 * sigma * math.sqrt(h)) <= 1e-15 * 10
    assert abs(by_h[1]["ci68"][1] - sigma) <= 1e-16


def test_sigma20_synthetic():
    closes = [100.0, 101.0, 99.0, 102.0, 102.0, 105.0]
    bars = [[f"d{i}", c, c, c, c, 1] for i, c in enumerate(closes)]
    rets = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]
    assert I.sigma20(bars) == pytest.approx(statistics.stdev(rets), abs=1e-15)
    long = _synthetic_bars(100)
    cl = [b[4] for b in long]
    rets = [cl[i] / cl[i - 1] - 1 for i in range(len(cl) - 20, len(cl))]
    assert I.sigma20(long) == pytest.approx(statistics.stdev(rets), abs=1e-15)
    assert I.sigma20(bars[:2]) == 0.0 and I.sigma20([]) == 0.0
    flat = [[f"d{i}", 5.0, 5.0, 5.0, 5.0, 1] for i in range(30)]
    assert I.sigma20(flat) == 0.0


# --------------------------------------------------------------------------- serialization (C4)

@pytest.mark.parametrize("code", CODES)
def test_everything_serializes_without_nan(symbols, code):
    bars = symbols[code]["bars"]
    out_bars, ind = I.published(bars, I.compute(bars))
    doc = {"bars": out_bars, "indicators": ind, "trend": I.trend(bars, ind),
           "atr14": I.atr14(bars), "sigma20": I.sigma20(bars), "kd60": I.kd60(bars)}
    raw = json.dumps(doc, ensure_ascii=False, allow_nan=False)
    assert "NaN" not in raw and "Infinity" not in raw
