# 07 — Forecast ledger, model health, parameter tuner, reward points, event log, engine health/heartbeat, data freshness

Status: reverse-engineered from the two surviving bakes — **Oct** = working tree (`data.json` / `events.json` / `model-health.json` / `symbol/*.json`, baked 2026-10-31T14:15:22+08:00, git `8623d98`) and **Aug** = git `2e74138` (baked 2026-08-15T14:15:32+08:00) — plus the two AI daily reports embedded in `data.json.ai_report` (dated 2026-08-02 and 2026-10-12), which quote ledger counts as of those dates. No engine source survives. Every rule that is not literally visible in the files is marked **inferred** with its evidence and a confidence (high / medium / low); unresolved points are collected in §8 with a proposed default.

Companion documents: `01-data-json-contract.md` (§4.2 `engine.health`, §8 `reward`, §9 `model_health_brief`), `02-symbol-json-contract.md` (§10 `forecast`, §11 `ledger`), `03-orders-events-health-shadow-contract.md` (§2 `events.json`, §3 `model-health.json`, §4 `shadow.json`). Those documents describe the *file shapes and the viewer*; this one specifies the *engine semantics* behind them (formulas, counters, schedules, message templates) and only repeats shape details where needed for a formula. All timestamps are Taipei-local ISO-8601 with explicit offset and second precision (`2026-10-31T14:15:22+08:00`); dates are `YYYY-MM-DD`.

Analysis scripts used for every number below were run with `python3 -I` against the files; results are quoted inline.

---

## 1. Forecast models

### 1.1 Vocabulary and the champion

| Item | Rule | Evidence | Confidence |
|---|---|---|---|
| Model names | exactly two: `"baseline"` and `"ridge"` | `by_model_horizon` has 6 rows (2 models × 3 horizons) in both bakes; `ledger.by_horizon` likewise | high |
| Horizons | `1`, `5`, `20` **trading days** (bars), in this order everywhere | all files | high |
| Champion | **global** per horizon (not per symbol): `metrics.champion = {"1": m, "5": m, "20": m}` (string keys). Every `symbol/*.json → forecast.model` and every `forecast.horizons[].model` equal the champion of that horizon | Oct: all `baseline`; Aug: `{"1":"baseline","5":"ridge","20":"baseline"}` and every Aug symbol file carries `ridge` for all three horizons — see note | high |
| Champion rule | the model with the **lower `mae`** in `by_model_horizon` for that horizon, "when the sample is sufficient" (`樣本數足夠時取 MAE 較低者`, chip tooltip) | Aug h=5: ridge 0.055381 < baseline 0.056801 → ridge; Aug h=1 0.025301 < 0.025734 → baseline; Aug h=20 (n=38) 0.057026 < 0.081410 → baseline; Oct all baseline lower | high (rule), **low** (threshold — §8 Q2) |
| Published forecast model | Aug symbol files use `ridge` for **all three horizons** although only h=5's champion was ridge. **Inferred**: the per-symbol `forecast{}` block is produced by a single model = `champion["5"]` (the 5-day champion), and `horizons[].model` just repeats it | 9/9 Aug files; `model_health_brief.champion` also = `champion["5"]` | medium-high |

### 1.2 `baseline` — zero-drift random walk with a 20-day volatility band (**high**)

For a symbol with closes `c[0..N-1]` (N = 250 back-adjusted bars, `made_date = bars[-1].date`, `base_price = bars[-1].close`):

```
r_t  = c[t] / c[t-1] - 1                      # simple daily return (NOT log)
σ    = sample std (ddof = 1) of the last 20 values of r_t
       == pandas: pd.Series(closes).pct_change().tail(20).std()
for h in (1, 5, 20):
    pred_ret = 0.0
    prob_up  = 0.5
    ci68     = [-σ·√h, +σ·√h]
    ci95     = [-1.96·σ·√h, +1.96·σ·√h]        # 1.96 exactly, not Φ⁻¹(0.975)=1.959964
```

All values are emitted **unrounded** (`0.012245379348764842`). `ci68`/`ci95` are symmetric about 0 (`lo + hi == 0.0` exactly in 27/27 cases).

Fit evidence — ratio `ci68_hi / (std_L(returns) · √h)` over all 9 symbols × 3 horizons (27 cases), Oct bake:

| Lookback L (bars) | simple returns, ddof=1 | simple, ddof=0 | log returns, ddof=1 |
|---|---|---|---|
| 10 | 0.912 (0.744–1.144) | 0.961 | 0.906 |
| **20** | **1.000000 (max abs deviation 4e-16)** | 1.025978 constant (= √(20/19)) | 0.999 (0.977–1.007) |
| 30 | 1.045 (0.906–1.145) | 1.063 | 1.046 |
| 60 | 1.012 (0.850–1.181) | 1.021 | 1.016 |
| 120 | 0.773 (0.627–1.015) | 0.776 | 0.777 |
| 250 | 0.840 (0.610–1.084) | 0.842 | 0.846 |

`ci95_hi / ci68_hi = 1.9600` in 27/27 cases. Only L=20, simple returns, ddof=1 reproduces the files to floating-point precision; `ci68_hi − σ20·√h` is at most 7e-16.

### 1.3 `ridge` — drifted forecast with its own error scale (Aug bake; shape **high**, internals **unknown**)

Observed on all 9 Aug files (27 horizon rows):

| Quantity | Rule | Evidence |
|---|---|---|
| `pred_ret` | non-zero, e.g. 0050 h=1 `-0.00040493645643316`, h=20 `+0.0510678629007913`; 2454 h=20 `+0.18067813912728076` | values |
| `ci68` | `[pred_ret − s_h, pred_ret + s_h]` — **centred on `pred_ret`** (`(lo+hi)/2 == pred_ret` to 1e-17) | 27/27 |
| `ci95` | `[pred_ret − 1.96·s_h, pred_ret + 1.96·s_h]` (`half95/half68 = 1.9600` 27/27) | 27/27 |
| `s_h` | **not** `σ20·√h`: ratio `s_h / (σ20·√h)` ranges 0.49–1.04 (0050 h=1 0.55, 2454 h=20 0.90, 3481 h=20 1.04). So `s_h` is a model-specific error scale (e.g. residual std of the fitted regression for that horizon) | computed |
| `prob_up` | **`Φ(pred_ret / s_h)`** where `Φ` is the standard normal CDF and `s_h = (ci68_hi − ci68_lo)/2` — matches all 27 values to 6 dp (e.g. 0050 h=5: `0.0048279/0.037122 = 0.1301 → Φ = 0.551739` vs file `0.5517393081989325`). Using `σ20·√h` instead does **not** fit (0.526) | 27/27 |
| `model` | `"ridge"` in every `horizons[]` row and at the top level | 9/9 |

The regression features, training window and regularisation are **not recoverable** from the data (§8 Q1). The baseline's `prob_up = 0.5` is the same formula with `pred_ret = 0` (Φ(0) = 0.5), so one implementation serves both models.

### 1.4 `fan{}` — 21 points, log-linear interpolation between the three horizon knots (**high**, reproduced to 1e-12 for both models)

