"""Forecasts, prediction ledger and model-health metrics (spec §4.10, §7.5, Q-F1…Q-F7, Q-P13).

Ledger rows live in ``state/predictions.jsonl`` (shape in ``state.py``); the frozen
aggregates recovered from the 2026-10-31 snapshot live in ``state/predictions_seed.json``
and are merged additively: n = n_seed + n_new, mae = (mae_seed·n_seed + Σ|err|_new)/n,
hit_rate = (hit_seed·n_seed + hits_new)/n; seed ``series`` rows are kept verbatim and a
new resolution week that collides with a seed week is merged the same way.

Models (spec §4.10, appendix 07 §1):

* ``baseline`` — zero-drift random walk: ``σ = close.pct_change().tail(20).std(ddof=1)``,
  ``pred_ret = 0.0``, ``prob_up = 0.5``, ``ci68 = ±σ√h``, ``ci95 = ±1.96σ√h`` (1.96 exactly),
  everything unrounded.  Reproduces the 9 snapshot files to ≤ 4e-16.
* ``ridge`` — drifted forecast with its own error scale ``s_h``: ``ci68 = pred ± s_h``,
  ``ci95 = pred ± 1.96 s_h``, ``prob_up = Φ(pred / s_h)``.  The internals were lost; the
  spec Q-F1 default is implemented: per horizon a ridge regression (α = 1.0) on the last
  250 bars with the 9 features {1-, 5-, 20-day returns, RSI14, MACD hist, K, D, BB %b,
  20-day volume ratio} (z-scored, unpenalised intercept), target = forward h-day simple
  return, ``s_h`` = residual std (ddof = 1).  Deterministic (plain linear algebra).

The fan (spec §4.10, 02 §10.2): ``dates = pd.bdate_range(made_date, periods=21)`` (weekdays,
holidays not removed); every band is ``base_price · exp(np.interp(i, [0,1,5,20],
[0, ln(1+x_1), ln(1+x_5), ln(1+x_20)]))`` — piece-wise linear in log-price space.

Ledger semantics (spec §4.10, Q-F4): ``record`` upserts the 6 rows of ``made_date =
bars[-1][0]`` keyed by ``(symbol, model, horizon, made_date)``; ``resolve`` fills every
pending row whose target bar (made index + h) exists with ``realized = close[target] /
close[made] − 1``, ``abs_err = |pred − realized|``, ``hit = (pred ≥ 0) == (realized ≥ 0)``
and never recomputes a resolved row (bars re-adjust later).

Everything except ``record``/``resolve`` (which mutate ``State.predictions`` and persist it)
is pure: no clock, no I/O beyond what ``State`` already holds.
"""
from __future__ import annotations

import math
from datetime import datetime

import numpy as np
import pandas as pd

from . import clock
from .state import State, append_jsonl

HORIZONS = (1, 5, 20)
MODELS = ("baseline", "ridge")
BASELINE, RIDGE = MODELS

Z95 = 1.96                      # spec §4.10: 1.96 exactly, not Φ⁻¹(0.975)
SIGMA_WINDOW = 20               # baseline volatility lookback (simple returns, ddof = 1)
FAN_POINTS = 21                 # anchor + 20 weekdays
FAN_KNOTS = (0,) + HORIZONS     # bar offsets of the interpolation knots
CHAMPION_MIN_N = 30             # spec Q-F2: a horizon needs n ≥ 30 before ridge can win
MAE_DP, HIT_DP = 6, 4           # published rounding of model-health.json (spec §7.5)

RIDGE_ALPHA = 1.0               # spec Q-F1
RIDGE_WINDOW = 250              # training rows (bars) per horizon
RIDGE_MIN_ROWS = 40             # fewer finite training rows → zero-drift fallback (still named "ridge")
RIDGE_FEATURES = ("ret1", "ret5", "ret20", "rsi", "macd_hist", "k", "d", "pct_b", "vol_ratio")
_RIDGE_IND_KEYS = ("rsi", "macd_hist", "k", "d", "bb_up", "bb_low")

