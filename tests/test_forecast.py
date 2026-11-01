"""Golden tests for ``engine.forecast`` against the frozen 2026-10-31 snapshot (spec §4.10,
§7.2, §7.5, Q-F1…Q-F7, Q-P13; appendices 07 §1–§2 and 02 §10–§11).

Every Oct symbol file carries the ``baseline`` model, so the baseline horizons, the fan and
the whole ``forecast`` block are reproduced on all 9 files.  The ``ridge`` fan and the
``prob_up = Φ(pred/s)`` invariant are checked on the Aug bake (git ``2e74138``) whose
2454/0050 forecast blocks are embedded verbatim below (the only surviving ridge output).
The ledger / metrics / brief tests seed ``predictions_seed.json`` from the fixture files in
the format of ``engine/state.py`` and verify byte-identity with ``model-health.json``,
``overview.model_health_brief`` and every symbol's ``ledger``.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from engine import clock
from engine import forecast as F
from engine.state import State, check_finite, dumps, read_jsonl, write_json, write_jsonl
from tests.conftest import CODES, SNAPSHOT

AT = datetime(2026, 10, 31, 14, 15, 22, tzinfo=clock.TZ)

# Aug 2026-08-15 bake (git 2e74138): symbol/2454.json → bars[-1] + forecast (ridge), verbatim.
AUG_2454 = json.loads(
    '{"bar":["2026-08-14",4400.0,4400.0,4205.0,4210.0,9711256],"forecast":{"made_date":"2026-08-14",'
    '"model":"ridge","base_price":4210.0,"horizons":[{"horizon_days":1,"pred_ret":0.009153985490194472,'
    '"ci68":[-0.02241297122868459,0.04072094220907353],"ci95":[-0.05271724967880849,0.07102522065919743],'
    '"prob_up":0.6140866469070353,"model":"ridge"},{"horizon_days":5,"pred_ret":0.057365854674403555,'
    '"ci68":[-0.020499402712902626,0.13523111206170974],"ci95":[-0.09525004980471655,0.20998175915352366],'
    '"prob_up":0.7693574374526652,"model":"ridge"},{"horizon_days":20,"pred_ret":0.18067813912728076,'
    '"ci68":[-0.0224502213605752,0.3838064996151367],"ci95":[-0.21745344742891692,0.5788097256834784],'
    '"prob_up":0.8131267883585852,"model":"ridge"}],"fan":{"dates":["2026-08-14","2026-08-17","2026-08-18",'
    '"2026-08-19","2026-08-20","2026-08-21","2026-08-24","2026-08-25","2026-08-26","2026-08-27","2026-08-28",'
    '"2026-08-31","2026-09-01","2026-09-02","2026-09-03","2026-09-04","2026-09-07","2026-09-08","2026-09-09",'
    '"2026-09-10","2026-09-11"],"median":[4210.0,4248.538278913719,4298.3967189217665,4348.840269355293,'
    '4399.875796738999,4451.510248179239,4484.366782324123,4517.465830082551,4550.809181444072,'
    '4584.3986396101245,4618.2360210915485,4652.323155806827,4686.661887181044,4721.254072245579,'
    '4756.101581738533,4791.206300205899,4826.570126103478,4862.194971899546,4898.082764178277,'
    '4934.23544374394,4970.654965725852],"lo68":[4210.0,4115.6413911272375,4117.653945296254,'
    '4119.667483606963,4121.682006540611,4123.69751457868,4123.149475264172,4122.601508784077,'
    '4122.053615128716,4121.505794288411,4120.958046253484,4120.41037101426,4119.862768561064,'
    '4119.315238884222,4118.767781974063,4118.220397820916,4117.673086415111,4117.125847746982,'
    '4116.57868180686,4116.0315885850805,4115.484568071978],"hi68":[4210.0,4381.435166700199,'
    '4477.6886008568,4576.056575850921,4676.585544912963,4779.322981779798,4842.828833142984,'
    '4907.178526442096,4972.383274332308,5038.45443845835,5105.403531434226,5173.242218849238,'
    '5241.982321300665,5311.635816453444,5382.2148411272365,5453.731693411213,5526.198834806936,'
    '5599.628892399732,5674.034661058897,5749.429105667153,5825.825363379726],"lo95":[4210.0,'
    '3988.060378852216,3942.520494196315,3897.500632031917,3852.994854193088,3808.9972903221433,'
    '3772.327920601344,3736.011568373925,3700.044835126315,3664.4243550625697,3629.1467947893966,'
    '3594.208853004216,3559.607260186219,3525.3387782904047,3491.4002004445624,3457.7883506491676,'
    '3424.5000834801713,3391.532283794648,3358.8818664392775,3326.5457759616356,3294.52098632426],'
    '"hi95":[4210.0,4509.016178975221,4648.647065998778,4792.601908368048,4941.0146061837195,'
    '5094.023206036333,5185.185728978332,5277.979694348646,5372.4342984037075,5468.579259895489,'
    '5566.444829422068,5666.061798945534,5767.461511480231,5870.675870954362,5975.737352248112,'
    '6082.679011411372,6191.534496064349,6302.338055984294,6415.124553881688,6529.929476369283,'
    '6646.788945127443]}}}')

# Aug bake symbol/0050.json → forecast.horizons (ridge), verbatim (spec 07 §1.3 quotes h=5 → Φ = 0.551739).
AUG_0050_HORIZONS = json.loads(
    '[{"horizon_days":1,"pred_ret":-0.00040493645643316,"ci68":[-0.018308746787165108,0.017498873874298788],'
    '"ci95":[-0.03549640470466777,0.03468653179180146],"prob_up":0.4909777584535898,"model":"ridge"},'
    '{"horizon_days":5,"pred_ret":0.0048279761151826805,"ci68":[-0.03229404441890493,0.041949996649270294],'
    '"ci95":[-0.06793118413162905,0.07758713636199441],"prob_up":0.5517393081989325,"model":"ridge"},'
    '{"horizon_days":20,"pred_ret":0.0510678629007913,"ci68":[-0.021043718049376305,0.12317944385095891],'
    '"ci95":[-0.09027083576153722,0.1924065615631198],"prob_up":0.7605827561952883,"model":"ridge"}]')

# Aug bake model-health.json → metrics.by_model_horizon (ridge was the h=5 champion at n=179; h=20 at n=38).
AUG_BY_MODEL_HORIZON = json.loads(
    '[{"model":"baseline","horizon":1,"n":215,"mae":0.025301,"hit_rate":0.5349},'
    '{"model":"ridge","horizon":1,"n":215,"mae":0.025734,"hit_rate":0.5163},'
    '{"model":"baseline","horizon":5,"n":179,"mae":0.056801,"hit_rate":0.5866},'
    '{"model":"ridge","horizon":5,"n":179,"mae":0.055381,"hit_rate":0.5475},'
    '{"model":"baseline","horizon":20,"n":38,"mae":0.057026,"hit_rate":0.6053},'
    '{"model":"ridge","horizon":20,"n":38,"mae":0.08141,"hit_rate":0.4211}]')
AUG_CHAMPION = {"1": "baseline", "5": "ridge", "20": "baseline"}
AUG_BRIEF = {"hit_rate_5d": 0.5475, "mae_5d": 0.055381, "n_resolved": 864, "champion": "ridge"}


# ---------------------------------------------------------------- helpers

def _max_abs(a, b) -> float:
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    assert a.shape == b.shape
    return float(np.max(np.abs(a - b))) if a.size else 0.0


def _synthetic_bars(n: int, seed: int = 11, start: float = 100.0, first: str = "2026-01-05") -> list:
    """Deterministic random-walk daily bars on weekdays ``[date, o, h, l, c, v]``."""
    rng = np.random.default_rng(seed)
    dates = [d.strftime("%Y-%m-%d") for d in pd.bdate_range(first, periods=n)]
    bars, c = [], start
    for d in dates:
        o = c
        c = round(c * float(np.exp(rng.normal(0.0, 0.015))), 2)
        hi, lo = round(max(o, c) * 1.01, 2), round(min(o, c) * 0.99, 2)
        bars.append([d, o, hi, lo, c, int(rng.integers(1_000_000, 5_000_000))])
    return bars


def _seed_from_fixture(model_health: dict, symbols: dict, source: str = "fixtures/snapshot-2026-10-31") -> dict:
    """The ``predictions_seed.json`` object in the format documented in ``engine/state.py``."""
    return {"source": source,
            "by_model_horizon": json.loads(json.dumps(model_health["metrics"]["by_model_horizon"])),
            "series": json.loads(json.dumps(model_health["metrics"]["series"])),
            "by_symbol": {code: json.loads(json.dumps(symbols[code]["ledger"]["by_horizon"])) for code in CODES}}


def _seeded_state(tmp_state, model_health, symbols) -> State:
    write_json(tmp_state / "predictions_seed.json", _seed_from_fixture(model_health, symbols))
    return State.load(tmp_state)


def _row(code, model, h, made, target, pred, realized, resolved_at="2026-11-03T14:15:30+08:00") -> dict:
    return {"symbol": f"{code}.TW", "code": code, "model": model, "horizon": h, "made_date": made,
            "pred_ret": pred, "target_date": target, "realized": realized,
            "abs_err": abs(pred - realized), "hit": (pred >= 0) == (realized >= 0), "resolved_at": resolved_at}


# ---------------------------------------------------------------- baseline (spec §4.10, 07 §1.2)

@pytest.mark.parametrize("code", CODES)
def test_baseline_reproduces_fixture_horizons(symbols, code):
    sym = symbols[code]
    got = F.baseline(sym["bars"])
    want = sym["forecast"]["horizons"]
    assert sym["forecast"]["model"] == "baseline"
    assert len(got) == 3
    for g, w in zip(got, want):
        assert list(g.keys()) == list(w.keys()) == list(F.HORIZON_KEYS)
        assert g["horizon_days"] == w["horizon_days"]
        assert g["pred_ret"] == 0.0 and g["prob_up"] == 0.5 and g["model"] == "baseline"
        assert isinstance(g["pred_ret"], float) and isinstance(g["prob_up"], float)
        assert _max_abs(g["ci68"], w["ci68"]) <= 1e-12
        assert _max_abs(g["ci95"], w["ci95"]) <= 1e-12
        assert g["ci68"][0] == -g["ci68"][1] and g["ci95"][0] == -g["ci95"][1]
        assert g["ci95"][1] == 1.96 * g["ci68"][1]


def test_baseline_sigma_is_std_of_last_20_simple_returns(symbols):
    for code in CODES:
        bars = symbols[code]["bars"]
        close = pd.Series([b[4] for b in bars])
        sigma = float(close.pct_change().tail(20).std(ddof=1))
        rows = F.baseline(bars)
        for r in rows:
            assert abs(r["ci68"][1] - sigma * math.sqrt(r["horizon_days"])) <= 1e-15


def test_baseline_short_history():
    assert F.baseline([]) == []
    assert F.baseline(_synthetic_bars(2)) == []
    rows = F.baseline(_synthetic_bars(3))
    assert [r["horizon_days"] for r in rows] == [1, 5, 20]
    check_finite(rows)


# ---------------------------------------------------------------- fan (spec §4.10, 02 §10.2)

@pytest.mark.parametrize("code", CODES)
def test_fan_reproduces_fixture(symbols, code):
    sym = symbols[code]
    want = sym["forecast"]["fan"]
    got = F.fan(sym["bars"], sym["forecast"]["horizons"])
    assert list(got.keys()) == list(want.keys()) == list(F.FAN_KEYS)
    assert got["dates"] == want["dates"]
    assert got["dates"][0] == sym["bars"][-1][0] == sym["forecast"]["made_date"]
    for key in ("median", "lo68", "hi68", "lo95", "hi95"):
        assert len(got[key]) == 21
        assert _max_abs(got[key], want[key]) <= 1e-12
        assert all(isinstance(v, float) for v in got[key])
    assert got["median"] == [sym["bars"][-1][4]] * 21          # flat for baseline


def test_fan_reproduces_aug_ridge_2454():
    want = AUG_2454["forecast"]["fan"]
    got = F.fan([AUG_2454["bar"]], AUG_2454["forecast"]["horizons"])
    assert got["dates"] == want["dates"]
    assert got["dates"][-1] == "2026-09-11"
    for key in ("median", "lo68", "hi68", "lo95", "hi95"):
        g, w = np.asarray(got[key]), np.asarray(want[key])
        # drifted ridge fan: ≤ 2 ulp at price 6646 (spec 07 §1.4 quotes 9.1e-13 on this file)
        assert float(np.max(np.abs(g - w) / np.abs(w))) <= 1e-12
        assert _max_abs(g, w) <= 2e-12


def test_fan_dates_are_weekdays_only():
    assert F.fan_dates("2026-10-30")[:3] == ["2026-10-30", "2026-11-02", "2026-11-03"]
    assert F.fan_dates("2026-10-30")[-1] == "2026-11-27"
    assert len(F.fan_dates("2026-08-14")) == 21 and F.fan_dates("2026-08-14")[-1] == "2026-09-11"


def test_fan_empty_inputs():
    empty = {k: [] for k in F.FAN_KEYS}
    assert F.fan([], []) == empty
    assert F.fan(_synthetic_bars(5), []) == empty


# ---------------------------------------------------------------- forecast block (spec §7.2)

@pytest.mark.parametrize("code", CODES)
def test_forecast_block_matches_fixture(symbols, data, code):
    sym = symbols[code]
    block = F.forecast_block(sym["bars"], sym["indicators"], "baseline")
    want = sym["forecast"]
    assert list(block.keys()) == list(want.keys()) == ["made_date", "model", "base_price", "horizons", "fan"]
    assert block["made_date"] == want["made_date"] == sym["bars"][-1][0]
    assert block["model"] == "baseline"
    assert block["base_price"] == want["base_price"] == sym["bars"][-1][4]
    assert dumps(block["fan"]["dates"]) == dumps(want["fan"]["dates"])
    for g, w in zip(block["horizons"], want["horizons"]):
        assert _max_abs(g["ci95"], w["ci95"]) <= 1e-12
    check_finite(block)
    # rows[].forecast5 twin (spec §4.10): the h=5 entry flattened, same key order
    row = next(r for r in data["overview"]["rows"] if r["code"] == code)
    f5 = F.forecast5(block)
    assert list(f5.keys()) == list(row["forecast5"].keys()) == ["pred_ret", "prob_up", "ci68_lo", "ci68_hi", "model"]
    assert f5["pred_ret"] == row["forecast5"]["pred_ret"] and f5["prob_up"] == row["forecast5"]["prob_up"]
    assert abs(f5["ci68_lo"] - row["forecast5"]["ci68_lo"]) <= 1e-12
    assert abs(f5["ci68_hi"] - row["forecast5"]["ci68_hi"]) <= 1e-12
    assert f5["model"] == row["forecast5"]["model"] == "baseline"


def test_forecast_block_ridge_and_edge_cases(symbols):
    sym = symbols["2330"]
    block = F.forecast_block(sym["bars"], sym["indicators"], "ridge")
    assert block["model"] == "ridge" and all(h["model"] == "ridge" for h in block["horizons"])
    assert block["fan"]["dates"] == sym["forecast"]["fan"]["dates"]
    assert block["fan"]["median"][0] == sym["bars"][-1][4]
    check_finite(block)
    empty = F.forecast_block([], {}, "baseline")
    assert empty["horizons"] == [] and empty["fan"]["dates"] == []
    assert F.forecast5(empty) is None
    assert F.forecast_block(sym["bars"], sym["indicators"], "unknown")["model"] == "baseline"


# ---------------------------------------------------------------- ridge (spec Q-F1, 07 §1.3)

def test_prob_up_formula_matches_aug_ridge_outputs():
    """``prob_up = Φ(pred_ret / s_h)`` with ``s_h = (ci68_hi − ci68_lo)/2`` on the surviving ridge rows."""
    for h in AUG_2454["forecast"]["horizons"] + AUG_0050_HORIZONS:
        s = (h["ci68"][1] - h["ci68"][0]) / 2
        assert abs(F.prob_up(h["pred_ret"], s) - h["prob_up"]) <= 1e-9
        assert abs((h["ci68"][0] + h["ci68"][1]) / 2 - h["pred_ret"]) <= 1e-16
        assert abs((h["ci95"][1] - h["ci95"][0]) / (h["ci68"][1] - h["ci68"][0]) - 1.96) <= 1e-12
    assert F.prob_up(0.0, 0.02) == 0.5
    assert F.prob_up(0.01, 0.0) == 1.0 and F.prob_up(-0.01, 0.0) == 0.0 and F.prob_up(0.0, 0.0) == 0.5


@pytest.mark.parametrize("code", CODES)
def test_ridge_shape_and_invariants(symbols, code):
    sym = symbols[code]
    rows = F.ridge(sym["bars"], sym["indicators"])
    assert [r["horizon_days"] for r in rows] == [1, 5, 20]
    for r in rows:
        assert list(r.keys()) == list(F.HORIZON_KEYS)
        assert r["model"] == "ridge"
        pred = r["pred_ret"]
        s = (r["ci68"][1] - r["ci68"][0]) / 2
        assert s > 0.0 and math.isfinite(pred)
        # centred on pred_ret (07 §1.3: to 1e-17), ci95 half-width = 1.96 × ci68 half-width
        assert abs((r["ci68"][0] + r["ci68"][1]) / 2 - pred) <= 1e-16
        assert abs((r["ci95"][0] + r["ci95"][1]) / 2 - pred) <= 1e-16
        assert abs((r["ci95"][1] - r["ci95"][0]) / (r["ci68"][1] - r["ci68"][0]) - 1.96) <= 1e-12
        assert abs(r["ci68"][0] - (pred - s)) <= 1e-15 and abs(r["ci68"][1] - (pred + s)) <= 1e-15
        assert abs(r["prob_up"] - F.prob_up(pred, s)) <= 1e-12
        assert 0.0 <= r["prob_up"] <= 1.0
        assert abs(r["prob_up"] - 0.5 * (1 + math.erf(pred / s / math.sqrt(2)))) <= 1e-12
    # the error scale is model specific (not σ20·√h) but of the same magnitude (spec 07 §1.3: 0.49–1.04)
    sigma = F.sigma20(sym["bars"])
    for r in rows:
        ratio = ((r["ci68"][1] - r["ci68"][0]) / 2) / (sigma * math.sqrt(r["horizon_days"]))
        assert 0.2 < ratio < 3.0
    check_finite(rows)


def test_ridge_is_deterministic_and_drifted(symbols):
    sym = symbols["2454"]
    a = F.ridge(sym["bars"], sym["indicators"])
    b = F.ridge(sym["bars"], sym["indicators"])
    assert dumps(a) == dumps(b)
    assert any(r["pred_ret"] != 0.0 for r in a)
    # works without a precomputed indicator dict (features recomputed from the bars)
    c = F.ridge(sym["bars"], {})
    assert [r["horizon_days"] for r in c] == [1, 5, 20] and all(r["model"] == "ridge" for r in c)
    check_finite(c)


def test_ridge_features_shape(symbols):
    sym = symbols["2330"]
    X = F.ridge_features(sym["bars"], sym["indicators"])
    assert X.shape == (250, len(F.RIDGE_FEATURES))
    assert np.all(np.isfinite(X[20:]))          # only the 20-day warm-up may be NaN
    assert np.all((X[:, 7][np.isfinite(X[:, 7])] > -5) & (X[:, 7][np.isfinite(X[:, 7])] < 6))


def test_ridge_short_history_falls_back_to_zero_drift():
    bars = _synthetic_bars(30)
    rows = F.ridge(bars, {})
    base = F.baseline(bars)
    assert [r["model"] for r in rows] == ["ridge"] * 3
    for r, b in zip(rows, base):
        assert r["pred_ret"] == 0.0 and r["prob_up"] == 0.5
        assert r["ci68"] == b["ci68"] and r["ci95"] == b["ci95"]
    assert F.ridge([], {}) == [] and F.ridge(_synthetic_bars(2), {}) == []


# ---------------------------------------------------------------- record / resolve (spec §4.10, Q-F4)

def test_record_and_resolve_lifecycle(tmp_state):
    st = State.load(tmp_state)
    bars = _synthetic_bars(120)
    ind = {}
    n0 = 60
    assert F.record(st, "2330", "2330.TW", bars[:n0], ind, AT) == 6
    rows = read_jsonl(tmp_state / "predictions.jsonl")
    assert len(rows) == 6 and len(st.predictions) == 6
    assert [(r["model"], r["horizon"]) for r in rows] == [("baseline", 1), ("baseline", 5), ("baseline", 20),
                                                          ("ridge", 1), ("ridge", 5), ("ridge", 20)]
    for r in rows:
        assert list(r.keys()) == list(F.LEDGER_KEYS)
        assert r["symbol"] == "2330.TW" and r["code"] == "2330" and r["made_date"] == bars[n0 - 1][0]
        assert r["target_date"] is None and r["realized"] is None and r["abs_err"] is None
        assert r["hit"] is None and r["resolved_at"] is None
        assert isinstance(r["pred_ret"], float)
    assert all(r["pred_ret"] == 0.0 for r in rows if r["model"] == "baseline")

    # idempotent upsert: same bars again → same 6 rows, nothing duplicated, file unchanged
    before = (tmp_state / "predictions.jsonl").read_bytes()
    assert F.record(st, "2330", "2330.TW", bars[:n0], ind, AT) == 6
    assert len(st.predictions) == 6
    assert (tmp_state / "predictions.jsonl").read_bytes() == before

    # nothing resolvable yet (no bar after made_date)
    assert F.resolve(st, "2330", bars[:n0], AT) == 0
    assert all(r["realized"] is None for r in st.predictions)

    # one more bar → the two h=1 rows resolve with the spec formulas
    assert F.resolve(st, "2330", bars[:n0 + 1], AT) == 2
    made_close, target_close = bars[n0 - 1][4], bars[n0][4]
    realized = target_close / made_close - 1
    for r in st.predictions:
        if r["horizon"] == 1:
            assert r["target_date"] == bars[n0][0]
            assert r["realized"] == realized
            assert r["abs_err"] == abs(r["pred_ret"] - realized)
            assert r["hit"] == ((r["pred_ret"] >= 0) == (realized >= 0))
            assert r["resolved_at"] == "2026-10-31T14:15:22+08:00"
        else:
            assert r["realized"] is None
    # resolving again is a no-op (resolved rows are never recomputed, even when bars change)
    assert F.resolve(st, "2330", bars[:n0 + 1], AT) == 0
    shifted = [list(b) for b in bars[:n0 + 1]]
    shifted[n0][4] = shifted[n0][4] * 1.5
    assert F.resolve(st, "2330", shifted, AT) == 0
    assert all(r["realized"] == realized for r in st.predictions if r["horizon"] == 1)

    # h=5 and h=20 targets appear → 2 + 2 more resolutions; persisted on disk
    assert F.resolve(st, "2330", bars[:n0 + 5], AT) == 2
    assert F.resolve(st, "2330", bars[:n0 + 20], AT) == 2
    assert F.resolve(st, "2330", bars, AT) == 0
    r20 = next(r for r in st.predictions if r["horizon"] == 20 and r["model"] == "baseline")
    assert r20["target_date"] == bars[n0 - 1 + 20][0]
    assert r20["realized"] == bars[n0 - 1 + 20][4] / made_close - 1
    reloaded = State.load(tmp_state)
    assert dumps(reloaded.predictions) == dumps(st.predictions)
    assert all(r["realized"] is not None for r in reloaded.predictions)
    check_finite(reloaded.predictions)


def test_record_upsert_updates_pred_in_place_and_ignores_other_symbols(tmp_state):
    st = State.load(tmp_state)
    bars = _synthetic_bars(80)
    assert F.record(st, "2330", "2330.TW", bars[:60], {}, AT) == 6
    assert F.record(st, "2317", "2317.TW", bars[:60], {}, AT) == 6
    assert len(st.predictions) == 12
    # a corrected last bar (same date) re-records: pred_ret changes in place, no new row
    corrected = [list(b) for b in bars[:60]]
    corrected[-1][4] = corrected[-1][4] * 1.04
    assert F.record(st, "2330", "2330.TW", corrected, {}, AT) == 6
    assert len(st.predictions) == 12
    mine = [r for r in st.predictions if r["code"] == "2330"]
    assert [r["made_date"] for r in mine] == [bars[59][0]] * 6
    assert dumps(read_jsonl(tmp_state / "predictions.jsonl")) == dumps(st.predictions)
    # resolving 2317 touches only 2317 rows
    assert F.resolve(st, "2317", bars[:61], AT) == 2
    assert all(r["realized"] is None for r in st.predictions if r["code"] == "2330")
    # a new made_date adds 6 more rows (daily cadence: 9 symbols × 6 = 54 on a trading day)
    assert F.record(st, "2330", "2330.TW", bars[:61], {}, AT) == 6
    assert len(st.predictions) == 18
    assert F.record(st, "2330", "2330.TW", bars[:2], {}, AT) == 0


def test_daily_cadence_counts(tmp_state):
    """Recording every day and resolving the next: n_h = D − h once every target exists (07 §2.3)."""
    st = State.load(tmp_state)
    bars = _synthetic_bars(100)
    D = 30
    for k in range(70, 70 + D):                    # made_dates = bars[69] … bars[69 + D − 1]
        F.resolve(st, "2330", bars[:k], AT)
        F.record(st, "2330", "2330.TW", bars[:k], {}, AT)
    F.resolve(st, "2330", bars[:70 + D - 1], AT)   # history ends on the last made bar
    block = F.ledger_block(st, "2330")
    assert [(r["model"], r["horizon"], r["n"]) for r in block["by_horizon"]] == [
        ("baseline", 1, D - 1), ("ridge", 1, D - 1), ("baseline", 5, D - 5), ("ridge", 5, D - 5),
        ("baseline", 20, D - 20), ("ridge", 20, D - 20)]
    m = F.metrics(st)
    assert [r["n"] for r in m["by_model_horizon"]] == [D - 1, D - 1, D - 5, D - 5, D - 20, D - 20]
    for r in m["by_model_horizon"]:
        assert r["mae"] == round(r["mae"], 6) and r["hit_rate"] == round(r["hit_rate"], 4)
    assert all(r["n"] > 0 for r in m["series"])
    assert sum(r["n"] for r in m["series"] if r["model"] == "baseline" and r["horizon"] == 1) == D - 1
    assert m["champion"] == {"1": "baseline", "5": "baseline", "20": "baseline"}   # n < 30 everywhere


# ---------------------------------------------------------------- metrics / brief / ledger with the seed (Q-P13, K8)

def test_metrics_seed_only_is_byte_identical(tmp_state, model_health, symbols):
    st = _seeded_state(tmp_state, model_health, symbols)
    assert st.predictions == []
    m = F.metrics(st)
    assert list(m.keys()) == ["by_model_horizon", "champion", "series"]
    assert dumps(m) == dumps(model_health["metrics"])
    assert dumps(m["by_model_horizon"]) == dumps(model_health["metrics"]["by_model_horizon"])
    assert dumps(m["series"]) == dumps(model_health["metrics"]["series"])
    assert m["champion"] == {"1": "baseline", "5": "baseline", "20": "baseline"}
    assert len(m["series"]) == 92
    assert [r["n"] for r in m["by_model_horizon"]] == [639, 639, 603, 603, 462, 462]


def test_brief_seed_only_is_byte_identical(tmp_state, model_health, symbols, data):
    st = _seeded_state(tmp_state, model_health, symbols)
    b = F.brief(F.metrics(st))
    assert dumps(b) == dumps(data["overview"]["model_health_brief"])
    assert b == {"hit_rate_5d": 0.5439, "mae_5d": 0.044109, "n_resolved": 3408, "champion": "baseline"}


@pytest.mark.parametrize("code", CODES)
def test_ledger_block_seed_only_is_byte_identical(tmp_state, model_health, symbols, code):
    st = _seeded_state(tmp_state, model_health, symbols)
    assert dumps(F.ledger_block(st, code)) == dumps(symbols[code]["ledger"])


def test_ledger_sums_match_global_counts(tmp_state, model_health, symbols):
    st = _seeded_state(tmp_state, model_health, symbols)
    totals = {}
    for code in CODES:
        for r in F.ledger_block(st, code)["by_horizon"]:
            totals[(r["model"], r["horizon"])] = totals.get((r["model"], r["horizon"]), 0) + r["n"]
    for r in F.metrics(st)["by_model_horizon"]:
        assert totals[(r["model"], r["horizon"])] == r["n"]


def test_metrics_merges_new_rows_with_seed(tmp_state, model_health, symbols):
    st = _seeded_state(tmp_state, model_health, symbols)
    rows = [
        # resolution week 2026-10-26 (a seed week: n = 36 for every model/horizon)
        _row("2330", "baseline", 1, "2026-10-29", "2026-10-30", 0.0, 0.02),
        _row("2330", "ridge", 1, "2026-10-29", "2026-10-30", 0.004, -0.02),
        # resolution week 2026-11-02 (new week)
        _row("2317", "baseline", 1, "2026-10-30", "2026-11-02", 0.0, -0.01),
        _row("2317", "ridge", 1, "2026-10-30", "2026-11-02", -0.003, -0.01),
        _row("2330", "baseline", 5, "2026-10-26", "2026-11-02", 0.0, 0.03),
        _row("2330", "ridge", 5, "2026-10-26", "2026-11-02", 0.01, 0.03),
        # still pending → ignored everywhere
        {"symbol": "2330.TW", "code": "2330", "model": "baseline", "horizon": 20, "made_date": "2026-10-30",
         "pred_ret": 0.0, "target_date": None, "realized": None, "abs_err": None, "hit": None, "resolved_at": None},
    ]
    write_jsonl(tmp_state / "predictions.jsonl", rows)
    st = State.load(tmp_state)
    m = F.metrics(st)
    seed = model_health["metrics"]
    bmh = {(r["model"], r["horizon"]): r for r in m["by_model_horizon"]}
    sb = {(r["model"], r["horizon"]): r for r in seed["by_model_horizon"]}
    # baseline/1: 639 seed + 2 new
    r = bmh[("baseline", 1)]
    assert r["n"] == 641
    assert r["mae"] == round((0.020186 * 639 + 0.02 + 0.01) / 641, 6)
    assert r["hit_rate"] == round((0.4945 * 639 + 1 + 0) / 641, 4)
    r = bmh[("ridge", 1)]
    assert r["n"] == 641
    assert r["mae"] == round((0.021101 * 639 + 0.024 + 0.007) / 641, 6)
    assert r["hit_rate"] == round((0.4867 * 639 + 0 + 1) / 641, 4)
    r = bmh[("baseline", 5)]
    assert r["n"] == 604 and r["mae"] == round((0.044109 * 603 + 0.03) / 604, 6)
    assert r["hit_rate"] == round((0.5439 * 603 + 1) / 604, 4)
    # untouched groups stay verbatim
    assert bmh[("baseline", 20)] == sb[("baseline", 20)] and bmh[("ridge", 20)] == sb[("ridge", 20)]
    assert list(bmh.keys()) == [("baseline", 1), ("ridge", 1), ("baseline", 5), ("ridge", 5), ("baseline", 20), ("ridge", 20)]
    assert m["champion"] == {"1": "baseline", "5": "baseline", "20": "baseline"}
    # series: the colliding seed week is merged, the new week appended, everything else verbatim and sorted
    series = {(r["date"], r["model"], r["horizon"]): r for r in m["series"]}
    seed_series = {(r["date"], r["model"], r["horizon"]): r for r in seed["series"]}
    w = series[("2026-10-26", "baseline", 1)]
    assert w["n"] == 37 and w["mae"] == round((0.024718 * 36 + 0.02) / 37, 6)
    assert w["hit_rate"] == round((0.3889 * 36 + 1) / 37, 4)
    w = series[("2026-10-26", "ridge", 1)]
    assert w["n"] == 37 and w["mae"] == round((0.02511 * 36 + 0.024) / 37, 6)
    assert series[("2026-11-02", "baseline", 1)] == {"date": "2026-11-02", "model": "baseline", "horizon": 1,
                                                    "mae": 0.01, "hit_rate": 0.0, "n": 1}
    assert series[("2026-11-02", "ridge", 5)] == {"date": "2026-11-02", "model": "ridge", "horizon": 5,
                                                 "mae": 0.02, "hit_rate": 1.0, "n": 1}
    assert series[("2026-11-02", "baseline", 5)]["hit_rate"] == 1.0
    for key, row in seed_series.items():
        if key not in (("2026-10-26", "baseline", 1), ("2026-10-26", "ridge", 1)):
            assert series[key] == row
    assert len(m["series"]) == 92 + 4
    keys = [(r["date"], r["model"], r["horizon"]) for r in m["series"]]
    assert keys == sorted(keys)
    assert all(list(r.keys()) == ["date", "model", "horizon", "mae", "hit_rate", "n"] for r in m["series"])
    # brief follows the merged champion-5 row
    b = F.brief(m)
    assert b == {"hit_rate_5d": bmh[("baseline", 5)]["hit_rate"], "mae_5d": bmh[("baseline", 5)]["mae"],
                 "n_resolved": 641 + 641 + 604 + 604 + 462 + 462, "champion": "baseline"}
    # per-symbol ledger: unrounded merge on top of the symbol's seed rows
    lb = {(r["model"], r["horizon"]): r for r in F.ledger_block(st, "2330")["by_horizon"]}
    s2330 = {(r["model"], r["horizon"]): r for r in symbols["2330"]["ledger"]["by_horizon"]}
    assert lb[("baseline", 1)]["n"] == 74
    assert lb[("baseline", 1)]["mae"] == (s2330[("baseline", 1)]["mae"] * 73 + 0.02) / 74
    assert lb[("baseline", 1)]["hit_rate"] == (s2330[("baseline", 1)]["hit_rate"] * 73 + 1) / 74
    assert lb[("ridge", 20)] == s2330[("ridge", 20)]
    assert dumps(F.ledger_block(st, "2454")) == dumps(symbols["2454"]["ledger"])
    check_finite(m)


def test_champion_rule_threshold_and_aug_reproduction(tmp_state):
    """Q-F2: lower MAE wins only at n ≥ 30, else baseline; Aug bake (ridge h=5 at n=179, h=20 at n=38)."""
    write_json(tmp_state / "predictions_seed.json",
               {"source": "aug", "by_model_horizon": AUG_BY_MODEL_HORIZON, "series": [], "by_symbol": {}})
    st = State.load(tmp_state)
    m = F.metrics(st)
    assert m["champion"] == AUG_CHAMPION
    assert dumps(m["by_model_horizon"]) == dumps(AUG_BY_MODEL_HORIZON)
    assert dumps(F.brief(m)) == dumps(AUG_BRIEF)
    # below the threshold the better ridge row does not win
    small = [dict(r, n=29) for r in AUG_BY_MODEL_HORIZON]
    write_json(tmp_state / "predictions_seed.json", {"source": "x", "by_model_horizon": small, "series": [], "by_symbol": {}})
    assert F.metrics(State.load(tmp_state))["champion"] == {"1": "baseline", "5": "baseline", "20": "baseline"}
    exact = [dict(r, n=30) for r in AUG_BY_MODEL_HORIZON]
    write_json(tmp_state / "predictions_seed.json", {"source": "x", "by_model_horizon": exact, "series": [], "by_symbol": {}})
    assert F.metrics(State.load(tmp_state))["champion"] == {"1": "baseline", "5": "ridge", "20": "baseline"}
    # a tie goes to baseline
    tie = [dict(r, mae=0.05) for r in AUG_BY_MODEL_HORIZON]
    write_json(tmp_state / "predictions_seed.json", {"source": "x", "by_model_horizon": tie, "series": [], "by_symbol": {}})
    assert F.metrics(State.load(tmp_state))["champion"] == {"1": "baseline", "5": "baseline", "20": "baseline"}


def test_champion_from_new_rows_only(tmp_state):
    rows = []
    day = datetime(2026, 9, 1)
    for i in range(40):
        made = clock.ymd(day + timedelta(days=i))
        target = clock.ymd(day + timedelta(days=i + 1))
        rows.append(_row("2330", "baseline", 1, made, target, 0.0, 0.02))
        rows.append(_row("2330", "ridge", 1, made, target, 0.015, 0.02))
    write_jsonl(tmp_state / "predictions.jsonl", rows)
    m = F.metrics(State.load(tmp_state))
    assert [r["n"] for r in m["by_model_horizon"]] == [40, 40]           # no n = 0 rows for h=5/20
    assert m["champion"] == {"1": "ridge", "5": "baseline", "20": "baseline"}
    assert m["by_model_horizon"][1] == {"model": "ridge", "horizon": 1, "n": 40, "mae": 0.005, "hit_rate": 1.0}


def test_empty_state_shapes(tmp_state):
    st = State.load(tmp_state)
    m = F.metrics(st)
    assert m == {"by_model_horizon": [], "champion": {"1": "baseline", "5": "baseline", "20": "baseline"}, "series": []}
    assert F.brief(m) == {"hit_rate_5d": None, "mae_5d": None, "n_resolved": 0, "champion": "baseline"}
    assert F.ledger_block(st, "2330") == {"by_horizon": []}
    assert F.quality_drop(st, AT) == (False, 0.0, 0.0)
    assert dumps(m) == json.dumps(m, ensure_ascii=False)


# ---------------------------------------------------------------- quality trigger (spec Q-F7, §8.2)

def _quality_rows(recent_err: float, recent_hit: bool, days: int = 60, ref_err: float = 0.01) -> list:
    rows = []
    dates = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2026-07-01", periods=days + 1)]
    for i in range(days):
        made, target = dates[i], dates[i + 1]
        late = i >= days - 5
        realized = (-recent_err if late and not recent_hit else recent_err) if late else ref_err
        for code in ("2330", "2317"):
            rows.append(_row(code, "baseline", 1, made, target, 0.0, realized))
            rows.append(_row(code, "ridge", 1, made, target, 0.001, 0.05))     # ridge much worse → never champion
    return rows


def test_quality_drop_triggers(tmp_state, events):
    write_jsonl(tmp_state / "predictions.jsonl", _quality_rows(0.05, recent_hit=False))
    st = State.load(tmp_state)
    at = datetime(2026, 10, 1, 14, 15, tzinfo=clock.TZ)
    triggered, hit5, worse = F.quality_drop(st, at)
    assert triggered is True
    assert hit5 == 0.0
    mae_ref = (55 * 0.01 + 5 * 0.05) / 60
    assert abs(worse - (0.05 / mae_ref - 1) * 100) <= 1e-9
    msg = F.quality_message(hit5, worse)
    assert msg == "偵測到預測品質下降(命中率 0%,MAE 惡化 275%),自動觸發調參"
    # verbatim template vs the real event of the snapshot
    real = next(e["message"] for e in events["events"] if e["message"].startswith("偵測到預測品質下降"))
    assert F.quality_message(33.3, 155.2) == real == "偵測到預測品質下降(命中率 33%,MAE 惡化 155%),自動觸發調參"


def test_quality_drop_not_triggered(tmp_state):
    # recent hits are fine → no trigger even though the MAE ratio is above 1.5
    write_jsonl(tmp_state / "predictions.jsonl", _quality_rows(0.05, recent_hit=True))
    st = State.load(tmp_state)
    at = datetime(2026, 10, 1, 14, 15, tzinfo=clock.TZ)
    triggered, hit5, worse = F.quality_drop(st, at)
    assert triggered is False and hit5 == 100.0 and worse > 50.0
    # misses but no MAE deterioration → no trigger
    write_jsonl(tmp_state / "predictions.jsonl", _quality_rows(0.01, recent_hit=False))
    triggered, hit5, worse = F.quality_drop(State.load(tmp_state), at)
    assert triggered is False and hit5 == 0.0 and abs(worse) <= 1e-9
    # rows after ``at`` are ignored; fewer than 5 distinct target dates → inert
    write_jsonl(tmp_state / "predictions.jsonl", _quality_rows(0.05, recent_hit=False, days=4))
    assert F.quality_drop(State.load(tmp_state), at) == (False, 0.0, 0.0)
    write_jsonl(tmp_state / "predictions.jsonl", _quality_rows(0.05, recent_hit=False))
    assert F.quality_drop(State.load(tmp_state), datetime(2026, 6, 1, tzinfo=clock.TZ)) == (False, 0.0, 0.0)


# ---------------------------------------------------------------- serialization guard (spec §1.2 C4)

def test_published_shapes_are_finite_and_round_trip(symbols, tmp_state, model_health):
    st = _seeded_state(tmp_state, model_health, symbols)
    for code in CODES:
        sym = symbols[code]
        for model in F.MODELS:
            block = F.forecast_block(sym["bars"], sym["indicators"], model)
            raw = dumps(block)
            check_finite(block)
            assert json.dumps(json.loads(raw), ensure_ascii=False) == raw
        raw = dumps(F.ledger_block(st, code))
        assert json.dumps(json.loads(raw), ensure_ascii=False) == raw
    raw = dumps(F.metrics(st))
    assert json.dumps(json.loads(raw), ensure_ascii=False) == raw
    assert (SNAPSHOT / "model-health.json").read_text(encoding="utf-8").find(dumps(F.metrics(st))) == len('{"metrics": ')