```
dates  = pd.bdate_range(made_date, periods=21)       # anchor + next 20 weekdays (Mon–Fri), holidays NOT removed
knots  = [0, 1, 5, 20]
med(i) = base_price · exp( interp(i, knots, [0, ln(1+pred_1), ln(1+pred_5), ln(1+pred_20)]) )
lo68(i)= base_price · exp( interp(i, knots, [0, ln(1+ci68_1[0]), ln(1+ci68_5[0]), ln(1+ci68_20[0])]) )
hi68, lo95, hi95 analogously (ci68[1], ci95[0], ci95[1])
```

`interp` = `numpy.interp` (piece-wise linear in log-price space). For `baseline` the median is flat (`== base_price` ×21). Verified: max abs error 9.1e-13 on Aug 2454 (ridge, drifted) and ≤1e-13 on all Oct files. Arrays: `dates`, `median`, `lo68`, `hi68`, `lo95`, `hi95`, each length 21; `dates[0] == made_date`, `dates[-1]` = 20th weekday after (`2026-11-27` for a `2026-10-30` anchor; `2026-09-11` for `2026-08-14`). The weekday calendar is used even though Taiwan holidays exist (no holiday fell inside either sampled range, so a holiday-aware calendar cannot be excluded — keep `bdate_range`).

### 1.5 Where the forecast is published

| Target | Content |
|---|---|
| `symbol/<code>.json → forecast` | `{made_date, model, base_price, horizons[3], fan}` with `base_price == bars[-1][4]`, `made_date == bars[-1][0]` |
| `data.json → overview.rows[].forecast5` | the h=5 entry flattened: `{pred_ret, prob_up, ci68_lo, ci68_hi, model}` (values byte-identical to the symbol file; no `ci95`) |
| `data.json → overview.model_health_brief` | §2.7 |

The published forecast is recomputed at every bake from the latest bars; it is **not** read back from the ledger (on the Saturday bake all nine `made_date` are `2026-10-30`, the last bar).

---

## 2. Forecast ledger (`記錄` / `兌現`)

The ledger is the engine's own store of every forecast ever issued and its realisation. The viewer never reads it; it feeds `ledger.by_horizon` (per symbol), `metrics.by_model_horizon`, `metrics.series`, `metrics.champion`, `model_health_brief`, the AI-report prompt and the tuner's quality trigger.

### 2.1 Recording (at EOD, per trading day) — **high**

| Rule | Evidence |
|---|---|
| One row per **(symbol, model, horizon, made_date)**: 9 symbols × 2 models × 3 horizons = **54** rows on a trading day | `EOD 完成:更新 9 檔資料,記錄 54 筆預測,兌現 54 筆。` on 08-13, 08-14, 10-29, 10-30 |
| `made_date` = the symbol's latest bar date; the forecast is computed from that bar's close with the formulas of §1 (both models are recorded, regardless of who is champion) | both models have identical `n` everywhere |
| Nothing is recorded when no new bar exists (Saturday): `記錄 0 筆預測` | 08-15 and 10-31 EOD |
| Recording is idempotent per key — a re-run on the same day must not create duplicates (see the AI-report count check in §2.3) | consistency of daily +9 |
| A row stores at least: `symbol, model, horizon, made_date, base_close, pred_ret` (and, for the record, `prob_up, ci68, ci95`); realised fields are filled at resolution | needed by §2.2 |

### 2.2 Resolution — **high** for the formulas, **medium** for the exact timing rule

```
target bar  = the bar h trading days after made_date (bar index + h)
realized    = close[target] / close[made] - 1               # simple return, same price series as the forecast
abs_err     = | pred_ret - realized |
hit         = ( pred_ret >= 0 ) == ( realized >= 0 )          # zero counts as "up" on both sides
```

Evidence for `realized` and `hit`:

| Check | Result |
|---|---|
| `metrics.series` week `2026-08-03`, baseline h=1: the 45 forecasts whose target bars are 08-03…08-07 (9 symbols × 5 days, made on the previous bar) give `mean(abs(realized)) = 0.022051` = file value (tolerance 1.5e-6) | exact |
| same week, hit rate with `realized >= 0` = **0.5111** = file; with `realized > 0` = 0.4889 ≠ file | `>=` confirmed |
| same week h=5: `mae = 0.070275` exact; hit `>=` 0.8222 = file (`>` would be 0.7778) | `>=` confirmed |
| same week h=20, `n = 6`: targets 08-07, made 07-09, the six original symbols only (`0050 2308 2317 2330 2454 2882`): `mae = 0.049373` exact | start date and target = +20 bars confirmed |
| first week `2026-07-06`, baseline h=1: `mae = 0.0`, `hit_rate = 1.0`, `n = 6` → realised return was exactly 0 for all six and counted as a hit; the ridge row of the same week has `hit_rate = 0.5` (= share of ridge `pred_ret >= 0`) | only `>=` explains both |
| per-symbol `ledger.by_horizon` hit rates reproduce with `>=` on the last-n windows for 2308/2317/2330/2882/2881 h=1 and 0050/2881/2882 h=20 (e.g. 2881 h=20 `0.9791666…` = 47/48; 2308 h=1 `0.5479` with `>=` vs 0.4795 with `>`) | `>=` confirmed |

Weeks other than 08-03 do **not** reproduce from today's bars to 1e-6 (they are within ±5 % in MAE) because the bars are back-adjusted for dividends after the fact and because the 0050 feed is unstable (§7); the engine resolves with the prices it held **at resolution time** and never rewrites `realized`. The rebuild must therefore store `realized`/`abs_err`/`hit` in the row when it resolves and must not recompute them from later price history.

Timing (**inferred**, medium): the EOD run resolves, for each symbol whose data was refreshed in that run, the forecasts whose target bar is that symbol's **latest** bar. Consequences visible in the data:

| EOD message | What happened | Evidence |
|---|---|---|
| `記錄 54 筆預測,兌現 54 筆` | normal trading day: 9 symbols got a new bar; 1 forecast per (symbol, model, horizon) resolved | 4 occurrences |
| `記錄 54 筆預測,兌現 48 筆` (08-13) | one symbol (0050, whose Yahoo feed lags — §7) had no 08-13 bar yet; its 6 resolutions were skipped. Next day it resolved only the target-08-14 forecasts (`兌現 54`, not 60); the 6 target-08-13 forecasts were **orphaned** permanently | AI report of 08-02 quotes h1 `n=126`, h5 `n=90`; Aug-15 bake shows 215/179 after 10 trading days: expected 216/180 → exactly one orphan per (model, horizon). `記錄 54` on 08-13 shows the stale symbol still "recorded" (idempotent re-write of its 08-12 row) |
| `記錄 0 筆預測,兌現 0 筆` (Sat 08-15) | no symbol had new data | — |
| `記錄 0 筆預測,兌現 6 筆` (Sat 10-31) | no new made_date, but one symbol's refetch returned a changed last bar (10-30 final correction), so its 6 target-10-30 forecasts were re-resolved (idempotent upsert; `n` unchanged at 73/69/53 for all six original symbols) | all nine symbols have identical `n` in Oct, so this was not a catch-up of a missing day; the only Saturday difference vs 08-15 is a refreshed bar |

Rebuild recommendation (deviation, flagged in §8 Q16): resolve **every pending** forecast whose target bar exists (no orphans) and make resolution an upsert; log the counts in the same message format.

### 2.3 Counters and their cross-checks