QUALITY_RECENT_DAYS = 5         # spec Q-F7: champion 1-day forecasts over the last 5 trading days
QUALITY_REF_DAYS = 60           # … against the trailing 60-day MAE
QUALITY_HIT_MAX = 0.40
QUALITY_MAE_RATIO = 1.5
QUALITY_TEMPLATE = "偵測到預測品質下降(命中率 {hit:.0f}%,MAE 惡化 {mae:.0f}%),自動觸發調參"

LEDGER_KEYS = ("symbol", "code", "model", "horizon", "made_date", "pred_ret",
               "target_date", "realized", "abs_err", "hit", "resolved_at")
HORIZON_KEYS = ("horizon_days", "pred_ret", "ci68", "ci95", "prob_up", "model")
FAN_KEYS = ("dates", "median", "lo68", "hi68", "lo95", "hi95")


# ---------------------------------------------------------------- small helpers

def _closes(bars: list) -> list:
    return [float(b[4]) for b in bars]


def _finite(x) -> bool:
    try:
        return math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def sigma20(bars: list) -> float:
    """Sample std (ddof = 1) of the last 20 simple daily returns; 0.0 when undefined."""
    if len(bars) < 3:
        return 0.0
    rets = pd.Series(_closes(bars)).pct_change().tail(SIGMA_WINDOW)
    if int(rets.notna().sum()) < 2:
        return 0.0
    s = float(rets.std(ddof=1))
    return s if math.isfinite(s) else 0.0


