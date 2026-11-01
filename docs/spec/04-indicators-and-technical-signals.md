# 04 — Indicators and technical signals (`symbol/<code>.json → indicators{}`, `signals[]`, `data.json → rows[].tech_total`)

Status: reverse-engineered by **recomputing** every indicator from the baked `bars[]` of all nine `symbol/*.json` files (snapshot 2026-10-31 14:15 Taipei) and comparing against the published `indicators{}` arrays, then collecting every `signals[]` item and cross-checking `rows[].tech_total` against the weights in `model-health.json`. This document is the normative definition for the rebuilt engine; it refines and, where stated, supersedes §4–§5 of `docs/spec/02-symbol-json-contract.md`.

Evidence base (all read-only): `symbol/{0050,2308,2317,2330,2454,2881,2882,3481,6789}.json` (250 bars + 11×250 indicator floats each), `data.json → overview.rows[]`, `model-health.json → params_history[]`, `shadow.json → genes[]`, `events.json`, `app.js`, and the AI prose in `data.json → ai_report` / `rows[].ai_note` (dated 2026-10-12, used only as weak corroboration for labels that do not occur in the 2026-10-30 snapshot).

Confidence legend: **high** = exact numeric reproduction on all 9 files (or read from code); **medium** = consistent with all data but not uniquely determined; **low** = inferred by symmetry / prose only.

Analysis scripts used (throwaway, not part of the repo): `/tmp/claude-0/-home-user-tw-quant-view/f8621ae4-2ceb-5122-afe3-19497387358e/scratchpad/{recompute.py,macd_seed.py,volume_grid.py,decay_fmt.py}`, run with `python3 -I` (pandas 2.x / numpy).

---

## 1. Inputs

### 1.1 `bars[]` column layout (**high**)

Each `bars[i]` is `[date, open, high, low, close, volume]`:

| idx | field | type | verification |
|---|---|---|---|
| 0 | `date` | `"YYYY-MM-DD"` | strictly increasing, 250 rows, window `2025-10-17 … 2026-10-30` in all 9 files |
| 1 | `open` | float (adjusted) | `high ≥ max(open, close)` and `low ≤ min(open, close)` hold for all 2 250 rows |
| 2 | `high` | float | |
| 3 | `low` | float | |
| 4 | `close` | float (adjusted) | `bars[-1][4]` is byte-identical to `data.json → rows[].price` for all 9 symbols (`2370.0`, `104.94999694824219`, `42.54999923706055`, …); `rows[].pct == round((bars[-1][4]/bars[-2][4]-1)*100, 2)` |
| 5 | `volume` | **int, shares** | the only integer column; e.g. 0050 `226322152`, 2330 `29664858`, 6789 `1104170` |

All indicators below are computed on the **adjusted** series exactly as stored in `bars[]` (`close` for MA/BB/RSI/MACD; `high`/`low`/`close` for KD; `volume` for the volume signal).

### 1.2 History length and alignment (**high**)