Each trading day adds exactly **9 per (model, horizon)** to the global `n` (= one per symbol): the 10-12 AI report quotes `n=531 / 495 / 354` (h=1/5/20); the 10-30 EOD gives `639 / 603 / 462`; the difference is 108 for every horizon = 12 trading days (10-13…10-30) × 9.

Per-symbol `ledger.by_horizon` (Oct):

| Group | Symbols | First `made_date` (**inferred**) | `n` h=1 / 5 / 20 | Check |
|---|---|---|---|---|
| original | 0050, 2308, 2317, 2330, 2454, 2882 | 2026-07-09 (week-07-06 rows, h=20 match in §2.2) | 73 / 69 / 53 | 6 × 73 = 438 |
| added later | 2881, 3481, 6789 | 2026-07-17 (week 07-13 h=1 `n=30` = 6 symbols × 5 days, week 07-20 `n=45` = 9 × 5) | 67 / 63 / 48 | 3 × 67 = 201 |
| global `by_model_horizon.n` | | | **639 / 603 / 462** | 438+201, 414+189, 318+144 ✓ |

Relationship between horizons: `n_1 − n_5 = 4 = 5 − 1` for every symbol (a forecast resolves `h` bars after it is made, so the 5-day count lags the 1-day count by 4 trading days); `n_5 − n_20 = 15 = 20 − 5` for the added symbols (16 for the originals: one extra orphan from the engine's first days, when its history contained a `2026-07-10` bar that no longer exists — the week-07-06 `mae = 0.0` row). Clean formula for the rebuild: with `D` = number of trading days on which the symbol received a forecast (first made_date … last bar inclusive), `n_h = D − h` once all targets exist. Observed values are 2–3 below this (`D=76` → 75/71/56 vs 73/69/53; `D=71` → 70/66/51 vs 67/63/48) because of the orphans above and a late-August outage (§2.5); the rebuild does not need to reproduce the deficits.

Rounding/serialisation:

| Field | `symbol/*.json → ledger.by_horizon[]` | `model-health.json → metrics.by_model_horizon[]` |
|---|---|---|
| `n` | int | int |
| `mae` | **unrounded** mean of `abs_err` | `round(x, 6)` |
| `hit_rate` | **unrounded** mean of `hit` | `round(x, 4)` |
| order | `(horizon asc, model asc)`: baseline 1, ridge 1, baseline 5, ridge 5, baseline 20, ridge 20 | same |
| no resolved rows yet | **unobserved** — propose omitting the row (viewer never reads the ledger; `by_model_horizon` is not rendered either) | |

### 2.4 Global metrics

`metrics.by_model_horizon[].{model, horizon, n, mae, hit_rate}` = the same aggregation over **all symbols** of all resolved rows (both bakes: `n` identical for the two models at each horizon, which follows from recording both models every day).

### 2.5 `metrics.series[]` — weekly rows keyed by the **target (resolution) week** (**high** for the key, **medium-high** for details)

| Field | Rule |
|---|---|
| `date` | Monday of the ISO week that contains the forecast's **target bar date** (= the date it was resolved on a normal day) |
| `model`, `horizon` | group keys |
| `mae` | `round(mean(abs_err), 6)` over the group |
| `hit_rate` | `round(mean(hit), 4)` |
| `n` | group size (identical for baseline and ridge in every row) |
| ordering | `(date asc, model asc, horizon asc)` |
| recomputation | the whole array is rebuilt from the ledger at every bake (the current week grows daily; rows never change afterwards because `realized` is frozen at resolution) |
| missing combos | no row at all (never `n: 0`) |

Why target week and not creation week: week `2026-10-26` has h=5 and h=20 rows with `n=36` although no forecast created that week could have resolved; week `2026-07-13` has h=5 `n=12` (= 6 symbols × the two forecasts made 07-09/07-10 whose 5-bar targets are 07-16/07-17) although 25+ 5-day forecasts were *created* that week; the exact match of week 08-03 in §2.2 uses target dates 08-03…08-07.

Observed `n` per week (baseline; ridge identical) with the calendar explanation:

| `date` | h=1 | h=5 | h=20 | Bars in week | Note |
|---|---|---|---|---|---|
| 2026-07-06 | 6 | — | — | 07-06…07-09 (07-10 absent today) | 6 original symbols, 1 day; `mae 0.0` (phantom 07-10 bar, see §2.3) |
| 07-13 | 30 | 12 | — | 5 | 6 symbols × 5; h=5: 6 × 2 |
| 07-20 | 45 | 33 | — | 5 | 9 symbols from 07-17 forecasts; h=5: 6×5 + 3×1 |
| 07-27 | 45 | 45 | — | 5 | |
| 08-03 | 45 | 45 | 6 | 5 | first 20-day resolutions (made 07-09) |
| 08-10 | 45 | 45 | 33 | 5 | h=20: 6×5 + 3×1 (added symbols' first 20-day) |
| 08-17 | 45 | 45 | 45 | 5 | |
| 08-24 | 17 | 44 | 44 | 5 | engine outage: h=1+h=5 of this and the next week sum to 63 each vs 90 expected (3 trading days without forecasts); h=20 unaffected (made in July) |
| 08-31 | 46 | 19 | 46 | 5 | 46/19 = asymmetric catch-up (0050 lag); |
| 09-07 | 45 | 45 | 45 | 5 | |
| 09-14 | 54 | 54 | 45 | 5 | one extra day's worth of h=1/h=5 — a catch-up EOD (the 09-14 17:56 tuner run shows an off-schedule EOD) |
| 09-21 | 27 | 27 | 9 | 4 (09-25 closed) | h=20 = 9: the 3 outage days of late August show up 20 bars later |
| 09-28 | 36 | 36 | 36 | 4 (09-28 closed) | |
| 10-05 | 36 | 36 | 36 | 4 (10-09 closed) | |
| 10-12 | 45 | 45 | 45 | 5 | |
| 10-19 | 36 | 36 | 36 | 4 (10-23 closed) | |
| 10-26 | 36 | 36 | 36 | 4 (10-26 closed) | partial week at bake time would still be a row |

Full weeks give `9 symbols × bars-in-week`; the rebuild gets this for free from the rule above.

Rendering reminder (03 §3.4): the viewer draws MAE as `+(mae*100).toFixed(3)` and hit rate as `+(hit_rate*100).toFixed(1)`, dashes the `baseline` line, and shows `資料累積中 — 預測需等到期兌現後才有誤差統計,第一天沒有資料是正常狀態。` while `series` is empty.

### 2.6 Weekly cadence of the ledger-derived outputs

`model-health.json` and `model_health_brief` are rebuilt at **every** bake (the Saturday bake carries the Friday numbers); nothing is weekly except the `series` grouping.

### 2.7 `overview.model_health_brief` (**high**)

```
champion5   = metrics.champion["5"]
row         = by_model_horizon[model == champion5, horizon == 5]
brief = {"hit_rate_5d": row.hit_rate (4 dp), "mae_5d": row.mae (6 dp),
         "n_resolved": Σ by_model_horizon[].n (both models, all horizons), "champion": champion5}
```

Oct: `{0.5439, 0.044109, 3408, "baseline"}` with 3408 = 639+639+603+603+462+462; Aug: `{0.5475, 0.055381, 864, "ridge"}` = ridge h=5 row, 864 = 2×(215+179+38). Key order as shown. Rendered `5日 MAE +4.4% ・ 命中率 54% ・ 已兌現 3408 筆`.

---

## 3. Parameter tuner (`調參`)

### 3.1 Runs: schedule, triggers and the event sequence

All 25 `params_history` rows (`adopted_at` = run time, **also for rejected rows**):

| Kind | Rows (`id` → `adopted_at`) | Rule (**inferred**) | Confidence |
|---|---|---|---|
| weekly scheduled | 3 (07-11 10:18), 6 (07-18 10:01), 7 (07-25 10:01), 9 (08-01 10:01), 10 (08-08 10:00), 11 (08-15 10:00), 14 (08-29 10:00), 15 (09-05 10:00), 17 (09-12 10:00), 19 (09-19 10:01), 21 (10-03 10:01), 22 (10-10 10:00), 24 (10-24 10:00), 25 (10-31 10:00) | **every Saturday 10:00 Taipei**; events: `[engine] 開始調參:walk-forward champion/challenger…` at 10:00:14–10:00:24, result 17–19 s later | high |
| missed-schedule catch-up | 13 (Sat 08-22 14:15:51), 20 (Sat 09-26 14:12:33), 23 (Sat 10-17 15:30:07) | Saturdays without a 10:00 row — the host was off at 10:00 and the job ran when the engine came up / after the Saturday EOD (the EOD is 14:15) | medium |
| after-EOD quality trigger | 8 (Wed 07-29 14:18), 12 (Wed 08-19 14:16), 16 (Fri 09-11 16:06), 18 (Mon 09-14 17:56) | preceded by `[engine] WARN 偵測到預測品質下降(命中率 {p}%,MAE 惡化 {q}%),自動觸發調參` then `開始調參…` (seen 10-30 14:15:45, where the run produced **no** row and no result event — the engine was restarted at 18:17, so the run died; the rebuild must always write a row) | medium |
| manual | 5 (07-18 09:58:43, `手動採用…`) and the bootstrap runs 1 (Thu 07-09 07:37), 2 (07-09 17:46), 4 (Fri 07-17 07:12) | operator-initiated | high |

Event sequence of one run (ids 6756–6758 / 1089–1091):

```
INFO  engine  開始調參:walk-forward champion/challenger…
WARN  tuner   AI 呼叫失敗(opus,rc=1):…            ← exactly one deep-model call per run; failure is non-fatal
INFO  tuner   調參採用新參數 v{new}:{reason}        ← adopted
   or         調參維持現任參數 v{active}:{reason}   ← rejected
```

The purpose of the `opus` call is unknown (it happens before the search; proposal in §8 Q6: an optional LLM-suggested candidate added to the pool, skipped on failure).

Quality-trigger numbers (10-30): `命中率 33%` matches the champion's 1-day forecasts over the **last 5 trading days** (45 forecasts, 15 hits with the `>=` rule; the 10-29 value was 51 %, no trigger) and also the 5-day horizon over the last 10 days. `MAE 惡化 155%` = recent MAE / reference − 1 ≈ 2.55×; no reference tried (overall MAE +22 %, previous 5 days +17 %, previous 60 days +23 %) reproduces it except "best weekly MAE in `series`" (week 09-21 h=1 `0.009738` → +153 %). Thresholds and reference are therefore **open** (§8 Q7).

### 3.2 Search space and candidates (**inferred**, medium)

| Aspect | Rule | Evidence |
|---|---|---|
| Tunable keys | `buy_th, strong_th, sell_th, strong_sell_th, weights{ma_align, ma_cross, rsi, macd, kd, bb, volume}` | these are the only keys that ever change between rows |
| Fixed keys | `fund_cap 1.5`, `use_market true`, `use_fundamentals true` | identical in 25/25 rows |
| `exit{stop_pct, trail_pct}` | tunable **until v4** (v2 `0.08/0.0`, v4 `0.0/0.0`), **frozen since v5** at `0.08/0.12` ("安全參數自此移出調參搜索空間(tuner SAFE_*),不再由任何回測決定") | rows 5–25 all `0.08/0.12`; the manual reason text |
| Perturbation style | one weight changed per candidate by a multiplier in `{0.5, 0.75, 1.25, 1.5}` (observed weight values 0.25 = 0.5×0.5, 0.625 = 1.25×0.5, 0.9375 = 1.25×0.75, 0.75, 1.25, 1.5); thresholds shifted together by ±0.5 as one coordinate (v2 `2.5/4.5/−2.5/−4.5` → v3 `3.0/5.0/−3.0/−5.0`) | from v6 on, **every** challenger (ids 7–25) differs from the incumbent in exactly one weight (`rsi 1.0→0.5`, `ma_align 1.0→1.5`, `bb 1.25→0.625`, `bb 0.625→0.9375`, `rsi 0.5→0.75`, `rsi 0.5→0.25`); earlier rows were wider: v6 changed `rsi/bb/volume` at once, ids 3–4 changed `rsi` and `stop_pct` together |
| Number of trials | `嘗試 {k} 組` with k ∈ {59, 60, 62, 63, 64}: 60 (ids 1–3), 64 (4), 63 (6, 9, 20, 21), 62 (7, 8, 18, 19, 22), 59 (10–17, 23–25) | the count varies with the incumbent → a generated/deduplicated set, max 64 |
| Selection | the row's `params_json` is the **challenger** (best candidate); `train_metric` its in-sample score, `valid_metric` its out-of-sample score, `champion_metric` the incumbent's out-of-sample score on the same window | rejected rows carry params ≠ incumbent (id 25: `rsi 0.25` while v9 has `rsi 0.5`); `valid == champion` exactly in 7 rows (16, 17, 18, 19, 23, 24, 25) = a candidate whose change does not alter any trade in the validation window |

### 3.3 Walk-forward evaluation

| Item | Observed | Confidence |
|---|---|---|
| Metric name | `calmar` for ids 1–6 (≤ 2026-07-18), `reward_points` from id 7 (2026-07-25) onward; the name is embedded in the reason text | high |
| `train_metric` range | calmar 1.67–2.38; reward_points 306–363 | high |
| `valid_metric` / `champion_metric` range | calmar 4.55–6.44; reward_points 808–1028 | high |
| Windows | train window precedes the validation window (walk-forward); the validation score is ~2.6–3.2× the train score for both metrics, so the windows differ in length or regime. Exact lengths **unknown** (§8 Q5) | low |
| Metric definition | `calmar` = annualised return / max drawdown of the backtest equity curve (standard). `reward_points` = the paper-trading reward scheme (§4) applied to the backtest — but 850 points ≠ 10 × a plausible window return, so the backtest scoring is finer-grained than monthly (§8 Q6) | low |
| Selection of the challenger | best candidate by `train_metric` (classic champion/challenger), then compared out of sample. Cannot be distinguished from "best by `valid_metric`" with the data; either produces the observed rows | low |

### 3.4 Adoption rule, versions, what a row records (**high**)

```
adopt  = valid_metric > champion_metric * 1.02            # "門檻 +2%"
```

Checked on all 24 automatic rows: adopted ratios 1.024 (id 12), 1.108, 1.024, 1.190, 1.040, 1.033, 1.056; rejected ratios ≤ 1.016 (id 20 `922.934/908.195`, id 21 1.0126, id 22 1.011); id 3 rejected with `6.430050574 < 6.430050586`.

| Row kind | `version` | `params_json` | `train/valid/champion_metric` | `adopted` | `reason` |
|---|---|---|---|---|---|
| adopted (auto) | **new** version = previous active + 1 (`v2…v9`, ids 1, 2, 4, 6, 10, 11, 12) | the challenger = new incumbent | floats | `1` | `樣本外 {metric} {valid:.3f} 勝過現任 {champ:.3f}(門檻 +2%,嘗試 {k} 組)` |
| rejected | the **currently active** version (ids 3 → v3, 7–9 → v6, 13–25 → v9) | the losing challenger | floats | `0` | `樣本外 {metric} {valid:.3f} 未勝過現任 {champ:.3f}(門檻 +2%,嘗試 {k} 組)` |
| manual | new version (id 5 → v5) | the adopted params | `null`, `null`, `null` | `1` | free text, e.g. `手動採用:恢復六月回測驗證的出場保護(停損 8%/移動停利 12%)。安全參數自此移出調參搜索空間(tuner SAFE_*),不再由任何回測決定——v4 於 7/17 崩盤日無停損的教訓。` |

`active_version` = `version` of the newest `adopted = 1` row = `data.json.engine.params_version` (9 in Oct, 8 in Aug). `id` is an autoincrement; the file lists rows **newest first** (all rows, no window: 25 in Oct, 11 in Aug). `adopted_at` is the run's completion time (the result event is logged in the same second: id 25 `10:00:31` ↔ event 6758 `10:00:31`). Numbers in `reason` use `%.3f` (`852.571`, `5.419`); `k` is an integer.

### 3.5 `params_json` serialisation (**high**)

A JSON **string** produced by `json.dumps(params)` with default separators (`", "`, `": "`), `ensure_ascii` irrelevant (ASCII only), floats in Python repr (`3.0`, `0.625`, `-5.0`), booleans `true/false`. Key order is fixed by construction:

```
{"buy_th": 3.0, "strong_th": 5.0, "sell_th": -3.0, "strong_sell_th": -5.0,
 "weights": {"ma_align": 1.5, "ma_cross": 1.0, "rsi": 0.5, "macd": 1.0, "kd": 0.5, "bb": 0.625, "volume": 1.5},
 "fund_cap": 1.5, "use_market": true, "use_fundamentals": true,
 "exit": {"stop_pct": 0.08, "trail_pct": 0.12}}
```

(shown wrapped; the stored string is one line). `json.dumps(json.loads(s)) == s` holds for all 25 rows. Relationship to the shadow genes: `strong_th = buy_th + strong_gap`, `strong_sell_th = sell_th − strong_gap` (`strong_gap = 2.0`), `weights.X = w_X`.

### 3.6 Proposed record for **v10** (manual adoption of shadow arm B `risk-exit-consensus`)

Insert one row (becomes `params_history[0]`), set `active_version = 10`, `engine.params_version = 10`, log the event, seal the shadow verdict as in 03 §4.5:

```
id            = 26
adopted_at    = "<cut-over time, e.g. 2026-11-01T09:00:00+08:00>"
version       = 10
adopted       = 1
train_metric  = null, valid_metric = null, champion_metric = null
reason        = "手動採用:影子對照 55 個交易日(2026-08-07~2026-10-29)B 臂 risk-exit-consensus 報酬 +13.21% 對 A 臂 +3.29%(差 +9.92pp),最大回撤 3.99% 對 5.88%,四項裁決全數通過,提前結案採用 B 臂基因。出場保護改為停損 8.30%/移動停利 20.61%(影子驗證值);安全參數仍不進入調參搜索空間。"
params_json   = {"buy_th": 3.0, "strong_th": 5.0, "sell_th": -3.0, "strong_sell_th": -5.0, "weights": {"ma_align": 1.8490543082236912, "ma_cross": 0.45138791133375156, "rsi": 0.7840884945834798, "macd": 1.2517538359316402, "kd": 0.24447732513006493, "bb": 1.2827766433755723, "volume": 1.4532856064819977}, "fund_cap": 1.5, "use_market": true, "use_fundamentals": true, "exit": {"stop_pct": 0.08300581937609232, "trail_pct": 0.206062542287206}}
event         = {"level": "INFO", "source": "tuner", "message": "調參採用新參數 v10:" + reason}
```

Numbers in the reason come from `shadow.json` (`legs.return.ret_b 0.132083 / ret_a 0.032851 / diff 0.099232`, `legs.safety.mdd_b 0.0399 / mdd_a 0.0588`, `progress.n_days 55`, `rows[0].date 2026-08-07`, `rows[-1].date 2026-10-29`). The viewer will render the row as `v10 ●`, `是`, `— — —`, the reason, and the summary `buy_th=3 停損8% 移停21%` (`Math.round(0.2061×100) = 21`). Two policy points need the owner's decision before this is written (§8 Q18): whether the SAFE_* exit values follow arm B (`0.0830/0.2061`, as the text above assumes) or stay at `0.08/0.12`, and where the four B genes that have no slot in `params_json` (`risk_frac 0.008025956907855073`, `strong_mult 1.487336088988674`, `caution_scale 0.5500015169427086`, `persistence 2.0`) are persisted — proposal: add them as a new top-level key `"sizing": {...}` appended **after** `"exit"` so existing keys keep their order.

---

## 4. Monthly reward points (`Reward 記分板`)

### 4.1 Month states and enumeration (**high** on shapes, **medium** on enumeration)

`overview.reward = {total, provisional, history[]}`; `history` is **newest first** and covers every calendar month from the first month that has any equity record (June 2026 — the pre-launch backtests) up to the month before the current one. Each month is one of:

| State | Shape | When |
|---|---|---|
| settled | `{month, equity_open, equity_close, partial:false, ret_pct, twii_ret_pct, base_points, beat_market, bonus_beat, new_high, bonus_high, points, total_after}` | both benchmarks exist (`2026-08`, `2026-09`) |
| settled, partial | same with `partial: true` | the month-end equity exists but the engine did not run at the start of the month: `equity_open` = the first equity the engine recorded = `initial_cash` 1 000 000 (`2026-07`, engine started 07-09; no trades → `equity_close 1000000.0`, `points 0`) |
| skipped | `{month, skipped: true, reason: "缺月初或月底權益基準(該月系統未完整運行)"}` | neither benchmark (`2026-06`) |
| provisional (current month) | `reward.provisional = {month, ret_pct, points, settled: false}` | always present while the engine runs; `null` only before the first EOD |

Settlement happens once, after the last EOD of the month; the Aug-15 bake already shows July settled and August provisional. Order of keys exactly as listed (01 §8 has the per-field rendering).

### 4.2 Formulas (all four observed months/provisionals fit exactly)

```
equity_open(M)   = equity_close(M-1)                          # Sep: 1015475.4 = Aug close
                   or first recorded EOD equity if M-1 has no close  (partial)
equity_close(M)  = account.equity at the last EOD of M       # 1040392.13
ret_frac         = equity_close / equity_open - 1
ret_pct          = round(ret_frac * 100, 2)                   # 2.45, 1.55, 0.0
base_points      = int(round(ret_frac * 1000))                # 1 point per 0.1 % — from the UNROUNDED return
bonus_high       = 10 if new_high else 0
bonus_beat       = B if beat_market else 0                    # B never observed (always 0, beat_market always false)
points           = base_points + bonus_beat + bonus_high
total_after(M)   = total_after(M-1) + points                  # 0 → 25 → 60
reward.total     = total_after of the newest settled month    # 60
provisional      = {"month": current, "ret_pct": round((equity_now / equity_close(M-1) - 1) * 100, 2),
                    "points": int(round((equity_now / equity_close(M-1) - 1) * 1000)), "settled": false}
```

Rounding evidence (the only variant that fits all four):

| Month | `equity_open → close` | unrounded ret % | `ret_pct` | `round(ret_frac×1000)` | `round(ret_pct×10)` (Python) | file `base_points`/`points` |
|---|---|---|---|---|---|---|
| 2026-09 | 1 015 475.40 → 1 040 392.13 | 2.4537 | 2.45 | **25** | 24 (banker's) | 25 |
| 2026-08 | 1 000 000.00 → 1 015 475.40 | 1.5475 | 1.55 | **15** | 16 | 15 |
| 2026-10 prov. (Oct bake) | 1 040 392.13 → 1 010 098.05 | −2.9118 | −2.91 | **−29** | −29 | −29 |
| 2026-08 prov. (Aug bake) | 1 000 000.00 → 1 008 754.09 | 0.8754 | 0.88 | **9** | 9 | 9 |

`new_high`: `true` for Aug (1 015 475 > 1 000 000) and Sep (> 1 015 475), `false` for July (equal, not greater) → **inferred** `equity_close > max(initial_cash, all earlier month-end equities)` (strict). `beat_market`: `false` in all three months including July (`0.0` vs TWII `−6.52`), so it is not plain `ret_pct > twii_ret_pct`; **inferred** `(ret_pct > twii_ret_pct) and not partial` (medium). `twii_ret_pct` (`3.93`, `6.98`, `−6.52`) is the TAIEX month-over-month return, 2 dp; source/exact endpoints unverifiable here (§8 Q10). The AI report also mentions a `目標線 5%/月,僅作對照` — a comparison line only, not part of the scoring.

### 4.3 Monthly numbers also fed to the AI report

The 10-12 report says `月度記分板:本月起點 1,043,324 → 目前 1,058,195,月至今 +1.43%` — a different anchor (the equity at the first EOD of October) than `provisional` uses (`equity_close(Sep) = 1 040 392.13`, which reproduces `−2.91` exactly). Keep the two anchors separate.

---

## 5. Event log (`運作日誌`)

### 5.1 Record and file rules (**high**; shape detail in 03 §2)

| Rule | Evidence |
|---|---|
| Row: `{id, ts, level, source, message}`; `id` global autoincrement never reset (Aug window 995–1094, Oct 6663–6762; ≈74 events/day); `ts` second precision Taipei; `message` single line | 200 rows |
| `level` ∈ `INFO`, `WARN` (`ERROR` never observed in 200 rows; the viewer styles it red/bold if it appears) | counts below |
| `source` ∈ `engine`, `news`, `ai`, `tuner`, `broker`, `heartbeat`, `data` | counts below |
| File = the **last 100 rows ascending by id**, `last_id = max(id)`; written at every bake, last row = the AI-daily-report failure logged in the bake's second | both |
| ids are monotonic with `ts`; several events share a second in execution order | 0 inversions in 200 rows |

Counts per (level, source): Oct — INFO/engine 35, WARN/news 33, WARN/ai 15, WARN/engine 9, INFO/heartbeat 3, INFO/broker 2, INFO/tuner 1, WARN/tuner 1, WARN/data 1. Aug — WARN/news 39, WARN/ai 30, INFO/engine 18, WARN/engine 8, INFO/broker 2, INFO/tuner 1, WARN/tuner 1, WARN/data 1 (no `heartbeat` yet — added with `engine.health` in September).

### 5.2 Message catalogue (verbatim templates; `{…}` placeholders; count = occurrences in Oct + Aug windows)

**`engine` / `INFO`**

| # | Template | Example | Emitted by |
|---|---|---|---|
| 24 | `{code} {name}:{old}→{new}` with old/new ∈ `觀望`,`買進`,`強力買進`,`賣出`,`強力賣出` | `2317 鴻海:觀望→強力買進` | every scan (incl. the `啟動` scan after a restart) when a symbol's recommendation changes |
| 4 | `{code} {name} 消息面偏空 {score:+.1f}({n} 則)` (`消息面偏多` for a positive tilt — unobserved) | `2330 台積電 消息面偏空 -1.2(8 則)` | news refresh when the aggregated sentiment tilts |
| 3 | `晨會:夜盤 {pct}、TSM {pct}、費半 {pct};近 {d} 日事件 {k} 筆、宏觀新聞 {m} 則;{無覆蓋\|風險覆蓋 caution}`; `夜盤 無資料` when the night session is missing; pct formatted `+0.8%`/`-1.4%` | `晨會:夜盤 -1.4%、TSM -1.8%、費半 -1.4%;近 3 日事件 1 筆、宏觀新聞 15 則;風險覆蓋 caution` | pre-market briefing (08:30 on a normal day; later after a late start) |
| 3 | `閘門攔截 {code} 買進:G3:市場 caution(晨會覆蓋:隔夜情勢(caution)),禁加碼` | as shown | buy blocked by the market-regime gate |
| 2 | `閘門攔截 {code} 買進:G4:{date} 收盤評分 {s:+.1f} 未達 buy_th {th:+.1f},訊號未跨日持續` | `閘門攔截 6789 買進:G4:2026-08-13 收盤評分 -0.6 未達 buy_th +3.0,訊號未跨日持續` | buy blocked by the persistence gate (G1 exists per the weekly review; its text is unobserved) |
| 1 | `自動換股:賣出 {code} {name}(評分 {s:+.1f})讓位給 {code} {name}(評分 {s:+.1f})` | `自動換股:賣出 0050 元大台灣50(評分 -2.0)讓位給 2317 鴻海(評分 +3.0)` | rotation |
| 2 | `收盤定盤掃描完成:{n} 檔以收盤世界重新定價(其中 {k} 檔取得交易所定盤價);14:15 EOD 會再以完整日K做最終校正。` | with 9/9 | 13:33 closing-fix scan |
| 1 | `市場狀態:halt(大盤單日 {pct}、5日 {pct})` (other states unobserved) | `市場狀態:halt(大盤單日 -2.5%、5日 -3.6%)` | EOD market-regime change |
| 6 | `EOD 完成:更新 {n} 檔資料,記錄 {p} 筆預測,兌現 {r} 筆。` | `EOD 完成:更新 9 檔資料,記錄 54 筆預測,兌現 54 筆。` | end of EOD (§2.2 for p/r) |
| 4 | `行事曆同步:TWSE 除權息 {n} 筆` | `行事曆同步:TWSE 除權息 3 筆` | after EOD |
| 3 | `開始調參:walk-forward champion/challenger…` | as shown | tuner start (§3.1) |

**`engine` / `WARN`**

| # | Template | Example |
|---|---|---|
| 16 | `{code} 未來 30 天無任何行事曆事件記錄——法說會/除權息可能未收錄` (one per symbol with an empty 30-day calendar, right after `行事曆同步`) | `0050 未來 30 天無任何行事曆事件記錄——法說會/除權息可能未收錄` |
| 1 | `偵測到預測品質下降(命中率 {p}%,MAE 惡化 {q}%),自動觸發調參` (integers) | `偵測到預測品質下降(命中率 33%,MAE 惡化 155%),自動觸發調參` |

**`broker` / `INFO`** (same second as the order row in `orders.json`)

| Template |
|---|
| `紙上買單成交:{code} {name} {qty} 股 @ {price:.2f},手續費 {fee} 元,總支出 {gross+fee:,} 元。` |
| `紙上賣單成交:{code} {name} {qty} 股 @ {price:.2f},手續費 {fee} 元,證交稅 {tax} 元,已實現損益 {pnl:+,} 元。` |

`qty` without thousands separator (`1571 股`), money totals with (`47,446`, `-3,665`), fee/tax plain integers.

**`tuner`** — `INFO`: `調參採用新參數 v{n}:{reason}` / `調參維持現任參數 v{n}:{reason}` (§3.4); `WARN`: the AI failure line below.

**`heartbeat` / `INFO`** — `心跳已送(FAIL:{red joined})`, e.g. `心跳已送(FAIL:AI 日報 19 天未產生)` (§6.2). OK form unobserved.

**`data` / `WARN`** — `{symbol} 本次最新日期 {new_last} 落後快取 {cache_last}(疑似劣化回應),保留舊快取` with the Yahoo ticker (`0050.TW`) (§7.1).

**`news` / `ai` / `tuner` / `WARN` — AI CLI failures**

| Template | Notes |
|---|---|
| `AI 呼叫失敗({model},rc={rc}):{stderr}` | `model` = `sonnet` (source `news`) or `opus` (sources `ai`, `tuner`); `stderr` = last line of the CLI's stderr, may be empty (Aug rows end with `:`); Oct: `Failed to authenticate: OAuth session expired and could not be refreshed` |
| `AI 連續失敗 {n} 次,暫停 AI 呼叫 {m} 分鐘(期間自動改用非 AI 路徑)` | always `3` / `15`; logged **in place of** the third failure line (§5.4) |

### 5.3 Daily ordering (trading day, from the two windows)

```
08:30  [engine] 晨會:…                               (pre-market briefing; 09:30 data refresh may add [data] WARN)
09:00– every 5 min: scan → recommendation changes, 消息面 lines, 閘門攔截, broker fills, 自動換股; AI calls as the breaker allows
13:33  [engine] 收盤定盤掃描完成:…
14:15  [engine] 市場狀態:…(if changed) → [heartbeat] 心跳已送(…) → [engine] EOD 完成:… → [engine] 行事曆同步:… → per-symbol calendar WARNs
       → (optional) [engine] WARN 偵測到預測品質下降… + 開始調參… → tuner events
       → AI daily report attempt ([ai] AI 呼叫失敗… on failure) → bake (data.json ts = this second)
Sat    09:30 data refresh ([data] WARN if degraded) → 10:00 tuner → 14:15 EOD (記錄 0) → heartbeat/bake as above
```

### 5.4 AI circuit breaker (**high**)

| Rule | Evidence |
|---|---|
| One **global** consecutive-failure counter across all callers (`news`/`ai`/`tuner`) | 10-31: `09:30:19 [ai] 失敗` → `10:00:17 [tuner] 失敗` → `10:00:32 [ai] AI 連續失敗 3 次` — three sources, 30 min apart, one counter |
| On the **3rd** consecutive failure the caller logs `AI 連續失敗 3 次,暫停 AI 呼叫 15 分鐘(期間自動改用非 AI 路徑)` (WARN, that caller's source) **instead of** a third `AI 呼叫失敗` line, and opens the breaker for 15 minutes | every burst is `失敗, 失敗, 連續失敗` (2 + 1 lines, 1–3 s apart) |
| While open, AI calls are skipped silently and the non-AI path is used (rule-based news sentiment, no AI note) | no events inside the 15-min gaps |
| When the window ends the counter is reset; the next call that fails starts a new `失敗, 失敗, 連續失敗` burst | bursts recur every ~15 min 20 s (11:42:40 → 11:57:41 → 12:12:54 …), alternating `news`/`ai` |
| A successful call resets the counter (unobserved but implied) | — |
| A burst = up to 3 attempts of one logical call within seconds (retry loop), each failure counted | timing |

---

## 6. Engine health and heartbeat (`overview.engine.health`)

### 6.1 Fields (Oct only; key order as emitted)

| Field | Type | Oct value | Formula (**inferred** unless noted) | Confidence |
|---|---|---|---|---|
| `configured` | bool | `true` | `HEARTBEAT_URL` env/config is set (viewer tooltip: `HEARTBEAT_URL 未設定:主機失聯時沒有人會收到通知`) | high |
| `share_days` | int | `1` | calendar days from the last successful **family-page publish** (`simple.html` + this repo push; the Saturday bake's `simple.html` says `產生時間 2026-10-31 14:15`) to `checked_at`'s date, evaluated **before** the current publish (Sat → Fri = 1) | medium |
| `ai_days` | int | `19` | `(checked_at.date − ai_last_success.date).days` = 10-12 → 10-31 = 19; 17 on 10-29, 18 on 10-30 (heartbeat events) | high |
| `share_enabled` | bool | `true` | publishing is switched on | high |
| `ai_enabled` | bool | `true` | = `engine.ai.enabled` | high |
| `ai_last_success` | iso | `2026-10-12T14:18:21+08:00` | **start time** of the last successful CLI call of any kind: on 10-12 the daily report finished `14:16:54`, then the nine per-symbol notes ran in `rows[]` order; `3481`'s note completed `14:18:21` and `2881`'s call (the last, note `ts 14:18:36`) started that second. Consistent with `ai_last_error.ts` also being a start time (`14:15:21`, event logged `14:15:22`) | medium |
| `ai_last_error` | object \| null | `{"ts": "2026-10-31T14:15:21+08:00", "model": "opus", "rc": 1, "error": "Failed to authenticate: OAuth session expired and could not be refreshed"}` | last failed CLI call: start time, model alias, return code, stderr tail (same text as the event, which is logged one second later) | high |
| `ai_hard_failure` | bool | `false` | not set by 19 days of `rc=1`; **proposal**: `true` only when the CLI cannot be executed at all (missing binary / timeout) | low |
| `red` | string[] | `["AI 日報 19 天未產生"]` | red lights; template `AI 日報 {ai_days} 天未產生`; the family-page counterpart is unobserved (`share_days` 1 was not red) | high (template) / low (thresholds) |
| `checked_at` | iso | `2026-10-31T14:15:22+08:00` | time of the check = bake time | high |

Proposed thresholds (§8 Q12/13): `ai_days > 3` and `share_days > 3` (tolerates a weekend), red strings `AI 日報 {n} 天未產生` and `家用快照 {n} 天未更新`.

### 6.2 Heartbeat protocol (**medium**; healthchecks-style)

```
if not configured: skip, no event
red = compute_red()
if red:  POST/GET  HEARTBEAT_URL + "/fail"   body = "、".join(red)      → event INFO heartbeat 心跳已送(FAIL:{"、".join(red)})
else:    POST/GET  HEARTBEAT_URL             → event INFO heartbeat 心跳已送(OK)          (OK text unobserved — proposal)
```

Sent once per EOD (trading days **and** Saturday), immediately before `EOD 完成` (14:15:21 ↔ 14:15:21). The viewer tooltip states the semantics: `監控紅燈:每日 EOD 會把它送到外部心跳的 /fail 端點`. The separator for multiple red strings is unobserved (`、` proposed).

### 6.3 Order of the EOD health steps (from timestamps 10-31)

1. `14:15:21` AI daily-report call starts and fails (`ai_last_error.ts`), 2. health computed (`ai_days` 19, `red`), 3. heartbeat sent and logged (`14:15:21`), 4. `EOD 完成` logged (`14:15:21`), 5. the failure event logged (`14:15:22`), 6. `checked_at`/bake at `14:15:22`. Any order that yields the same values is acceptable, but `checked_at` must equal `data.json.overview.ts`.

---

## 7. Data freshness

### 7.1 Degraded-response guard on the daily-bar fetch (**high** on the rule, event text verbatim)

Each refresh fetches the full history (250 bars) for a symbol and compares the **last bar date** with the cached file:

| `new_last` vs `cache_last` | Action | Event |
|---|---|---|
| `>` (newer) | replace cache, mark symbol updated (record + resolve, §2) | none |
| `==` | replace cache (values may be revised — this is how the Saturday 10-31 re-resolution of 6 rows occurred); no new made_date | none |
| `<` (older) | **reject**, keep cache | `WARN data`: `{symbol} 本次最新日期 {new_last} 落後快取 {cache_last}(疑似劣化回應),保留舊快取` |
| fetch error / empty | keep cache | (unobserved — propose the same WARN wording with `無資料` in place of the date) |

Both observed occurrences are `0050.TW` on a Saturday 09:30 refresh (`09:30:15`, `09:30:25`), returning data one day behind the cache (Yahoo serving a stale snapshot). Only `0050.TW` ever triggered it, and 0050 is also the symbol behind the `兌現 48` incident (§2.2).

### 7.2 `rows[].quote_fresh` (**low**)

`false` on both Saturday bakes with `rows[].ts == engine.last_scan` (Friday 18:17 / 20:50, after the close). Viewer: when `false` it appends `延` with tooltip `延遲價(非交易所即時報價),擷取 HH:MM`. **Proposal**: `quote_fresh = market.is_open and (now − quote_ts) ≤ 20 min` (the disclaimer says Yahoo may be delayed 15–20 minutes); otherwise `false` with `ts` = time of the scan that produced the price.

### 7.3 Decision table for an EOD run (rebuild)

| Condition | Record | Resolve | Heartbeat | Bake |
|---|---|---|---|---|
| trading day, all 9 symbols have today's bar | 54 | all pending with target ≤ latest bar (normally 54) | yes | yes |
| trading day, symbol X stale (no bar for today) | 48 (skip X) and `data` WARN if the fetch regressed | pending for the other 8 | yes | yes |
| non-trading day (Sat; GitHub Actions should also cover holidays) | 0 | whatever became resolvable (normally 0) | yes | yes |
| fetch failed for all symbols | 0 | 0 | yes, with a red `資料更新失敗` (proposal) | yes (unchanged data, new `ts`) |

---

## 8. Open questions (with proposed defaults)

| # | Question | Evidence gap | Proposed default |
|---|---|---|---|
| Q1 | `ridge` internals (features, window, α, error scale `s_h`) | only outputs survive (§1.3) | ridge regression per symbol per horizon on the last 250 bars with features {1-, 5-, 20-day returns, RSI14, MACD hist, KD, BB %b, 20-day volume ratio}, target = forward h-day simple return, `α = 1.0`, `s_h` = residual std; `prob_up = Φ(pred/s_h)`; name must stay `"ridge"` |
| Q2 | "sample sufficient" threshold for the champion | Aug h=20 decided at `n=38` | `n ≥ 30`, else `baseline` |
| Q3 | which model fills `symbol.forecast` | Aug: all `ridge` while only h=5 champion was ridge | use `champion["5"]` for all three horizons (§1.1) |
| Q4 | candidate generator of the tuner | `k` ∈ 59–64 | 64 random single-coordinate perturbations (weights × {0.5, 0.75, 1.25, 1.5}; thresholds ±0.5, keeping `strong = buy + 2`, `sell = −buy`), seeded by run date, deduplicated → 59–64 |
| Q5 | walk-forward windows | valid/train ≈ 3× | train = bars −250…−61, valid = last 60 bars (both shared by champion and challengers) |
| Q6 | `reward_points` backtest metric and the tuner's `opus` call | magnitudes 300/850; one AI call per run | points = Σ over backtest days of `round(daily_ret × 1000)` + 10 per new equity high; the AI call (if it succeeds) returns one extra candidate param set |
| Q7 | quality-trigger thresholds/reference | 33 % reproduced, 155 % not | after each trading-day EOD: `hit5 < 0.40 and mae5/mae_ref > 1.5` where `hit5/mae5` = champion 1-day forecasts over the last 5 trading days and `mae_ref` = trailing-60-day MAE; message as §5.2 |
| Q8 | `bonus_beat` value and `beat_market` rule | never true | `bonus_beat = 10`; `beat_market = ret_pct > twii_ret_pct and not partial` |
| Q9 | `new_high` definition | 3 months | `equity_close > max(initial_cash, previous month-end closes)` |
| Q10 | `twii_ret_pct` source | values only | `^TWII` close on the last trading day of M vs M−1 via yfinance; for a partial month use the first day the engine ran |
| Q11 | settlement moment | Aug-15 bake shows July settled | settle month M during the first EOD run dated in M+1 (before computing the new provisional) |
| Q12 | heartbeat OK text and separator | unobserved | `心跳已送(OK)`; `、` |
| Q13 | red thresholds and the family-page red string | `ai_days` 17 was red, `share_days` 1 was not | `ai_days > 3` → `AI 日報 {n} 天未產生`; `share_days > 3` → `家用快照 {n} 天未更新` |
| Q14 | `ai_hard_failure` | false after 19 days of rc=1 | true only when the CLI cannot start |
| Q15 | `quote_fresh` | always false in the two bakes | §7.2 |
| Q16 | orphaned forecasts / Saturday `兌現 6` | §2.2 | resolve all pending with an existing target bar; counts in the same message |
| Q17 | EOD on non-trading days | engine ran Saturdays | GitHub Actions runs daily 14:15 Taipei (Mon–Sat); on non-trading days record 0, still heartbeat and bake |
| Q18 | v10: SAFE_* exits from arm B or kept 0.08/0.12; storage of `risk_frac/strong_mult/caution_scale/persistence` | policy conflict with the v5 note | take arm B's values (the shadow safety leg passed) and add a `"sizing"` key after `"exit"`; otherwise keep `0.08/0.12` and change the reason text accordingly |
| Q19 | gates G1/G2 message texts; `消息面偏多` wording; `市場狀態` other than `halt` | unobserved | mirror the observed patterns: `閘門攔截 {code} 買進:G1:…`, `消息面偏多 {score}({n} 則)`, `市場狀態:{state}(大盤單日 {pct}、5日 {pct})` |
| Q20 | ledger row with `n = 0` (new symbol) | unobserved | omit the row from `by_horizon`/`by_model_horizon` |