def norm_cdf(x: float) -> float:
    """Standard normal CDF Φ (``Φ(0) == 0.5`` exactly)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def prob_up(pred_ret: float, s: float) -> float:
    """``Φ(pred_ret / s)``; a zero error scale degenerates to a step (never NaN)."""
    if not (s > 0.0) or not math.isfinite(s):
        return 0.5 if pred_ret == 0.0 else (1.0 if pred_ret > 0.0 else 0.0)
    p = norm_cdf(pred_ret / s)
    return p if math.isfinite(p) else 0.5


def _horizon_row(h: int, pred: float, s: float, model: str) -> dict:
    """One ``horizons[]`` entry; with ``pred == 0.0`` this is exactly ``±s`` / ``±1.96 s``."""
    pred = float(pred) if _finite(pred) else 0.0
    s = float(s) if _finite(s) and s >= 0.0 else 0.0
    return {"horizon_days": int(h), "pred_ret": pred,
            "ci68": [pred - s, pred + s],
            "ci95": [pred - Z95 * s, pred + Z95 * s],
            "prob_up": prob_up(pred, s), "model": model}


# ---------------------------------------------------------------- models

def baseline(bars: list) -> list:
    """Zero-drift horizons ``[{"horizon_days","pred_ret","ci68","ci95","prob_up","model"}]`` (exact, spec §4.10)."""
    if len(bars) < 3:
        return []
    sigma = sigma20(bars)
    return [_horizon_row(h, 0.0, sigma * math.sqrt(h), BASELINE) for h in HORIZONS]


def _aligned(values, n: int) -> np.ndarray:
    """Trailing ``n`` entries of an indicator array as floats (front-padded with NaN)."""
    arr = np.full(n, np.nan)
    vals = [float(v) if _finite(v) else np.nan for v in list(values or [])]
    if vals:
        tail = vals[-n:]
        arr[n - len(tail):] = tail
    return arr


def ridge_features(bars: list, ind: dict | None) -> np.ndarray:
    """``(len(bars), 9)`` feature matrix (NaN where undefined), columns ``RIDGE_FEATURES``.

    ``ind`` is the indicator dict aligned with the end of ``bars`` (the published 11
    arrays or ``indicators.compute`` output); missing keys are recomputed from ``bars``."""
    n = len(bars)
    ind = dict(ind or {})
    if any(not ind.get(k) for k in _RIDGE_IND_KEYS):
        from . import indicators            # local import: indicators is pure and heavy
        computed = indicators.compute(bars)
        for k in _RIDGE_IND_KEYS:
            if not ind.get(k):
                ind[k] = computed[k]
    close = np.array(_closes(bars), dtype=float)
    vol = np.array([float(b[5]) for b in bars], dtype=float)
    X = np.full((n, len(RIDGE_FEATURES)), np.nan)

    def lag_ret(lag: int) -> np.ndarray:
        out = np.full(n, np.nan)
        if n > lag:
            prev = close[:-lag]
            with np.errstate(divide="ignore", invalid="ignore"):
                out[lag:] = np.where(prev != 0.0, close[lag:] / prev - 1.0, np.nan)
        return out

    X[:, 0] = lag_ret(1)
    X[:, 1] = lag_ret(5)
    X[:, 2] = lag_ret(20)
    X[:, 3] = _aligned(ind["rsi"], n)
    X[:, 4] = _aligned(ind["macd_hist"], n)
    X[:, 5] = _aligned(ind["k"], n)
    X[:, 6] = _aligned(ind["d"], n)
    up, low = _aligned(ind["bb_up"], n), _aligned(ind["bb_low"], n)
    width = up - low
    with np.errstate(divide="ignore", invalid="ignore"):
        pct_b = np.where(width > 0.0, (close - low) / width, 0.5)
    pct_b[~np.isfinite(up) | ~np.isfinite(low)] = np.nan
    X[:, 7] = pct_b
    vr = np.full(n, np.nan)
    if n >= SIGMA_WINDOW:
        mean20 = pd.Series(vol).rolling(SIGMA_WINDOW).mean().to_numpy()
        with np.errstate(divide="ignore", invalid="ignore"):
            vr = np.where(mean20 > 0.0, vol / mean20, 1.0)
        vr[~np.isfinite(mean20)] = np.nan
    X[:, 8] = vr
    return X


def _ridge_fit(X: np.ndarray, y: np.ndarray, x_last: np.ndarray, alpha: float) -> tuple:
    """Ridge with an unpenalised intercept on z-scored features → ``(pred, residual_std)``."""
    mu = X.mean(axis=0)
    sd = X.std(axis=0)
    sd = np.where(sd > 0.0, sd, 1.0)
    Z = (X - mu) / sd
    ymean = float(y.mean())
    yc = y - ymean
    p = Z.shape[1]
    beta = np.linalg.solve(Z.T @ Z + alpha * np.eye(p), Z.T @ yc)
    resid = yc - Z @ beta
    s = float(np.std(resid, ddof=1)) if len(resid) > 1 else float("nan")
    pred = ymean + float(((x_last - mu) / sd) @ beta)
    return pred, s


def ridge(bars: list, ind: dict) -> list:
    """Ridge-regression horizons with the same shape (spec Q-F1 defaults; name stays ``"ridge"``)."""
    if len(bars) < 3:
        return []
    sigma = sigma20(bars)
    n = len(bars)
    X = ridge_features(bars, ind)
    close = np.array(_closes(bars), dtype=float)
    x_last = X[-1]
    start = max(0, n - RIDGE_WINDOW)
    rows = []
    for h in HORIZONS:
        pred, s = 0.0, sigma * math.sqrt(h)
        last = n - 1 - h
        if last >= start and np.all(np.isfinite(x_last)):
            idx = np.arange(start, last + 1)
            with np.errstate(divide="ignore", invalid="ignore"):
                y = close[idx + h] / close[idx] - 1.0
            ok = np.all(np.isfinite(X[idx]), axis=1) & np.isfinite(y)
            if int(ok.sum()) >= RIDGE_MIN_ROWS:
                p_fit, s_fit = _ridge_fit(X[idx][ok], y[ok], x_last, RIDGE_ALPHA)
                if math.isfinite(p_fit):
                    pred = p_fit
                if math.isfinite(s_fit) and s_fit > 0.0:
                    s = s_fit
        rows.append(_horizon_row(h, pred, s, RIDGE))
    return rows


# ---------------------------------------------------------------- fan and block

def fan_dates(made_date: str, periods: int = FAN_POINTS) -> list:
    """``pd.bdate_range(made_date, periods=21)`` as ``YYYY-MM-DD`` strings (weekdays only)."""
    return [d.strftime("%Y-%m-%d") for d in pd.bdate_range(str(made_date)[:10], periods=periods)]


def _log_band(x: float) -> float:
    return math.log(max(1.0 + float(x), 1e-12))


def fan(bars: list, horizons: list) -> dict:
    """21-point fan ``{"dates","median","lo68","hi68","lo95","hi95"}`` (spec §4.10, log-linear interpolation)."""
    empty = {k: [] for k in FAN_KEYS}
    if not bars or not horizons:
        return empty
    made_date = str(bars[-1][0])[:10]
    base = float(bars[-1][4])
    by_h = {int(r["horizon_days"]): r for r in horizons}
    knots = [0] + [h for h in HORIZONS if h in by_h]
    if len(knots) < 2:
        return empty
    x = np.arange(FAN_POINTS)
    out = {"dates": fan_dates(made_date)}
    picks = {"median": ("pred_ret", None), "lo68": ("ci68", 0), "hi68": ("ci68", 1),
             "lo95": ("ci95", 0), "hi95": ("ci95", 1)}
    for key, (field, idx) in picks.items():
        vals = [0.0]
        for h in knots[1:]:
            v = by_h[h][field]
            vals.append(_log_band(v if idx is None else v[idx]))
        out[key] = (base * np.exp(np.interp(x, knots, vals))).tolist()
    return out


def forecast_block(bars: list, ind: dict, model: str) -> dict:
    """Symbol-file ``forecast`` object for ``model`` (spec §7.2)."""
    model = model if model in MODELS else BASELINE
    if not bars:
        return {"made_date": None, "model": model, "base_price": None, "horizons": [],
                "fan": {k: [] for k in FAN_KEYS}}
    horizons = ridge(bars, ind) if model == RIDGE else baseline(bars)
    return {"made_date": str(bars[-1][0])[:10], "model": model, "base_price": bars[-1][4],
            "horizons": horizons, "fan": fan(bars, horizons)}


def forecast5(block: dict) -> dict | None:
    """``rows[].forecast5 = {pred_ret, prob_up, ci68_lo, ci68_hi, model}`` of the h=5 entry (spec §4.10)."""
    for r in (block or {}).get("horizons") or []:
        if int(r["horizon_days"]) == 5:
            return {"pred_ret": r["pred_ret"], "prob_up": r["prob_up"],
                    "ci68_lo": r["ci68"][0], "ci68_hi": r["ci68"][1], "model": r["model"]}
    return None


# ---------------------------------------------------------------- ledger

def _is_row_of(row: dict, code: str, symbol: str | None = None) -> bool:
    return row.get("code") == code or (symbol is not None and row.get("symbol") == symbol)


def _resolved(row: dict) -> bool:
    return row.get("realized") is not None


def record(st: State, code: str, symbol: str, bars: list, ind: dict, at: datetime) -> int:
    """Upsert the 6 rows (2 models × 3 horizons) for ``made_date = bars[-1][0]``; returns rows written."""
    per_model = {BASELINE: baseline(bars), RIDGE: ridge(bars, ind) if len(bars) >= 3 else []}
    if not per_model[BASELINE]:
        return 0
    made_date = str(bars[-1][0])[:10]
    existing = {}
    for row in st.predictions:
        if _is_row_of(row, code, symbol) and row.get("made_date") == made_date:
            existing[(row.get("model"), int(row.get("horizon", 0)))] = row
    written, changed, new_rows = 0, False, []
    for model in MODELS:
        for hz in per_model[model]:
            h = int(hz["horizon_days"])
            pred = float(hz["pred_ret"])
            row = existing.get((model, h))
            if row is None:
                row = {"symbol": symbol, "code": code, "model": model, "horizon": h,
                       "made_date": made_date, "pred_ret": pred, "target_date": None,
                       "realized": None, "abs_err": None, "hit": None, "resolved_at": None}
                st.predictions.append(row)
                new_rows.append(row)
            elif row.get("pred_ret") != pred:
                row["pred_ret"] = pred
                if _resolved(row):
                    realized = float(row["realized"])
                    row["abs_err"] = abs(pred - realized)
                    row["hit"] = (pred >= 0.0) == (realized >= 0.0)
                changed = True
            written += 1
    if changed:
        st.save_predictions()
    else:
        for row in new_rows:
            append_jsonl(st.path("predictions.jsonl"), row)
    return written


def resolve(st: State, code: str, bars: list, at: datetime) -> int:
    """Resolve every pending row whose target bar exists (spec Q-F4); returns the count."""
    if not bars:
        return 0
    pos = {str(b[0])[:10]: i for i, b in enumerate(bars)}
    close = _closes(bars)
    stamp = clock.iso(at)
    count = 0
    for row in st.predictions:
        if not _is_row_of(row, code) or _resolved(row):
            continue
        i = pos.get(str(row.get("made_date", ""))[:10])
        if i is None:
            continue
        t = i + int(row.get("horizon", 0))
        if t >= len(bars) or t <= i or close[i] == 0.0:
            continue
        realized = close[t] / close[i] - 1.0
        if not math.isfinite(realized):
            continue
        pred = float(row.get("pred_ret") or 0.0)
        row["target_date"] = str(bars[t][0])[:10]
        row["realized"] = realized
        row["abs_err"] = abs(pred - realized)
        row["hit"] = (pred >= 0.0) == (realized >= 0.0)
        row["resolved_at"] = stamp
        count += 1
    if count:
        st.save_predictions()
    return count


# ---------------------------------------------------------------- aggregates

def _accumulate(agg: dict, key, row: dict) -> None:
    cell = agg.setdefault(key, [0, 0.0, 0])
    cell[0] += 1
    cell[1] += float(row["abs_err"])
    cell[2] += 1 if row.get("hit") else 0


def _merge(seed: dict | None, new: list | None, mae_dp: int | None, hit_dp: int | None) -> tuple | None:
    """``(n, mae, hit_rate)`` of seed aggregates ⊕ new rows; ``None`` when ``n == 0``.

    Seed-only groups return the seed values verbatim (Q-P13 / K8: frozen aggregates)."""
    n_seed = int(seed["n"]) if seed else 0
    n_new, sum_abs, hits = (new or [0, 0.0, 0])
    n = n_seed + n_new
    if n <= 0:
        return None
    if n_new == 0:
        return n_seed, float(seed["mae"]), float(seed["hit_rate"])
    mae_total = sum_abs + (float(seed["mae"]) * n_seed if seed else 0.0)
    hit_total = hits + (float(seed["hit_rate"]) * n_seed if seed else 0.0)
    mae, hit = mae_total / n, hit_total / n
    if mae_dp is not None:
        mae = round(mae, mae_dp)
    if hit_dp is not None:
        hit = round(hit, hit_dp)
    return n, mae, hit


def _champion_of(rows: list, h: int) -> str:
    cands = [r for r in rows if int(r["horizon"]) == h and int(r["n"]) >= CHAMPION_MIN_N]
    if not cands:
        return BASELINE
    best = min(cands, key=lambda r: (float(r["mae"]), MODELS.index(r["model"]) if r["model"] in MODELS else len(MODELS)))
    return best["model"]


def metrics(st: State) -> dict:
    """``model-health.json → metrics`` ``{"by_model_horizon","champion","series"}`` (spec §7.5)."""
    seed = st.predictions_seed or {}
    agg, weeks = {}, {}
    for row in st.predictions:
        if not _resolved(row) or row.get("abs_err") is None:
            continue
        key = (row.get("model"), int(row.get("horizon", 0)))
        _accumulate(agg, key, row)
        target = row.get("target_date")
        if target:
            monday = clock.ymd(clock.monday_of(clock.parse_date(str(target))))
            _accumulate(weeks, (monday,) + key, row)

    seed_bmh = {(r["model"], int(r["horizon"])): r for r in seed.get("by_model_horizon") or []}
    by_model_horizon = []
    for h in HORIZONS:
        for model in MODELS:
            merged = _merge(seed_bmh.get((model, h)), agg.get((model, h)), MAE_DP, HIT_DP)
            if merged:
                n, mae, hit = merged
                by_model_horizon.append({"model": model, "horizon": h, "n": n, "mae": mae, "hit_rate": hit})
    champion = {str(h): _champion_of(by_model_horizon, h) for h in HORIZONS}

    seed_series = {(r["date"], r["model"], int(r["horizon"])): r for r in seed.get("series") or []}
    series = []
    for key in sorted(set(seed_series) | set(weeks), key=lambda k: (k[0], k[1], k[2])):
        merged = _merge(seed_series.get(key), weeks.get(key), MAE_DP, HIT_DP)
        if merged:
            n, mae, hit = merged
            series.append({"date": key[0], "model": key[1], "horizon": key[2], "mae": mae, "hit_rate": hit, "n": n})
    return {"by_model_horizon": by_model_horizon, "champion": champion, "series": series}


def ledger_block(st: State, code: str) -> dict:
    """Symbol-file ``ledger`` ``{"by_horizon": [...]}`` (spec §7.2; rows with n = 0 omitted)."""
    seed = st.predictions_seed or {}
    seed_rows = {(r["model"], int(r["horizon"])): r
                 for r in (seed.get("by_symbol") or {}).get(code) or []}
    agg = {}
    for row in st.predictions:
        if _is_row_of(row, code) and _resolved(row) and row.get("abs_err") is not None:
            _accumulate(agg, (row.get("model"), int(row.get("horizon", 0))), row)
    out = []
    for h in HORIZONS:
        for model in MODELS:
            merged = _merge(seed_rows.get((model, h)), agg.get((model, h)), None, None)
            if merged:
                n, mae, hit = merged
                out.append({"model": model, "horizon": h, "n": n, "mae": mae, "hit_rate": hit})
    return {"by_horizon": out}


def brief(m: dict) -> dict:
    """``overview.model_health_brief`` from ``metrics()`` output (spec §4.10)."""
    rows = (m or {}).get("by_model_horizon") or []
    champ5 = ((m or {}).get("champion") or {}).get("5", BASELINE)
    row = next((r for r in rows if r["model"] == champ5 and int(r["horizon"]) == 5), None)
    return {"hit_rate_5d": row["hit_rate"] if row else None,
            "mae_5d": row["mae"] if row else None,
            "n_resolved": sum(int(r["n"]) for r in rows),
            "champion": champ5}


# ---------------------------------------------------------------- quality trigger

def quality_drop(st: State, at: datetime) -> tuple:
    """``(triggered, hit5_pct, mae_worse_pct)`` per spec Q-F7.

    ``hit5``/``mae5`` are the champion-1 one-day forecasts whose target dates are the
    last 5 distinct resolved bar dates (≤ ``at``), ``mae_ref`` the same over the last 60;
    triggered when ``hit5 < 0.40 and mae5 / mae_ref > 1.5``.  The percentages are the
    ``{hit5*100}`` / ``{(mae5/mae_ref − 1)*100}`` of the event template (format ``:.0f``,
    see :func:`quality_message`).  Needs at least 5 distinct target dates in the ledger."""
    champ1 = metrics(st)["champion"]["1"]
    today = clock.ymd(at)
    rows = [r for r in st.predictions
            if _resolved(r) and r.get("model") == champ1 and int(r.get("horizon", 0)) == 1
            and r.get("target_date") and str(r["target_date"]) <= today and r.get("abs_err") is not None]
    dates = sorted({str(r["target_date"]) for r in rows}, reverse=True)
    if len(dates) < QUALITY_RECENT_DAYS:
        return False, 0.0, 0.0
    recent, ref = set(dates[:QUALITY_RECENT_DAYS]), set(dates[:QUALITY_REF_DAYS])
    recent_rows = [r for r in rows if r["target_date"] in recent]
    ref_rows = [r for r in rows if r["target_date"] in ref]
    hit5 = sum(1 for r in recent_rows if r.get("hit")) / len(recent_rows)
    mae5 = sum(float(r["abs_err"]) for r in recent_rows) / len(recent_rows)
    mae_ref = sum(float(r["abs_err"]) for r in ref_rows) / len(ref_rows)
    if not (mae_ref > 0.0):
        return False, hit5 * 100.0, 0.0
    ratio = mae5 / mae_ref
    triggered = hit5 < QUALITY_HIT_MAX and ratio > QUALITY_MAE_RATIO
    return triggered, hit5 * 100.0, (ratio - 1.0) * 100.0


def quality_message(hit5_pct: float, mae_worse_pct: float) -> str:
    """Verbatim WARN text of spec §8.2 (``偵測到預測品質下降(命中率 33%,MAE 惡化 155%),自動觸發調參``)."""
    return QUALITY_TEMPLATE.format(hit=hit5_pct, mae=mae_worse_pct)