* `indicators.X[i]` belongs to `bars[i]`. All 11 arrays have exactly 250 finite floats; **no `null`, no `NaN`, no shorter-window fallback at the head**.
* The head of the window is **not** a warm-up: it is the continuation of a longer history that the engine computed on and then sliced. Evidence (see §2 per indicator): `ma60[0]` ≠ `close[0]` and ≠ any `min_periods=1` mean (max err 1.1–244 depending on price level); `rsi[0..13]` are populated and differ from a `min_periods=1` recomputation by 28–93 points; `k[8]` ≠ `rsv[8]` (e.g. 2308: `rsv[8]=24.24`, published `k[8]=59.37`); the back-solved EMA states before `bars[0]` are plausible prices (2330: EMA12 = 1389.49, EMA26 = 1326.02 while `close[0]` = 1432.43).
* **Rule for the rebuild:** compute every indicator over the full cached history (≥ 250 bars *before* the published window; see §2.7 for the decay math), then emit `[-250:]` of each array. Never serialise `NaN` (invalid JSON; the viewer's `res.json()` would throw).

---

## 2. Indicator definitions (recomputed)

Summary — the parameterisation that reproduces the published arrays. "Aligned region" = indices from which a window-only recomputation can be compared (`n-1` for rolling windows); for recursive indicators the comparison is done either on the tail (after the window-start transient has decayed) or by seeding the recursion from published values.

| key | definition that matches | parameters tested | max abs error (all 9 files) | rejected alternatives (max err) | confidence |
|---|---|---|---|---|---|
| `ma5` / `ma20` / `ma60` | `close.rolling(n).mean()` | n = 5 / 20 / 60 | **0.0** on `[n-1:]` | `min_periods=1` at the head: 0.2–244 | **high** |
| `bb_up` / `bb_low` | `ma20 ± 2.0 × close.rolling(20).std(ddof=1)` (sample std) | 20 / 2.0 / ddof 0 vs 1 | **≤ 1.7e-11** on `[19:]` | ddof=0 (population): 0.30 (0050) … 34.8 (2454) | **high** |
| `rsi` | **Cutler / SMA RSI(14)**: `100 − 100/(1 + SMA14(gain)/SMA14(loss))` | 14 vs 6; SMA vs Wilder vs ewm(adjust=True) | **0.0** on `[14:]` (whole window, 9/9) | Wilder-14 (tail-60): 12.8–24.5; ewm(com=13, adjust=True): same as Wilder; period 6 (any smoothing): 17.7–64.5 | **high** |
| `macd` | `EMA12(close) − EMA26(close)`, `ewm(span, adjust=False)` (α = 2/13, 2/27) | 12/26; adjust False vs True | **≤ 1.5e-12** once the two pre-window EMA states are back-solved (§2.4); window-only recomputation: 1.5e-10 … 4.7e-7 at `i=249` (pure truncation) | adjust=True, window-only: 10–20× larger residual at `[200:]` (e.g. 2330 2.0e-4 vs 2.0e-5) and does not satisfy the exact recursion | **high** |
| `macd_sig` | `EMA9(macd)`, `ewm(span=9, adjust=False)` (α = 0.2) | 9 | **0.0**: `sig[i] == 0.8·sig[i-1] + 0.2·macd[i]` holds exactly for all 249 steps in all 9 files | adjust=True: does not satisfy the recursion | **high** |
| `macd_hist` | `macd − macd_sig` (**not** ×2) | — | **0.0** (9/9) | `2·(macd−sig)`: 1.3–144 | **high** |
| `k` | Taiwan KD(9,3,3): `rsv = (close − L9)/(H9 − L9)·100`, `k[i] = ⅔·k[i-1] + ⅓·rsv[i]` | n = 9 vs 14; EMA(α=⅓) vs SMA(3); seed 50 vs first-RSV | **≤ 2.8e-14** (recursion seeded from published `k[7]`, checked on `[8:]`; tail-100 window-only: 0.0 … 2.8e-14 for either seed) | n=14: 21.8–35.4; SMA(3) stochastic: 15.7–24.4 | **high** |
| `d` | `d[i] = ⅔·d[i-1] + ⅓·k[i]` | same | **≤ 4.3e-14** | — | **high** |

`H9 = high.rolling(9).max()`, `L9 = low.rolling(9).min()` (bar highs/lows, not closes).

### 2.1 Moving averages

`ma5[i] = mean(close[i-4..i])`, `ma20`, `ma60` likewise. Exact (error 0.0) from index `n-1` on in all nine files. Published `ma60[0]` is populated (0050: 53.7815 vs `close[0]` 60.8163; 2308: 749.51 vs 993.80), proving ≥ 59 bars of history before the window. `(bb_up + bb_low)/2 == ma20` to 5e-13 — the Bollinger mid-line is the same `ma20` series.

### 2.2 Bollinger bands

`bb_up = ma20 + 2.0·σ`, `bb_low = ma20 − 2.0·σ` with `σ = close.rolling(20).std(ddof=1)` (sample std, pandas default). Errors with ddof=1: 5.7e-14 (3481) … 1.7e-11 (2330). With ddof=0 the error is 0.30 (0050), 1.07 (2317), 7.0 (2330), 11.9 (2308), 34.8 (2454) — unambiguous. Only the 2.0 multiplier was needed; no other multiplier fits.

### 2.3 RSI

Definition (exact on every index ≥ 14 of every file):

```
d      = close.diff()
gain   = max(d, 0)          loss = max(−d, 0)
rsi[i] = 100 − 100 / (1 + mean(gain[i-13..i]) / mean(loss[i-13..i]))
```

* Period 14 with **simple** 14-day means (Cutler's RSI). Wilder smoothing (α = 1/14, SMA-seeded or not) is off by 12.8–24.5 points on the last 60 bars; period 6 is off by 18–65 points. (**high**)
* Edge cases: `rsi == 50.0` exactly when mean gain == mean loss (observed, e.g. 2454 `rsi[0] = 50.0`); no 0/100 values occur in the window. The rebuild must guard `loss_mean == 0 → 100.0` and `gain_mean == loss_mean == 0 → 50.0` (proposed default; not observed — see Open questions).
* Values are emitted unrounded (full `repr`, e.g. `59.375`, `16.923076923076923`).

### 2.4 MACD

`macd = EMA12(close) − EMA26(close)`, `macd_sig = EMA9(macd)`, `macd_hist = macd − macd_sig`, all EMAs recursive (`adjust=False`): `EMA[i] = EMA[i-1] + α·(x[i] − EMA[i-1])`, α = 2/(span+1).

Proof that the recursion (and only this recursion) is used:

* **Signal line:** the published arrays satisfy `macd_sig[i] = 0.8·macd_sig[i-1] + 0.2·macd[i]` with max error **0.0** over all 249 steps of all 9 files.
* **DIF:** treating the two EMA states immediately before `bars[0]` as unknowns and solving the 250 linear equations `macd[i] = (s12·(11/13)^(i+1) + P12[i]) − (s26·(25/27)^(i+1) + P26[i])` by least squares gives residuals of 2.2e-14 … 1.5e-12 (`P` = window-only partial EMAs). The solved states are plausible prices (0050: 59.30/57.33 vs `close[0]` 60.82; 6789: 263.90/270.90 vs 246.12 — the stock had been falling). With `adjust=True` the equations are not satisfied.
* A window-only recomputation (`close.ewm(span, adjust=False)` on the 250 bars, seeded with `close[0]`) shows pure transient decay, e.g. 2330: `|err| = 62 (i=0), 14 (i=25), 2.1 (i=50), 4.5e-2 (i=100), 9.5e-4 (i=150), 2.0e-5 (i=200), 4.7e-7 (i=249)`; 2882: `0.31 → 1.5e-10`. This is the (25/27)^i decay of the EMA26 seed difference, i.e. the engine's history started well before the window.
* `macd_hist` is the plain difference (max err 0.0); the Taiwanese "×2 OSC" convention is **not** used (err 1.3–144).

### 2.5 KD (stochastic, 9/3/3)

```
H9[i]  = max(high[i-8..i])      L9[i] = min(low[i-8..i])
rsv[i] = (close[i] − L9[i]) / (H9[i] − L9[i]) × 100
k[i]   = k[i-1]·2/3 + rsv[i]/3
d[i]   = d[i-1]·2/3 + k[i]/3
```

* With `k[7], d[7]` taken from the published arrays, the recursion reproduces `k[8:]`, `d[8:]` with max error 2.8e-14 / 4.3e-14 in all 9 files — so period 9, α = ⅓ for both K and D, and bar `high`/`low` (not closes) are pinned. (**high**)
* Period 14 (err 22–35) and SMA(3)/SMA(3) stochastic (err 16–24) are rejected.
* **Seed:** indistinguishable. `(2/3)^242 ≈ 1e-43`, so after the first ~70 bars of history any seed (50/50, first RSV, or pandas `ewm(alpha=1/3, adjust=False)` which seeds with the first RSV) gives bit-identical tails (window-only tail-100 error 0.0 … 2.8e-14 for both seeds). The published `k[8]` ≠ `rsv[8]` only shows the history started before the window. Proposed default: pandas `rsv.ewm(alpha=1/3, adjust=False).mean()` for K and the same for D (equivalently seed with the first RSV), computed over the full history. (**medium** for the seed, irrelevant to output)
* Division by zero when `H9 == L9` is not observed; proposed default `rsv = 50.0` (Open questions).

### 2.6 Serialisation details (**high**)

* 11 keys in this order: `ma5, ma20, ma60, bb_up, bb_low, rsi, macd, macd_sig, macd_hist, k, d`; each a JSON array of 250 floats at full Python `repr` precision (no rounding), e.g. `"rsi": [66.97674166008935, …]`.
* The viewer only needs `ma5/ma20/ma60` for the price overlay, `bb_up`+`bb_low` (both) for the band, `rsi`, `macd/macd_sig/macd_hist`, `k/d` for the sub-charts; a missing key degrades gracefully (spec 02 §4.1), a `NaN` literal breaks the whole file.

### 2.7 How much history the rebuild must keep

| indicator | exact after | to match the lost engine to < 1e-6 absolute at `bars[0]` |
|---|---|---|
| MA5/20/60, BB20 | 4 / 19 / 59 bars | 59 bars before the window |
| RSI(14) SMA | 14 bars | 14 bars before the window |
| KD(9,3,3) | — | ≈ 70 bars before the window (`(2/3)^70·100 < 1e-10`) |
| MACD(12,26,9) | — | ≈ 240 bars before the window for high-priced names (`(25/27)^240 · 100 ≈ 1e-6`; the seed difference scales with price, 2330/2454 need the most) |

Proposed default: keep ≥ 500 daily bars per symbol in the cache (yfinance `period="3y"` on first fetch, then incremental), compute on everything, publish the last 250. The original engine evidently did this (`events.json`: the data layer caches daily bars per symbol and refuses regressed responses).

---

## 3. Technical `signals[]`

### 3.1 Item schema (**high**)

```json
{"indicator": "<group>", "label": "<state>", "score": <float, already weighted, 2 dp>, "note": "<text>"}
```

Key order exactly `indicator, label, score, note`. `score` is always a float literal (`0.0`, not `0`). Punctuation inside `note` is **ASCII**: comma `,` (U+002C) and space (U+0020), no full-width characters, e.g. `"MA5>MA20>MA60,趨勢偏多"`, `"量為均量 2.0 倍,量增價跌"`, `"K=9 下穿 D=10"`.

Viewer rendering (`app.js:731-733`): one chip per item, text `indicator + ' ' + label`, class from `clsOf(score)` (`>0` up/red, `<0` down/green, `0` flat), tooltip `note + '(分數 ' + score + ')'`. The viewer never totals these.

### 3.2 Complete inventory of the snapshot (34 items, 11 distinct `(indicator, label, score)` tuples)

| symbol | items (in emitted order) |
|---|---|
| 0050 | `均線排列/糾結/0.0`, `RSI/超賣/0.75` (`RSI=20<30,跌深可能反彈`), `MACD/綠柱/-0.5`, `成交量/帶量下跌/-1.5` (`量為均量 2.0 倍,量增價跌`) |
| 2308 | `均線排列/空頭排列/-3.0`, `RSI/超賣/0.75` (`RSI=10<30,…`), `MACD/綠柱/-0.5`, `KD/死亡交叉/-0.75` (`K=9 下穿 D=10`), `成交量/帶量下跌/-1.5` (`量為均量 2.1 倍,…`) |
| 2317 | `均線排列/糾結/0.0`, `RSI/中性/0.0` (`RSI=44`), `MACD/紅柱/0.5` |
| 2330 | `均線排列/糾結/0.0`, `RSI/超賣/0.75` (`RSI=17<30,…`), `MACD/綠柱/-0.5` |
| 2454 | `均線排列/糾結/0.0`, `RSI/超賣/0.75` (`RSI=22<30,…`), `MACD/綠柱/-0.5`, `成交量/帶量下跌/-1.5` (`量為均量 1.7 倍,…`) |
| 2881 | `均線排列/多頭排列/3.0`, `RSI/中性/0.0` (`RSI=59`), `MACD/綠柱/-0.5` |
| 2882 | `均線排列/多頭排列/3.0`, `RSI/中性/0.0` (`RSI=56`), `MACD/紅柱/0.5` |
| 3481 | `均線排列/糾結/0.0`, `RSI/超賣/0.75` (`RSI=25<30,…`), `MACD/綠柱/-0.5`, `KD/低檔/0.5` (`K=18<20,低檔區`), `布林通道/觸下軌/0.62` |
| 6789 | `均線排列/糾結/0.0`, `RSI/中性/0.0` (`RSI=31`), `MACD/綠柱/-0.5`, `KD/死亡交叉/-0.75` (`K=27 下穿 D=34`) |

Distinct tuples and counts: `均線排列/糾結/0.0` ×6, `均線排列/多頭排列/3.0` ×2, `均線排列/空頭排列/-3.0` ×1, `RSI/超賣/0.75` ×5, `RSI/中性/0.0` ×4, `MACD/綠柱/-0.5` ×7, `MACD/紅柱/0.5` ×2, `KD/死亡交叉/-0.75` ×2, `KD/低檔/0.5` ×1, `布林通道/觸下軌/0.62` ×1, `成交量/帶量下跌/-1.5` ×3.

### 3.3 Emission rules (**high** unless noted)

Order is fixed: `均線排列`, `RSI`, `MACD` are **always** emitted (9/9 files, including zero scores), then `KD`, `布林通道`, `成交量` only when they fire. **A missing conditional group contributes 0** (proved by §4.2: `tech_total` equals the sum of the listed scores in all nine files). Zero-score items for the conditional groups never appear.

Last-bar values the rules were inferred from (`c` = close, `c₋₁` = previous close; `k₋₁/d₋₁` = previous K/D):

| sym | c | ma5 | ma20 | ma60 | rsi | macd_hist | k | d | k₋₁ | d₋₁ | bb_low | bb_up | low | vol/mean20 (incl. today) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0050 | 104.95 | 106.87 | 110.86 | 108.10 | 19.84 | −0.818 | 21.87 | 19.88 | 23.40 | 18.89 | 103.53 | 118.19 | 103.85 | 1.98 |
| 2308 | 1335.0 | 1487.0 | 1736.0 | 1757.4 | 9.82 | −43.1 | 8.56 | 10.24 | 12.84 | 11.08 | 1326.55 | 2145.4 | 1335.0 | 1.71 |
| 2317 | 245.5 | 247.5 | 247.35 | 250.9 | 44.14 | +0.410 | 63.42 | 59.22 | 69.38 | 57.11 | 237.07 | 257.63 | 240.0 | 0.82 |
| 2330 | 2370.0 | 2399.0 | 2470.25 | 2427.8 | 16.92 | −13.2 | 22.58 | 20.95 | 27.98 | 20.14 | 2331.10 | 2609.4 | 2360.0 | 1.22 |
| 2454 | 3915.0 | 4033.0 | 4458.0 | 4345.3 | 21.95 | −69.0 | 21.83 | 17.09 | 22.83 | 14.72 | 3660.26 | 5255.7 | 3805.0 | 1.55 |
| 2881 | 161.5 | 161.0 | 157.125 | 146.06 | 59.38 | −0.092 | 69.13 | 64.70 | 67.34 | 62.49 | 148.85 | 165.40 | 158.0 | 0.81 |
| 2882 | 116.0 | 115.1 | 113.225 | 108.38 | 56.00 | +0.088 | 67.21 | 59.52 | 63.31 | 55.68 | 109.19 | 117.26 | 113.0 | 0.97 |
| 3481 | 42.55 | 46.0 | 49.385 | 48.87 | 25.31 | −0.642 | 18.46 | 20.98 | 21.29 | 22.24 | 43.40 | 55.37 | 41.5 | 0.81 |
| 6789 | 411.0 | 433.6 | 458.7 | 453.21 | 31.04 | −4.16 | 27.50 | 33.59 | 39.73 | 36.63 | 407.75 | 509.65 | 409.0 | 1.08 |

All nine symbols closed down on 2026-10-30 (`pct` −0.31 … −9.8), so no "price up" branch was exercised.

#### 3.3.1 `均線排列` (weight key `ma_align`) — always emitted

| condition (last bar) | `label` | base | `score` (×1.5) | `note` (verbatim) | evidence |
|---|---|---|---|---|---|
| `ma5 > ma20 > ma60` | `多頭排列` | +2.0 | `3.0` | `MA5>MA20>MA60,趨勢偏多` | 2881 (161.0>157.1>146.1), 2882 |
| `ma5 < ma20 < ma60` | `空頭排列` | −2.0 | `-3.0` | `MA5<MA20<MA60,趨勢偏空` | 2308 (1487<1736<1757) |
| otherwise | `糾結` | 0 | `0.0` | `均線糾結,方向不明` | 6 files, incl. 2317 (ma5 247.5 > ma20 247.35 but < ma60) and 0050/2330/2454/3481/6789 (ma5<ma20 but ma20>ma60) |

Strict inequalities; no tolerance band is needed to explain any file (2317's ma5−ma20 = +0.15 still counts as "above", and the file is 糾結 only because of ma60).

#### 3.3.2 `RSI` (weight key `rsi`) — always emitted

| condition | `label` | base (see §4.3) | `score` | `note` | evidence |
|---|---|---|---|---|---|
| `rsi < 30` | `超賣` | +1.5 (or +3.0) | `0.75` | `RSI=%d<30,跌深可能反彈` | 0050 19.8, 2308 9.8, 2330 16.9, 2454 22.0, 3481 25.3 |
| `30 ≤ rsi ≤ 70` | `中性` | 0 | `0.0` | `RSI=%d` | 6789 **31.04** (→ 中性, so the oversold edge is strictly `< 30` or `≤ 30`; 30.0 itself unobserved), 2317 44, 2882 56, 2881 59 |
| `rsi > 70` | `超買` (**low**: by symmetry; the 2026-10-12 AI note for 0050 says `RSI 已進入超買`) | −1.5 (or −3.0) | `-0.75` (**low**) | proposed `RSI=%d>70,漲多可能回檔` (**not observed**) | — |

`%d` is the **rounded** integer: `round(rsi)` (Python `round`, or `'%.0f'`). A plain `'%d' % rsi` truncates and does **not** reproduce: 0050 19.84 → published `20` (truncation gives 19); likewise 2308 9.82→`10`, 2330 16.92→`17`, 2454 21.95→`22`, 2882 55.99…→`56`. Inverse evidence: 9/9 notes match `round()`, 5/9 mismatch `int()`.

#### 3.3.3 `MACD` (weight key `macd`) — always emitted

| condition | `label` | base | `score` | `note` | evidence |
|---|---|---|---|---|---|
| `macd_hist > 0` | `紅柱` | +0.5 | `0.5` | `柱狀體在零軸上,動能偏多` | 2882 at +0.088, 2317 at +0.41 |
| `macd_hist < 0` | `綠柱` | −0.5 | `-0.5` | `柱狀體在零軸下,動能偏空` | 2881 at −0.092 and 6 others |

Exactly 0 is unobserved; proposed `>= 0 → 紅柱`. No DIF/DEA crossover label occurs in the snapshot (no symbol had a histogram sign change on the last bar, so a crossover rule can neither be confirmed nor excluded — Open questions; default: none).

#### 3.3.4 `KD` (weight key `kd`) — conditional, if/elif chain, cross before zone

| priority | condition (last two bars) | `label` | base | `score` (×0.5) | `note` | evidence |
|---|---|---|---|---|---|---|
| 1 | `k₋₁ ≥ d₋₁ and k < d` | `死亡交叉` | −1.5 | `-0.75` | `K=%d 下穿 D=%d` | 2308 (12.84/11.08 → 8.56/10.24), 6789 (39.73/36.63 → 27.50/33.59) |
| 1 | `k₋₁ ≤ d₋₁ and k > d` | `黃金交叉` (**medium**: symmetric; the 2026-10-12 AI note for 2882 says `KD 黃金交叉`) | +1.5 | `0.75` | `K=%d 上穿 D=%d` (**low** wording) | not in snapshot |
| 2 | no cross and `k < 20` | `低檔` | +1.0 | `0.5` | `K=%d<20,低檔區` | 3481 (k 18.46; **d = 20.98 > 20**, so the test is on K only) |
| 2 | no cross and `k > 80` | `高檔` (**low**) | −1.0 | `-0.5` (**low**) | `K=%d>80,高檔區` (**low**) | not in snapshot |
| — | `20 ≤ k ≤ 80`, no cross | *(nothing emitted)* | | | | 0050 k 21.9, 2330 22.6, 2454 21.8, 2317, 2881, 2882 |

Cross takes precedence over zone: 2308 has `k = 8.56 < 20` but only `死亡交叉` is emitted (one item per group). `%d` = `round()` of the **current** K and D (2308: 8.56→`9`, 10.24→`10`; 6789: 27.499→`27`, 33.59→`34`; `int()` would give 8 / 33 — rejected).

#### 3.3.5 `布林通道` (weight key `bb`) — conditional

| condition | `label` | base | `score` (×0.625, rounded 2 dp) | `note` | evidence |
|---|---|---|---|---|---|
| `close < bb_low` | `觸下軌` | +1.0 | `0.62` | `跌破下軌,偏弱但可能超跌反彈` | 3481 (42.55 < 43.40). Non-firing checks: 2308 close 1335.0 > 1326.55; 6789 411 > 407.75; 0050 104.95 > 103.53 |
| `close > bb_up` | `觸上軌` (**medium**: 2026-10-12 AI notes for 2881 say `價格觸及布林上軌` and the AI report gives 2881 `技術分數 +1.9` = 3.0 − 0.5 − 0.625 = 1.875) | −1.0 | `-0.62` (**medium**) | proposed `突破上軌,偏強但可能過熱` (**low** wording) | not in snapshot |

`0.62` is `round(1.0 × 0.625, 2)` under Python's round-half-even on the exactly representable 0.625 → the engine rounds **each** weighted score to 2 dp (confirmed again by §4.2). Whether the test uses `close` or `low` cannot be separated in this snapshot (`low < bb_low` gives the same 9 outcomes: 2308 low 1335.0 > 1326.55, 0050 103.85 > 103.53, 6789 409 > 407.75); the note wording `跌破下軌` ("closed below") favours `close`. Proposed default: `close`.

#### 3.3.6 `成交量` (weight key `volume`) — conditional

| condition | `label` | base | `score` (×1.5) | `note` | evidence |
|---|---|---|---|---|---|
| `ratio ≥ T` and `close < c₋₁` | `帶量下跌` | −1.0 | `-1.5` | `量為均量 %.1f 倍,量增價跌` | 0050 (`2.0`), 2308 (`2.1`), 2454 (`1.7`) |
| `ratio ≥ T` and `close > c₋₁` | `帶量上漲` (**medium**) | +1.0 | `1.5` (**medium**) | `量為均量 %.1f 倍,量增價漲` (**low** wording) | not in snapshot (all 9 fell) |
| otherwise | *(nothing)* | | | | 2330 (ratio ≈ 1.2), 6789 (≈ 1.1), 2317/2881/2882/3481 (< 1.0) |

Threshold `T`: fired at ≥ 1.7 (published) / ≥ 1.55 (recomputed), silent at ≤ 1.25 → `T ∈ (1.25, 1.55]`; proposed default **1.5**. The printed ratio is `'%.1f'`.

**The ratio does not reproduce from `bars[]`** (grid over N = 2…120, mean/median, including/excluding today, lag-1: zero combinations print `2.0 / 2.1 / 1.7` for 0050/2308/2454 simultaneously). Closest: `volume[-1] / mean(volume[-20:])` (20 bars **including** today) gives 1.98 / 1.71 / 1.55 → `2.0 / 1.7 / 1.6` — exact for 0050, whose 2026-10-30 bar is known to be the same object the 18:17 scan used (`events.json` 2026-10-31 09:30: `0050.TW 本次最新日期 2026-10-29 落後快取 2026-10-30(疑似劣化回應),保留舊快取`), while 2308/2454 bars were refreshed by the 10-31 EOD. Implied scan-time volumes for the published ratios are 2308 ≈ 21.9 M (baked 18.3 M) and 2454 ≈ 12.4 M (baked 11.3 M). See Open questions.

### 3.4 `ma_cross` — defined in the weights but never observed

`params_history[*].weights.ma_cross` (1.0 in every version) and `shadow.json → genes[] w_ma_cross` prove a seventh signal group exists. In the snapshot no symbol had a same-day MA5/MA20 (or MA20/MA60, MA5/MA60, MA10/MA20) sign change on 2026-10-30, and nothing was emitted — consistent with a *same-day* cross rule. Crosses that happened 1–2 bars earlier (2317 MA5/MA20 golden cross on 10-29, 2308 MA20/MA60 death cross on 10-29, 6789 MA5/MA10 death cross on 10-30 itself) produced **no** item, which rules out a multi-day look-back for 5/20 and 20/60 and rules out the 5/10 pair entirely. Label strings, base score and note are unknown (Open questions; proposed default in §6).

---

## 4. Weights and aggregation → `data.json → rows[].tech_total`

### 4.1 Weight keys ↔ signal groups

| `weights` key | signal `indicator` | published `score` observed | v9 weight (`params_history[0]`, id 25) | implied base | last **adopted** weight (id 12, `adopted: 1`, 2026-08-19, version 9) | implied base |
|---|---|---|---|---|---|---|
| `ma_align` | `均線排列` | ±3.0 / 0.0 | 1.5 | ±2.0 | 1.5 | ±2.0 |
| `ma_cross` | *(unobserved)* | — | 1.0 | ? | 1.0 | ? |
| `rsi` | `RSI` | +0.75 / 0.0 | **0.25** | **±3.0** | **0.5** | **±1.5** |
| `macd` | `MACD` | ±0.5 | 1.0 | ±0.5 | 1.0 | ±0.5 |
| `kd` | `KD` | −0.75 (cross), +0.5 (zone) | 0.5 | ∓1.5 (cross), ±1.0 (zone) | 0.5 | same |
| `bb` | `布林通道` | +0.62 | 0.625 | ±1.0 | 0.625 | ±1.0 |
| `volume` | `成交量` | −1.5 | 1.5 | ±1.0 | 1.5 | ±1.0 |

`score = round(base × weight, 2)` (Python `round`, half-even; this is what turns 0.625 into `0.62`). The two weight sets differ **only** in `rsi`, and the published RSI score (0.75) is the same under both, so the viewer output of the snapshot does not discriminate. See §4.3.

### 4.2 Aggregation (**high**)

`tech_total = Σ score over the emitted signals[]` — a plain sum of the already-rounded, already-weighted scores; **no clipping, no re-quantisation to 0.05/0.1, no normalisation**:

| sym | listed scores | Σ | `rows[].tech_total` |
|---|---|---|---|
| 0050 | 0 + 0.75 − 0.5 − 1.5 | −1.25 | −1.25 |
| 2308 | −3 + 0.75 − 0.5 − 0.75 − 1.5 | −5.0 | −5.0 |
| 2317 | 0 + 0 + 0.5 | 0.5 | 0.5 |
| 2330 | 0 + 0.75 − 0.5 | 0.25 | 0.25 |
| 2454 | 0 + 0.75 − 0.5 − 1.5 | −1.25 | −1.25 |
| 2881 | 3 + 0 − 0.5 | 2.5 | 2.5 |
| 2882 | 3 + 0 + 0.5 | 3.5 | 3.5 |
| 3481 | 0 + 0.75 − 0.5 + 0.5 + **0.62** | **1.37** | **1.37** |
| 6789 | 0 + 0 − 0.5 − 0.75 | −1.25 | −1.25 |

9/9 equal as floats (`sum == tech_total` is `True` in Python). 3481 is decisive: the unrounded sum would be 1.375 (→ `1.38` if rounded once at the end), the published 1.37 means each signal score was rounded to 2 dp **before** summing. 1.37 is not a multiple of 0.05 or 0.1, so no coarse quantisation exists. Range in the snapshot: −5.0 … +3.5; the theoretical envelope with v9 weights is ±(3 + 0.75 + 0.5 + 0.75 + 0.62 + 1.5 + |ma_cross|) = ±7.12 + ma_cross, and nothing suggests a cap (2308 reached −5.0 with 5 of 6 groups firing).

Proposed engine rule: `tech_total = round(Σ round(base_i × w_i, 2), 2)` — the outer `round` is a no-op on the snapshot but protects against float noise (the viewer prints the raw value in the score tooltip: `'技術 ' + r.tech_total`, `app.js:505`).

Cross-reference (spec 01/03): `rows[].total == round(tech_total + mkt_score + fund_total + news_total + chips_total + kd60_total, 1)` holds 9/9 (e.g. 2330: 0.25 − 0.5 + 1.5 + 0.5 − 1.0 + 0.0 = 0.75 → `0.8`; 3481: 1.37 − 0.5 + 0 − 1.07 + 0 + 0.5 = 0.30 → `0.3`). `rows[].kd60_total` (from `intraday_kd.score`, 60-minute KD) is **not** part of `tech_total`.

### 4.3 Which weight set is live (**medium**)

`params_history[]` rows carry `adopted: 0|1`; `params_json` on an `adopted: 0` row is the best **challenger** of that tuning run, not the incumbent. Evidence: (a) the only `adopted: 1` rows are ids 1–6, 10, 11, 12; id 12 (2026-08-19, version 9) is the last adoption and `engine.params_version` / `model-health.active_version` are still 9; (b) every later `params_json` (ids 13–25) equals id 12 with **one** weight multiplied by 1.5 or 0.5 (`bb 0.625→0.9375`, `rsi 0.5→0.75`, `rsi 0.5→0.25`), i.e. single-step perturbations of an unchanged incumbent; (c) rows 16–19 and 23–25 have `valid_metric == champion_metric` to full precision — a challenger whose trades coincide with the incumbent's over the validation window — which is natural for a small `rsi` change and impossible to read as "the incumbent changed three times without an adoption record".

Consequently the live weights at snapshot time are most likely **id 12's**: `{ma_align: 1.5, ma_cross: 1.0, rsi: 0.5, macd: 1.0, kd: 0.5, bb: 0.625, volume: 1.5}`, and the base scores are the "natural" set `{ma_align ±2, rsi ±1.5, macd ±0.5, kd ±1.5 cross / ±1.0 zone, bb ±1.0, volume ±1.0}`. Under the caller's assumption (`params_history[0]`, `rsi: 0.25`) the only change is `rsi base = ±3.0`. The published snapshot is identical either way; the choice matters as soon as weights are re-tuned (e.g. adopting shadow arm B, `w_rsi = 0.784`: 1.5×0.784 = `1.18` vs 3.0×0.784 = `2.35`). Listed under Open questions with the proposed default `base ±1.5, w = 0.5`.

Weight-update mechanics seen in the history (for the tuner spec, not this one): `buy_th 3.0, strong_th 5.0, sell_th −3.0, strong_sell_th −5.0, fund_cap 1.5, exit {stop_pct 0.08, trail_pct 0.12}` are applied to `rows[].total`, not to `tech_total`.

---

## 5. Reproducible formulas (normative)

Inputs: full cached history `H` (≥ 500 bars), columns `open, high, low, close, volume` (adjusted prices, integer shares). `i` = last bar, `i-1` = previous bar. All rolling windows use `min_periods = n` (no shorter-window fallback); the published arrays are `[-250:]` slices, so they are never `NaN`.

```
ma_n[i]        = mean(close[i-n+1 .. i])                         n ∈ {5, 20, 60}
sigma20[i]     = stdev(close[i-19 .. i], ddof=1)
bb_up[i]       = ma_20[i] + 2.0·sigma20[i]
bb_low[i]      = ma_20[i] − 2.0·sigma20[i]

gain[i]        = max(close[i] − close[i-1], 0);  loss[i] = max(close[i-1] − close[i], 0)
rsi[i]         = 100 − 100 / (1 + mean(gain[i-13..i]) / mean(loss[i-13..i]))
                 (loss-mean 0 → 100.0; both 0 → 50.0 [proposed])

ema_s[i]       = ema_s[i-1] + (2/(s+1))·(x[i] − ema_s[i-1]),  ema_s[0] = x[0]   (adjust=False)
macd[i]        = ema_12(close)[i] − ema_26(close)[i]
macd_sig[i]    = ema_9(macd)[i]
macd_hist[i]   = macd[i] − macd_sig[i]

rsv[i]         = (close[i] − min(low[i-8..i])) / (max(high[i-8..i]) − min(low[i-8..i])) · 100
                 (denominator 0 → 50.0 [proposed])
k[i]           = (2/3)·k[i-1] + (1/3)·rsv[i]        (k seeded with the first rsv [proposed])
d[i]           = (2/3)·d[i-1] + (1/3)·k[i]

ratio          = volume[i] / mean(volume[i-19 .. i])           [proposed; see Open questions]
```

Signal evaluation on the last bar, in this order, each producing `score = round(base × w[key], 2)`:

```
均線排列 (always):  ma5>ma20>ma60 → 多頭排列 +2 | ma5<ma20<ma60 → 空頭排列 −2 | else 糾結 0        key ma_align
RSI      (always):  rsi<30 → 超賣 +1.5 | rsi>70 → 超買 −1.5 [low] | else 中性 0                 key rsi
MACD     (always):  macd_hist>=0 → 紅柱 +0.5 | else 綠柱 −0.5                                   key macd
KD       (cond.):   k₋₁>=d₋₁ and k<d → 死亡交叉 −1.5 | k₋₁<=d₋₁ and k>d → 黃金交叉 +1.5 [medium]
                    | elif k<20 → 低檔 +1.0 | elif k>80 → 高檔 −1.0 [low] | else nothing         key kd
布林通道 (cond.):   close<bb_low → 觸下軌 +1.0 | close>bb_up → 觸上軌 −1.0 [medium] | else nothing   key bb
成交量   (cond.):   ratio>=1.5 and close<close₋₁ → 帶量下跌 −1.0 | ratio>=1.5 and close>close₋₁ → 帶量上漲 +1.0 [medium]
                    | else nothing                                                              key volume
(ma_cross: see Open questions)                                                                   key ma_cross
tech_total = round(Σ score, 2)
```

Notes (verbatim templates; `%d` = `round()` to int, `%.1f` one decimal, ASCII comma/space):

| label | note template |
|---|---|
| `多頭排列` | `MA5>MA20>MA60,趨勢偏多` |
| `空頭排列` | `MA5<MA20<MA60,趨勢偏空` |
| `糾結` | `均線糾結,方向不明` |
| `超賣` | `RSI=%d<30,跌深可能反彈` |
| `中性` | `RSI=%d` |
| `紅柱` | `柱狀體在零軸上,動能偏多` |
| `綠柱` | `柱狀體在零軸下,動能偏空` |
| `死亡交叉` | `K=%d 下穿 D=%d` |
| `低檔` | `K=%d<20,低檔區` |
| `觸下軌` | `跌破下軌,偏弱但可能超跌反彈` |
| `帶量下跌` | `量為均量 %.1f 倍,量增價跌` |

---

## 6. Open questions (with proposed defaults)

1. **RSI base score / live `rsi` weight.** Published `0.75` = 1.5 × 0.5 (last adopted id 12) or 3.0 × 0.25 (`params_history[0]`, a non-adopted challenger). Evidence in §4.3 favours id 12. *Default:* base ±1.5, weight 0.5; store base scores in code and weights in params so the product is what is published.
2. **`ma_cross` signal.** Weight key exists (1.0) but no item was ever observed; same-day semantics inferred from non-events (§3.4). *Default:* `indicator "均線交叉"`, MA5 crossing MA20 on the last bar only; `黃金交叉` base +1.0 / `死亡交叉` base −1.0, notes `MA5 上穿 MA20,短線轉強` / `MA5 下穿 MA20,短線轉弱`; emitted between `均線排列` and `RSI`. Mark the strings as unverified in the engine so they can be swapped without touching logic.
3. **Volume ratio source.** No function of `bars[].volume` prints `2.0 / 2.1 / 1.7`; the 0050 value matches `volume[-1] / mean(volume[-20:])` and the other two bars were refreshed after the scan. *Default:* that formula (20 bars including today), threshold 1.5, `'%.1f'`; computed from the same bar the signal is evaluated on, so the published note and the bar are always consistent in the rebuild.
4. **Unobserved branch strings:** `超買` note, `黃金交叉` wording (`上穿`), `高檔` note, `觸上軌` note, `帶量上漲` note. *Defaults* as listed in §3.3 / §5; scores by symmetry (−0.75, +0.75, −0.5, −0.62, +1.5 under v9 weights).
5. **Boundary equalities:** `rsi == 30/70`, `macd_hist == 0`, `k == 20/80`, `close == band`, `ratio == 1.5`. *Defaults:* `rsi < 30` / `rsi > 70`; `macd_hist >= 0 → 紅柱`; `k < 20` / `k > 80`; strict `<`/`>` for bands; `ratio >= 1.5`.
6. **Bollinger touch uses `close` or `low`/`high`?** Indistinguishable on this snapshot. *Default:* `close` (note says `跌破`).
7. **Degenerate denominators:** RSI with zero loss (→ 100) / zero gain and loss (→ 50); KD with `H9 == L9` (→ rsv 50). Not observed; *defaults* as stated, must never emit `NaN`.
8. **History length / seeds of the lost engine.** Unknown; irrelevant beyond ~240 pre-window bars for MACD and ~70 for KD (§2.7). *Default:* keep ≥ 500 bars, pandas `ewm(adjust=False)` seeded with the first value.
9. **MACD crossover label.** Not seen; the AI prose (`MACD 翻紅`, `翻綠柱`) is consistent with just `紅柱`/`綠柱` flipping. *Default:* no separate crossover signal.
