# 05 — Market, fundamentals, news, chips and 60-min KD scoring; final recommendation, sizing and AI-note semantics

Status: reverse-engineered from the two surviving baked snapshots (git `8623d98` = bake of 2026-10-31T14:15:22+08:00, the working-tree files, "Oct"; git `2e74138` = bake of 2026-08-15T14:15:32+08:00, "Aug"), the viewer (`app.js` 2082 lines, `index.html`, `simple.html`) and the engine's own log lines in `events.json` / `orders.json`. Nothing here comes from engine source. Every rule that is not literally in the viewer or in an engine log line is marked **inferred** with its evidence and a confidence (**high** = reproduced numerically on every available row; **medium** = consistent with all data but not uniquely determined; **low** = plausible guess). Unresolved points are collected in §11 with a proposed default.

Companion documents: `01-data-json-contract.md` (field-by-field `data.json` contract, incl. `rows[]`), `02-symbol-json-contract.md` (per-symbol file; its §5–§9 give the raw shapes of `fund_signals`, `news`, `chips`, `intraday_kd`, `trend`), `03-orders-events-health-shadow-contract.md` (`params_history`, `genes`, event formats). This document is about the **rules that produce the numbers**, not the shapes.

Evidence base (18 "symbol-rows" = 9 symbols × 2 snapshots):

| Source | Used for |
|---|---|
| `data.json → overview.market`, `overview.rows[]` (Oct + Aug) | `mkt_score`, `fund_total`, `news_total`, `chips_total`, `kd60_total`, `total`, `rec_code`, `changed`, `regime`, `suggest_qty`, `forecast5`, `ai_note` |
| `symbol/*.json` (Oct + Aug) | `fund_signals`, `news.items`, `chips.signals/recent`, `intraday_kd`, `trend.summary`, `forecast.horizons`, `bars` (ATR for sizing) |
| `model-health.json → params_history[].params_json` | `buy_th 3.0`, `strong_th 5.0`, `sell_th -3.0`, `strong_sell_th -5.0`, `fund_cap 1.5`, `use_market true`, `use_fundamentals true`, `exit.stop_pct 0.08` |
| `shadow.json → genes[]` | `risk_frac 0.005`, `strong_mult 1.5`, `caution_scale 0.5`, `persistence 2.0`, `strong_gap 2.0` |
| `events.json`, `orders.json` | gate messages (G3/G4), `市場狀態:halt`, recommendation-change lines, news-refresh lines, fills used to probe sizing |
| `data.json → ai_report.content`, `rows[].ai_note.text` (2026-10-12 and 2026-08-02/03) | historical component values quoted by the AI (`籌碼 +1.5`, `技術分數 +1.9`, `外資連賣三日` …) |

---

## 0. Composition of the score (verified)

```
total = round(tech_total + mkt_score + fund_total + news_total + chips_total + kd60_total, 1)
```

| Snapshot | Rows where `round(Σ,1) == total` | Notes |
|---|---|---|
| Oct (2026-10-30 18:17 scan) | **9 / 9** (e.g. 2330: 0.25 − 0.5 + 1.5 + 0.5 − 1.0 + 0.0 = 0.75 → `0.8`; 2454: −1.25 − 0.5 + 0.3 − 0.33 − 1.0 + 0.0 = −2.78 → `-2.8`; 2308: −5.0 − 0.5 + 1.5 − 1.34 − 0.5 + 0.3 = −5.54 → `-5.5`) | Python `round()` on the float sum (`-2.78 → -2.8`, `0.75 → 0.8`, `2.67 → 2.7`, `2.92 → 2.9`, `-3.08 → -3.1`) |
| Aug (2026-08-14 20:50 scan) | 6 / 9; the 3 misses are exactly the rows whose `news_total` was refreshed after the scan (2317: Σ 3.66 vs `3.0`; 2454: 2.38 vs `2.2`; 2308: 2.84 vs `2.5`) | `total` and `rec_code` are frozen at scan time; `news_total` (= `symbol.news.score`) is overwritten whenever the news refresher runs (§3.6) |

Component identities, verified on all 18 rows (**high**):

| `rows[]` field | equals |
|---|---|
| `mkt_score` | `overview.market.score` (same value on every row of a snapshot: `-0.5` ×9 Oct, `0.5` ×9 Aug) |
| `fund_total` | `min(max(Σ fund_signals[].score, -fund_cap), +fund_cap)` with `fund_cap = 1.5`, then rounded to 1 dp (§2) |
| `news_total` | `symbol.news.score` (2 dp) |
| `chips_total` | `symbol.chips.score` = clipped Σ `chips.signals[].score` (§4) |
| `kd60_total` | `symbol.intraday_kd.score`; `rows[].kd60` = `intraday_kd` minus `score` |
| `tech_total` | Σ `symbol.signals[].score` (18/18; the technical rules themselves are out of scope here) |
| `regime` | `symbol.trend.summary.regime` |
| `forecast5` | the `horizon_days == 5` entry of `symbol.forecast.horizons` (§9) |
| `ai_note` | identical object to `symbol.ai_note` (§10) |

Component value grids observed: `mkt_score ∈ {-0.5, +0.5}`, `fund_total` multiples of 0.1 in `[0, 1.5]`, `news_total` 2-dp float in `[-1.34, 0.96]`, `chips_total ∈ {-1.5, -1.0, -0.5, 0.0, 0.5, 1.5}`, `kd60_total ∈ {0.0, 0.3, 0.5}`.

Feature flags (`params_json`): `use_market: true` and `use_fundamentals: true` in every one of the 25 parameter rows (v2 … v9). **Inferred** (high on intent, untestable): when `use_market` is false the engine adds `0.0` for `mkt_score` (and should still publish `market.*` for the top bar); when `use_fundamentals` is false `fund_total = 0.0` and `fund_signals = []`. Neither flag has ever been false in the surviving history, so the rebuild may keep them as constants.

---

## 1. Market block (`overview.market`, `rows[].mkt_score`)

### 1.1 Fields

```json
"market": {"is_open": false, "label": "收盤", "index": 45211.828125, "pct": -2.4941593686153634, "regime_label": "偏空震盪", "score": -0.5}
```

| Field | Rule | Evidence / confidence |
|---|---|---|
| `index` | last close (or last intraday quote when open) of `^TWII` (Yahoo Finance Taiwan Weighted Index), emitted **unrounded**. Values are float32-representable (`45211.828125`, `45811.01171875`), i.e. straight from yfinance's float32 column; the viewer prints `fmtPrice` (2 dp). | **high** on source (`disclaimer`: "資料來源 Yahoo Finance"; AI report quotes "加權指數收 49,301.96"); `simple.html` prints it as `45,212` (0 dp) |
| `pct` | `(index / previous_close − 1) × 100`, unrounded (`-2.4941593686153634`) | **high**; the EOD event prints the same number as `大盤單日 -2.5%` (1 dp) |
| `is_open` | `true` while the TWSE session is open (09:00–13:30 Taipei on a trading day), else `false`. Both bakes (14:15) say `false`. | **medium** (only closed-market samples exist; `simple.html`/viewer fall back to `is_open ? '盤中' : '收盤'`) |
| `label` | `"盤中"` when `is_open` else `"收盤"` — the only two strings the viewer knows (`app.js:398`). | **high** |
| `regime_label` | short Chinese mood label, see §1.2 | observed `"偏空震盪"` (Oct), `"偏多震盪"` (Aug), `「偏空震盪」` quoted by the 2026-08-02 AI report |
| `score` | the market tilt added to every row as `mkt_score` | observed `-0.5` / `+0.5` |

Viewer rendering (`app.js:404–411`): `regime_label + ' ' + ('+' if score>0) + score` → `偏空震盪 -0.5`; chip colour by sign of `score`; chip hidden when `regime_label` is falsy. `simple.html` line: `加權指數 <span class='down'>45,212(-2.49%)</span>.大盤環境:偏空震盪`.

### 1.2 `regime_label` / `score` rule — **inferred (medium)**

Only two label/score pairs were ever baked. The index proxy `0050.TW` (which carries the same `trend.summary` machinery as every symbol, §7) sits in the identical configuration on both days, so the following rule reproduces both observations:

| Condition on `^TWII` daily bars (same MA20/MA60 "raw daily label" as `02 §9.1` step 1) | `regime_label` | `score` | Evidence |
|---|---|---|---|
| raw label `range` **and** `close > ma20` (equivalently `slope20 > 0`) | `"偏多震盪"` | `+0.5` | Aug: 0050 close 106.40 > ma20 101.59, ma20 < ma60 103.14 → `range`; `slope20 = +65.12` |
| raw label `range` **and** `close < ma20` (`slope20 < 0`) | `"偏空震盪"` | `-0.5` | Oct: 0050 close 104.95 < ma20 110.86, ma20 > ma60 108.10 → `range`; `slope20 = -118.71` |
| raw label `bull` (`close > ma20 > ma60`) | `"多頭"` (proposed) | `+1.0` (proposed) | never baked; the 2026-10-12 AI report says of the index "趨勢判定仍為多頭" and every 10-12 `ai_note` says "大盤站在多方 / 大盤處於多頭 / 大盤仍處多頭格局" — a distinct bull state existed on 10-12 |
| raw label `bear` (`close < ma20 < ma60`) | `"空頭"` (proposed) | `-1.0` (proposed) | never baked; 2026-08-03 `ai_note`s say "加權指數趨勢仍為 bear", "空頭的大盤環境" |

Counter-evidence to keep in mind (why the bull/bear rows are **low** confidence): the 2026-08-02 AI report quotes the label as `「偏空震盪」` on a day it also describes as index "+7.98%" with the next day's notes calling the index trend `bear`. Either the label set really is only `{偏多震盪, 偏空震盪}` (score only ever ±0.5, driven by close-vs-MA20) and the bull/bear words in the AI texts come from a separate `regime` string passed to the prompt, or the label flipped between 08-02 and 08-03. The viewer does not constrain this (it prints whatever string it gets). See §11 Q1.

The AI notes cannot pin `mkt_score` on 10-12 to `+0.5` vs `+1.0` (both are consistent with every quoted total once the unknown news/kd60 parts are allowed to vary).

### 1.3 Market *state* (gate G3) — separate from the tilt

The tilt above is additive; a second, non-additive market **state** gates orders (it does not change `rec_code` or `total`):

| Log line (verbatim format) | Meaning |
|---|---|
| `市場狀態:halt(大盤單日 -2.5%、5日 -3.6%)` (EOD 2026-10-30 14:15:25) | state machine entered `halt` from the index's 1-day (`pct`, 1 dp) and 5-day returns. Thresholds unknown (−2.49 % and −3.6 % triggered it); proposed defaults in §11 Q2 |
| `晨會:夜盤 -1.4%、TSM -1.8%、費半 -1.4%;近 3 日事件 1 筆、宏觀新聞 15 則;風險覆蓋 caution` (08:30/11:23 morning briefing) | overnight override: night-session TAIEX futures, TSM ADR, SOX; override is `無覆蓋` or `風險覆蓋 caution` |
| `閘門攔截 2881 買進:G3:市場 caution(晨會覆蓋:隔夜情勢(caution)),禁加碼` | while the override is `caution`, **adds to existing positions are blocked** (`禁加碼`); a fresh entry is still allowed but sized by `caution_scale` (§8.4). On 2026-10-30 2882's and 2317's *add* orders were blocked at 12:58/13:03 while 2317's *entry* at 12:58 filled |

So "regime" has three different meanings in the engine: the additive `market.score`, the per-symbol `trend.summary.regime` (§7), and the G3 order gate (this section). The July weekly review's "G3/regime 擋下 365 筆買單" refers to this gate in its earlier, regime-based form; by October it is the caution/halt override.

---

## 2. Fundamentals (`symbol.fund_signals[]`, `rows[].fund_total`)

### 2.1 Vocabulary (every distinct tuple ever baked; strings verbatim)

Item schema: `{"indicator": str, "label": str, "score": float(1 dp), "note": str}`; array order is always `ROE`, `營收成長`, `盈餘成長`, `毛利率`, `本益比` (only the ones that fire), or the single placeholder.

| `indicator` | `label` (format) | `score` | `note` | Observed inputs → score |
|---|---|---|---|---|
| `ROE` | `f"{roe*100:.0f}%"` | `0.7` | `股東權益報酬率高,獲利能力強` | 24 %, 25 %, 26 %, 29 %, 30 %, 40 %, 42 % |
| `ROE` | same | `0.3` | `ROE 尚可` | 12 %, 13 %, 19 % |
| `營收成長` | `f"{g*100:.0f}%"` | `0.7` | `營收年增率高,成長強` | 29 %, 31 %, 36 %, 41 %, 48 %, 51 %, 94 %, 176 % |
| `營收成長` | same | `0.3` | `營收正成長` | 1 %, 10 %, 13 %, 19 % |
| `營收成長` | same | `-0.5` | `營收衰退` | −25 %, −62 % |
| `盈餘成長` | `f"{g*100:.0f}%"` | `0.4` | `獲利成長` | 18 %, 26 %, 34 %, 67 %, 68 %, 69 %, 77 %, 80 % |
| `盈餘成長` | same | `-0.4` | `獲利衰退` | −13 % |
| `毛利率` | `f"{m*100:.0f}%"` | `0.3` | `高毛利,具競爭力` | 26 %, 28 %, 50 %, 51 % |
| `本益比` | `f"{pe:.0f}"` (no `%`) | `-0.3` | `本益比偏高,評價偏貴` | 55, 65, 67, 69, 78, 95, 455 |
| `基本面` | `中性` | `0.0` | `基本面無明顯偏多或偏空訊號` | placeholder emitted **only** when no other signal fires (0050, both snapshots) |

No other labels/notes exist in the data (no low-PE bonus, no negative-ROE, no low-margin text, no dividend-yield / EPS-level signal).

### 2.2 Thresholds — **inferred (medium)**

| Metric | Rule consistent with every observation | Gap in the evidence |
|---|---|---|
| ROE | `≥ 0.20 → 0.7`; `> 0 (or ≥ 0.10) → 0.3`; else no signal | cut lies in (19 %, 24 %]; lower bound of the 0.3 band unobserved (smallest seen 12 %) |
| 營收成長 (revenue YoY) | `≥ 0.20 → 0.7`; `> 0 → 0.3`; `< 0 → -0.5` | cut lies in (19 %, 29 %] |
| 盈餘成長 (earnings YoY) | `> 0 → 0.4`; `< 0 → -0.4` | only one negative sample (−13 %) |
| 毛利率 (gross margin) | `≥ 0.25 → 0.3`, no negative branch | **anomaly**: 2454 (its own news says "毛利率46.3%") and 2308 never get the chip while 2881/2882 (26 %/28 %) do; and 3481/6789 never show it. Most likely the source field was missing/None for those tickers at fetch time (signal skipped when the field is absent), not a different threshold. See §11 Q3 |
| 本益比 (trailing PE) | `> 50 → -0.3`; no positive branch observed | cut lies in (≈30, 55]; 3481's PE went 455 → 55 between Aug and Oct and the chip stayed |
| placeholder | emitted iff the list would otherwise be empty | 0050 is an ETF: no ROE/PE/margins/growth in the source |

Data source (**medium**): the five metrics map one-to-one onto yfinance `Ticker.info` keys `returnOnEquity`, `revenueGrowth`, `earningsGrowth`, `grossMargins`, `trailingPE` (all fractions, hence the `×100` formatting; PE a plain number). Values changed between Aug and Oct exactly as quarterly `info` fields do (2330 ROE 40 % → 42 %, revenue 36 % → 51 %, earnings 77 % → 69 %, margin 50 % → 51 %; 2454 PE 67 → 65). Missing keys → the signal is skipped (explains 2882-Aug with only `營收成長` and 2881-Aug without `毛利率`/`本益比`).

### 2.3 `fund_total` — **high**

`fund_total = round(clip(Σ score, -1.5, +1.5), 1)` with `fund_cap = 1.5` from `params_json`.

| Symbol (snapshot) | Σ scores | `fund_total` | Note |
|---|---|---|---|
| 2330 (Oct, Aug) | 0.7+0.7+0.4+0.3 = 2.1 | `1.5` | capped |
| 2308 (Oct) | 0.7+0.7+0.4 = 1.8 | `1.5` | capped |
| 2308 (Aug) | 0.7+0.7+0.4−0.3 = 1.5 | `1.5` | exactly at cap |
| 2317 (both) | 0.3+0.7+0.4 = 1.4000000000000001 | `1.4` | rounding needed |
| 2454 (both) | 0.7+0.3−0.4−0.3 = 0.3 | `0.3` | |
| 2881 (Oct) / (Aug) | 0.7−0.5+0.3 = 0.5 / 0.3+0.7 = 1.0 | `0.5` / `1.0` | |
| 2882 (Oct) / (Aug) | 0.5 / 0.7 | `0.5` / `0.7` | |
| 3481 (Oct) / (Aug) | 0.3−0.3 = 0.0 / 0.3+0.4−0.3 = 0.4 | `0.0` / `0.4` | |
| 6789 (both) | 0.3+0.4−0.3 = 0.4 | `0.4` | |
| 0050 (both) | 0.0 | `0.0` | placeholder |

The negative cap (−1.5) is symmetric by construction (`fund_cap` is one number) but has never been reached (minimum possible with the vocabulary is −1.2).

---

## 3. News (`symbol.news`, `rows[].news_total`)

### 3.1 Source and query

* Every `items[].link` is a Google News RSS redirect `https://news.google.com/rss/articles/CBM…?oc=5` (142/142 items across both snapshots) → the feed is `https://news.google.com/rss/search?q=<query>&hl=zh-TW&gl=TW&ceid=TW:zh-Hant` (Traditional-Chinese Taiwan edition; all `source` strings are Taiwanese outlets: `Yahoo股市`, `今周刊`, `UDN`, `ETtoday財經雲`, `CMoney`, `工商時報`, `經濟日報`, `MoneyDJ`, `DIGITIMES`, `Facebook`, `1111人力銀行` …). **high** on the endpoint, **medium** on parameters.
* Query text: not recoverable from the data. Every 0050 title contains `0050`, every 2317 title contains `鴻海`, every 2881 title `富邦金`; but 6789-Aug returned unrelated DIGITIMES/1111 items and 2308-Aug an unrelated "狂賺870萬…" item, which is what a loose name query (`采鈺`, `台達電`) returns. Proposed default in §11 Q4: `q = name` (the Chinese short name), falling back to `code` for ETFs.
* `items[]` keeps **feed order** (not time-sorted: 0050-Oct runs 12:37, 08:54, 12:31, 14:26 …) and is truncated to **8** entries (17 of 18 symbol-files have exactly 8; 6789-Oct has 6 because the feed had only 6). The refresh event also reports `(8 則)`.
* `published`: RSS `pubDate` (GMT) converted to Taipei and written as `2026-10-30T12:37:47+08:00` (seconds precision). Oldest item seen is 3 days before the scan (2881-Oct: 10-27 22:10 at a 10-30 scan), so no hard window shorter than ~72 h is applied to the *list*.
* `source`: RSS `<source>` text, raw (includes odd hosts like `sinotrade.com.tw`, `news.cnyes.com`, `fnc.ebc.net.tw`).

### 3.2 Per-item sentiment

| Field | Rule | Evidence |
|---|---|---|
| `score` | integer in **[−3, +3]** written as float (`-2.0`, `1.0`, `3.0`); observed set `{-3,-2,-1,0,1,2,3}` | 142 items |
| `sentiment` | `"pos"` if `score > 0`, `"neg"` if `< 0`, `"neu"` if `== 0` — never disagrees with the sign (142/142) | viewer `NEWS_BADGE` maps `pos→利多`, `neg→利空`, `neu→中性` (`app.js:1222–1226`) and falls back to the sign of `score` for unknown values |
| scorer | title-level ("標題級情緒計分(AI 語意為主,詞典備援)", `app.js:741`): primary path = an AI call on the title with the fast model (`engine.ai.model_fast = "sonnet"`), fallback = a keyword lexicon | `events.json`: `AI 呼叫失敗(sonnet,rc=1):Failed to authenticate: OAuth session expired and could not be refreshed`, then `AI 連續失敗 3 次,暫停 AI 呼叫 15 分鐘(期間自動改用非 AI 路徑)` — a 3-strike circuit breaker with a 15-minute pause |

Consequence for reproduction: the **Oct** item scores are lexicon output (AI down since 2026-10-12), the **Aug** ones are AI output. Neither the lexicon nor the AI prompt survives; §11 Q5 proposes a minimal lexicon that reproduces the sign of every Oct title (`跌停`/`重挫`/`慘跌`/`崩`/`砍目標價` → negative; `創新高`/`大賺`/`漲停`/`買點`/`最重要的夥伴` → positive; everything else 0).

### 3.3 Aggregate `news.score` (= `rows[].news_total`) — **not fully determined**

Observed (sum of the 8 item scores → published aggregate):

| Snapshot | Symbol | n | Σ item scores | `news.score` | Σ/6 | fits Σ/6? |
|---|---|---|---|---|---|---|
| Oct | 0050 | 8 | +1 | `0.17` | 0.167 | yes |
| Oct | 2330 | 8 | +3 | `0.5` | 0.500 | yes |
| Oct | 2454 | 8 | −2 | `-0.33` | −0.333 | yes |
| Oct | 2882 | 8 | −5 | `-0.83` | −0.833 | yes |
| Oct | 2317 | 8 | 0 | `0.0` | 0 | yes |
| Oct | 2308 | 8 | −8 | `-1.34` | −1.333 | off by 0.01 |
| Oct | 2881 | 8 | +3 | `0.42` | 0.500 | no (items span 10-27…10-30) |
| Oct | 3481 | 8 | −13 | `-1.07` | −2.167 | no |
| Oct | 6789 | 6 | +1 | `-0.37` | 0.167 | no — sign differs (the −2 item is from 10-30, both positives from 10-28) |
| Aug | 2454 | 8 | +2 | `0.33` | 0.333 | yes |
| Aug | 2881 | 8 | −3 | `-0.5` | −0.500 | yes |
| Aug | 2882 | 8 | +1 | `0.17` | 0.167 | yes |
| Aug | 0050, 6789 | 8 | 0 | `0.0` | 0 | yes |
| Aug | 2308 | 8 | +2 | `0.34` | 0.333 | off by 0.01 |
| Aug | 2317 | 8 | +6 | `0.96` | 1.000 | no (items span 08-12…08-14) |
| Aug | 2330 | 8 | +2 | `0.4` | 0.333 | no |
| Aug | 3481 | 8 | +4 | `0.5` | 0.667 | no |

Findings from a brute-force fit over 18 cases (time-decay families exp/linear/window/per-day with reference time = scan time, bake time or newest item; denominators n, Σw, 6, 8, √n; rank-position weights; title de-duplication; per-item clipping; source down-weighting):

* The best any single formula reaches is **10–11 / 18**, and `Σ score / 6` (equivalently `mean × 4/3` for n = 8) is the backbone of every top family.
* 6789-Oct proves a **recency component** exists (older positives are outweighed by one fresher negative); 2308-Oct (`-1.34` vs −1.333) and 2308-Aug (`0.34` vs 0.333) prove weights are **not all 1 even for same-day items**; 3481-Oct (`-1.07` from six negatives on the same day) cannot be produced by any monotone time weight that also keeps 2308-Oct at ≈ −8/6 — so either the aggregate is **smoothed across refreshes** (e.g. an EMA of successive refresh means, consistent with 3481 reading `-1.2` at 11:22 and `-1.07` at 18:17) or the AI path returns its own aggregate. Neither can be verified from two snapshots.
* The viewer never recomputes it (`app.js:738–741`, `1233–1243`), and it is explicitly "僅供提示,不構成訊號;不納入回測" — it **does** enter `total` though (§0).

Proposed default (§11 Q6): `news.score = round(Σ_i w_i·s_i / 6, 2)` with `w_i = 0.5 ** (age_hours / 24)` measured from the refresh time, over the ≤ 8 kept items, clipped to ±3. This reproduces the 10 clean cases and gives the right sign for 6789-Oct.

### 3.4 Refresh cadence and the `消息面` event

* News is refreshed **independently of the 5-minute scan**; `total`/`rec_code` keep the value from the last scan while `news_total` is overwritten (the Aug mismatch in §0). Observed refresh moments (from the AI-failure bursts and `消息面` lines): 10-28 17:20, 10-28 23:45, 10-29 14:32, 10-30 11:22 (2330/2308/3481), 10-30 11:57 (2454) → roughly every few hours, symbols staggered.
* Event line (verbatim format): `{code} {name} 消息面偏空 {score:.1f}({n} 則)` — seen for `-1.2`, `-1.0`, `-1.2`, `-1.0`; **inferred** (medium): emitted when the refreshed score ≤ −1.0, with the mirror `消息面偏多 +x.x(n 則)` for ≥ +1.0 (never observed; the Aug 2317 `0.96` produced no line, consistent with a 1.0 threshold).

---

## 4. Chips / institutional flow (`symbol.chips`, `rows[].chips_total`)

### 4.1 Data

* Source: TWSE **T86** daily "三大法人買賣超" (viewer tooltip `TWSE 三大法人買賣超(T86,收盤後公布);僅供提示,暫不納入回測`). Units are **shares** (raw, signed); the viewer divides by 1000 for `張`.
* `recent[]`: the last **10 trading days**, newest first: `{"date": "YYYY-MM-DD", "foreign": int, "invtrust": int, "dealer": int, "total": int}` with `total = foreign + invtrust + dealer` (verified, e.g. 0050 10-30: −97 979 941 + 2 609 000 − 67 364 227 = −162 735 168). Non-trading days are simply absent (10-23/24/26 missing).
* The streak counters below need **more than 10 days** of history (a 16-day streak is reported) — keep ≥ 60 trading days in the engine's store even though only 10 are published.
* OTC (`.TWO`) symbols have no T86 row: publish `{"score": 0.0, "signals": [], "recent": []}` and the viewer prints `暫無籌碼資料(上櫃股票或資料尚未回填)` (`app.js:1297`; also shown when `chips` is missing entirely). No `.TWO` symbol exists in either snapshot.

### 4.2 Signals (verbatim vocabulary; array order `外資動向`, `投信動向`, `法人動能`)

| `indicator` | `label` | `score` | `note` | Rule |
|---|---|---|---|---|
| `外資動向` | `外資連買{n}日` | `+1.5` | `外資連續 {n} 個交易日買超` | `n` = consecutive trading days (newest backwards) with `foreign > 0`; observed n = 5, 6 |
| `外資動向` | `外資連賣{n}日` | `-1.5` | `外資連續 {n} 個交易日賣超` | consecutive days with `foreign < 0`; observed n = 16 |
| `投信動向` | `投信買超` | `+0.5` | `近 5 日投信買賣超同向(無反向日)` | all of the last 5 days have `invtrust > 0` |
| `投信動向` | `投信賣超` | `-0.5` | `近 5 日投信買賣超同向(無反向日)` | all of the last 5 days have `invtrust < 0` |
| `法人動能` | `法人買盤動能` | `+0.5` | `近 3 日三大法人合計 z 分數 {z:+.2f}(相對近 60 日)` | `z ≥ +1` (observed +1.12, +1.81) |
| `法人動能` | `法人賣壓動能` | `-0.5` | same format | `z ≤ −1` (observed −1.02, −1.08, −2.06) |

Streak threshold evidence (foreign):

| Case | Streak (from `recent`) | Signal? | Implication |
|---|---|---|---|
| 2454-Aug | +6 (08-06 negative) | `外資連買6日` 1.5 | ≥ 5 → ±1.5 |
| 0050-Aug | +5 (08-07 negative) | `外資連買5日` 1.5 | 5 is enough for 1.5 |
| 0050/2330/2454-Oct | −16 (needs history beyond the 10 shown) | `外資連賣16日` −1.5 | no higher tier above 1.5 (also capped, §4.3) |
| 3481-Oct (−2), 2308-Oct (−2: 10-28 foreign = **+1 410**, a tiny positive, breaks it), 2881-Aug (+2) | 2 | none | threshold > 2; the sign test is strict (`> 0` / `< 0`); a 0 or opposite-sign day of any size breaks the run |
| 2026-10-12 `ai_note`s: "外資連賣三日" (2330, 2317, 2454, 0050) with 2454's chips quoted as `籌碼面 -1.5` = 外資連賣3日 + 法人賣壓動能(−0.5); 2330: "外資已連賣三日(投信買超難以完全抵銷)" | 3 | yes | **inferred (medium)**: `3 ≤ n < 5 → ±1.0` (label still `外資連買{n}日`/`外資連賣{n}日`); with ±0.5 the 2330 wording ("not fully offset" by +0.5) would be false |

投信 evidence: 2308-Aug (5 positives) → `投信買超`; 2454-Aug (5 negatives) → `投信賣超`; 2317-Oct (4 positives then −255 528) → none; 3481-Oct (4 positives then −504 500) → none; 0050-Aug (0, then negatives, then +50 000) → none. So **all five** must share the sign; a `0` day counts as "反向" (proposed, untested).

法人動能: `z` = z-score of the latest 3-day sum of `total` against the distribution of rolling 3-day sums over the trailing 60 trading days (**inferred, medium**: the note says "近 3 日三大法人合計 z 分數 … 相對近 60 日"; mean/std of 3-day sums is the natural reading; the data published is too short to recompute it). `|z| < 1` → no signal (all 9 no-signal cases are consistent, but unverifiable). Format `f"{z:+.2f}"` (`+1.12`, `-1.08`).

### 4.3 `chips.score` — **high**

`chips.score = clip(Σ signals[].score, -1.5, +1.5)`, 1 dp. Evidence: 0050-Aug has `外資連買5日 +1.5` + `法人買盤動能 +0.5` = 2.0 but publishes `1.5`; 2454-Aug `1.5 − 0.5 + 0.5 = 1.5`; 0050-Oct `−1.5 + 0.5 − 0.5 = −1.5`; 2330-Oct `−1.5 + 0.5 = −1.0`; 2308-Oct `−0.5`; no signals → `0.0`. The 2026-10-12 AI report quotes `籌碼 +1.5 最強(外資買超)` for 6789 whose note lists "外資連買五日與投信同步買超" (1.5 + 0.5 → capped 1.5) — same cap. `rows[].chips_total` is this value.

---

## 5. 60-minute KD (`symbol.intraday_kd`, `rows[].kd60`, `rows[].kd60_total`)

```json
{"score": 0.5, "k": 16.0, "d": 15.3, "label": "低檔黃金交叉", "note": "60分K線 K=16 D=15"}
```

| Field | Rule | Confidence |
|---|---|---|
| `k`, `d` | stochastic K/D on **60-minute bars** (yfinance `interval="60m"`), rounded to 1 dp (`20.5`, `27.1`) | high on rounding; the KD parameters (9,3,3 as for the daily KD) are unobserved |
| `note` | `f"60分K線 K={k_raw:.0f} D={d_raw:.0f}"` formatted from the **unrounded** values (Oct 2881: `k 52.0, d 47.5` → `K=52 D=47`, i.e. the raw d was 47.4999…; Aug 2317: `d 13.5` → `D=14`) | high |
| `label` / `score` | see table | |

Observed label → score pairs (18 rows + Aug duplicates):

| `label` | `score` | Observed K/D | Rule (**inferred, medium**) |
|---|---|---|---|
| `中性` | `0.0` | 14 rows, K between 20.5 and 63.7 | nothing else fires |
| `低檔` | `+0.3` | K 4.3/D 11.1; K 12.0/D 13.5; K 12.9/D 26.3 | `K < 20` (D unconstrained: 26.3 qualifies) and no fresh cross |
| `低檔黃金交叉` | `+0.5` | K 16.0 > D 15.3 (3481-Oct) | `K < 20` and K crossed above D on the latest bar |

Unobserved but implied by the naming: `高檔` (`K > 80`) → `-0.3`, `高檔死亡交叉` → `-0.5`; mid-range crosses probably carry no score (`中性`). §11 Q7. The viewer prints the chip `60分KD {label}` plus ` ±x.x` only when the score is non-zero and calls it "短線輔助(未回測,僅小幅 tilt)". `rows[].kd60` is the same object **without** `score`; `rows[].kd60_total = score`.

---

## 6. `total` → `rec_code` / `rec_text`, `changed`, and the persistence gate

### 6.1 Thresholds (**high**; from `params_json` + 18 rows + order notes)

| Condition on `total` (1 dp) | `rec_code` | `rec_text` | Evidence |
|---|---|---|---|
| `total ≥ strong_th (5.0)` | `STRONG_BUY` | `強力買進` | order notes `訊號加碼(強力買進,評分 +5.0)`, `(+5.1)`, `(+5.5)`; AI report `+5.4【強力買進】`, `+5.7`, `+5.8`, `+6.0` |
| `buy_th (3.0) ≤ total < 5.0` | `BUY` | `買進` | 2317-Aug `total 3.0 → BUY` (boundary **inclusive**); order note `訊號進場(買進,評分 +3.0)` on 10-30; AI `+3.3【買進】`, `+3.6`, `+4.4` |
| `-3.0 < total < 3.0` | `HOLD` | `觀望` | 2881-Oct `2.9 → HOLD`, 2454-Oct `-2.8 → HOLD`, AI `-0.2【觀望】`, `+2.5 觀望` |
| `strong_sell_th (-5.0) < total ≤ sell_th (-3.0)` | `SELL` | `賣出` | 0050-Oct `-3.1 → SELL`; AI `-3.7 建議賣出` |
| `total ≤ -5.0` | `STRONG_SELL` | `強力賣出` | 2308-Oct `-5.5 → STRONG_SELL` |

`strong_th = buy_th + strong_gap` (`strong_gap` gene = 2.0 in both arms); `strong_sell_th = -strong_th`. The five strings are the viewer's `REC` map (`app.js:24–30`) and must be byte-identical (CSS classes `rec-sbuy/rec-buy/rec-hold/rec-sell/rec-ssell`). The comparison is on the published 1-dp `total` (proposed; only the rounded value is observable).

`rec_code` is recomputed on **every scan** (5-minute cadence while open, plus `啟動`, `收盤定盤` and EOD scans): the event log shows flips at 09:31, 10:31, 11:01, 12:58, 13:02, 13:33, 14:02, 14:15 and 18:17 on single days. Only the technical part moves intraday (quotes); `fund/news/chips/kd60` are picked up as last refreshed.

### 6.2 `changed` and the recommendation-change event

* `changed = (rec_code != rec_code of the previous scan for the same symbol)`; it is `true` only for the scan that flipped it and reverts to `false` on the next scan with no flip (**high**: Oct's five `true` rows are exactly the five `…→…` events stamped at the `last_scan` 18:17; Aug's one `true` row (2881) is exactly the one event at 20:51:04 = `last_scan` 20:50:42 + 22 s).
* Event line format: `{code} {name}:{old rec_text}→{new rec_text}` (INFO, source `engine`), e.g. `2308 台達電:賣出→強力賣出`, `0050 元大台灣50:觀望→賣出`, `2881 富邦金:強力買進→買進`. One line per flipped symbol, emitted in row order, ~1 s apart. The viewer shows `●` with title `本次掃描建議有變化`.

### 6.3 Persistence (`persistence` gene = 2.0) — gate G4, not part of `rec_code`

`閘門攔截 6789 買進:G4:2026-08-13 收盤評分 -0.6 未達 buy_th +3.0,訊號未跨日持續` and `閘門攔截 2317 買進:G4:2026-08-13 收盤評分 +0.8 未達 buy_th +3.0,訊號未跨日持續` (both on 08-14 right after the symbols flipped to `買進` intraday):

* A BUY order requires the signal to hold on `persistence = 2` consecutive **daily** observations: the current scan's `total ≥ buy_th` **and** the previous trading day's **EOD (收盤) total ≥ buy_th**. Message format: `閘門攔截 {code} 買進:G4:{prev_date} 收盤評分 {prev_total:+.1f} 未達 buy_th {buy_th:+.1f},訊號未跨日持續`.
* The gate blocks the *order* only; the row still shows `BUY` and `changed:true`. The 08-14 event sequence (`6789 采鈺:觀望→買進` at 09:31:00, G4 block at 09:31:01) shows the gate runs in the same scan immediately after the flip.
* `persistence` is identical in both shadow arms (`differs:false`), so the adopted v10 keeps 2.0.
* SELL-side orders are driven by the exit rules (stop/trail) and by `SELL`/`STRONG_SELL` + swap logic (`自動換股:賣出 0050 元大台灣50(評分 -2.0)讓位給 2317 鴻海(評分 +3.0)`); no persistence line was ever logged for a sell.

Gate inventory seen in the logs: `G1/freshness` (stale quote; only in the July weekly review), `G3` (market caution/halt, §1.3), `G4` (persistence). `G2` never appears in any surviving text (§11 Q8).

---

## 7. Per-symbol regime (`rows[].regime`) and `caution_scale`

* `rows[].regime = trend.summary.regime ∈ {"bull","bear","range"}` — the raw MA20/MA60 label of the last daily bar (`02 §9.2`), viewer chip `多頭`/`空頭`/`盤整`.
* It does **not** feed `total`, `rec_code` or `suggest_qty` (§8 reproduces all 18 quantities without it; §0 reproduces all totals without it). It is informational and goes into the AI prompts (the notes quote it: "趨勢分段也判定為 bull", "型態判定仍是區間整理").
* `caution_scale = 0.5` (arm A; B 0.55) is **not** a regime multiplier either: it is the order-size multiplier applied while the market override is `caution` (§8.4). The only sizing input that differs between a bull and a bear symbol is its ATR.

---

## 8. `suggest_qty` — **high** (18/18 exact)

### 8.1 Formula

```
atr14   = SMA_14( TR ),  TR_t = max(H_t − L_t, |H_t − C_{t−1}|, |L_t − C_{t−1}|)   on the published daily bars[] (last bar included)
q_risk  = 0.0075 × cash / atr14
q_cap   = 0.30   × cash / price
suggest_qty = floor( min(q_risk, q_cap) )          # shares, odd lots allowed, may be 0
```

where `cash = overview.account.cash` (not equity) and `price = rows[].price` (the last quote).

Interpretation (**medium** — the constants are exact, their decomposition is not): `0.0075 = risk_frac (0.005) × strong_mult (1.5)` — the displayed quantity is the *maximum* (strong-signal) size — and `0.30` is a per-order cash cap of 30 % of available cash. The budget `0.0075 × cash` is "cash at risk per 1 ATR move"; no `stop_pct` term and no equity term appear (an `equity × risk_frac / (price × stop_pct)` candidate gives 257 for 2317-Oct vs the published 329, and `equity × risk_frac / (2.5 × atr14)` misses three Oct rows by one share and every Aug row by ~5×).

### 8.2 Verification

Oct (`cash 269 729.55`, budget 2 022.97, cap notional 80 918.87):

| code | price | atr14 | `q_risk` | `q_cap` | published | binding |
|---|---|---|---|---|---|---|
| 2330 | 2370.00 | 39.2857 | 51.49 | 34.14 | **34** | cap |
| 2317 | 245.50 | 6.0357 | 335.17 | 329.61 | **329** | cap |
| 2454 | 3915.00 | 197.1429 | 10.26 | 20.67 | **10** | risk |
| 2308 | 1335.00 | 86.4286 | 23.41 | 60.61 | **23** | risk |
| 2882 | 116.00 | 3.3929 | 596.24 | 697.58 | **596** | risk |
| 0050 | 104.95 | 2.0679 | 978.29 | 771.02 | **771** | cap |
| 6789 | 411.00 | 21.9643 | 92.10 | 196.88 | **92** | risk |
| 3481 | 42.55 | 2.3107 | 875.47 | 1901.74 | **875** | risk |
| 2881 | 161.50 | 4.6429 | 435.72 | 501.05 | **435** | risk |

Aug (`cash 55 760.09`, budget 418.20):

| code | price | atr14 | `q_risk` | `q_cap` | published |
|---|---|---|---|---|---|
| 2330 | 2395.0 | 67.1429 | 6.23 | 6.98 | **6** |
| 2317 | 259.5 | 10.7857 | 38.77 | 64.46 | **38** |
| 2454 | 4210.0 | 254.2857 | 1.64 | 3.97 | **1** |
| 2308 | 1885.0 | 119.2857 | 3.51 | 8.87 | **3** |
| 2882 | 101.5 | 3.3571 | 124.57 | 164.81 | **124** |
| 0050 | 106.4 | 3.0714 | 136.16 | 157.22 | **136** |
| 6789 | 442.5 | 27.2857 | 15.33 | 37.80 | **15** |
| 3481 | 50.1 | 3.4321 | 121.85 | 333.89 | **121** |
| 2881 | 129.5 | 3.8929 | 107.43 | 129.17 | **107** |

Tightness of the constants: the integer floors bracket the budget to `[2022.14, 2024.19]` (Oct) and `[417.71, 418.72]` (Aug), i.e. coefficient `∈ [0.007497, 0.007505] ∩ [0.007491, 0.007509]` → `0.0075`; the cap is bracketed by 0050/2317/2330-Oct to `[0.29999, 0.30036)` → `0.30`. ATR variants fail: EWM-14 (Wilder) 3/9 and 4/9, SMA-10 2/9, SMA-20 5/9, high–low-only 3/9.

### 8.3 What the viewer does with it

`recs` tab (`app.js:1170–1184`): BUY/STRONG_BUY rows show `(qty × price / equity × 100).toFixed(1) + '%'` ("建議部位 %"), SELL rows show the held `positions[].qty`; the order modal pre-fills `suggest_qty` (`app.js:660`). `0` → `—`.

### 8.4 Real fills vs the formula (supporting evidence, **medium**)

Walking `orders.json` backwards from the published cash gives the cash before each BUY:

* 36 of the 40 BUY fills in the window are exactly `floor(0.30 × cash / price_hint)` — the engine was cash-starved from 09-21 to 10-14 (cash 500–45 000) and the 30 % cap bound every time (e.g. 10-01 09:01 2330 `21` = floor(0.3 × 179 139 / 2495); 10-13 11:27 3481 `265` = floor(0.3 × 44 462 / 50.2)).
* 2026-10-30 12:58 `2317 193 股` (`訊號進場(買進,評分 +3.0)`, cash before 317 175, morning override `風險覆蓋 caution`): `q_cap = 387.6`, `q_risk ≈ 394–411` → `floor(0.5 × 387.6) = 193` ✓. This is the only fill under a logged `caution` state and it is exactly **`caution_scale × suggest_qty`** — the `caution` override halves new entries and (per the G3 lines) blocks adds.
* Two early fills do not fit any multiplier (09-25 6789 `143` implies 0.0086; 09-29 2882 `463` implies 0.0068); the backward cash reconstruction ignores any dividend credits in late September, so these are not treated as counter-evidence. No fill distinguishes a BUY-sized (`risk_frac × 1.0`) order from a STRONG_BUY-sized (`× strong_mult`) one — §11 Q9.

---

## 9. `rows[].forecast5`

```json
"forecast5": {"pred_ret": 0.0, "prob_up": 0.5, "ci68_lo": -0.027381500634110295, "ci68_hi": 0.027381500634110295, "model": "baseline"}
```

* Exactly the `horizon_days == 5` element of `symbol.forecast.horizons[]`, re-keyed: `pred_ret`, `prob_up`, `ci68_lo = ci68[0]`, `ci68_hi = ci68[1]`, `model` (18/18 identical, full float precision; `ci95` and the 1-/20-day horizons are not copied). `model` is the current champion for horizon 5 (`model-health.metrics.champion["5"]`: `baseline` in Oct, `ridge` in Aug).
* Viewer: tooltip `5日預測 {fmtRet(pred_ret)}(漲率 {round(prob_up×100)}%,{model})` on the watch-list row and the `recs` cell `{fmtRet(pred_ret)} 漲率{p}%`; absent → `累積中`.
* It plays no role in `total`/`rec_code` (Oct's 9 rows carry `pred_ret 0.0, prob_up 0.5` while recommendations range from `STRONG_SELL` to `HOLD`).

---

## 10. `ai_note {ts, rec_code, text}`

* Same object in `rows[].ai_note` and `symbol.ai_note`; `null`/absent when never generated (viewer then prints `尚未產生` if `engine.ai.enabled`).
* Generated per symbol by the deep model (`engine.ai.model_deep = "opus"`) **only when the call succeeds**; otherwise the previous note is kept verbatim — Oct's notes are all dated **2026-10-12** (19 days before the bake) because every AI call since then failed (`health.ai_last_success = 2026-10-12T14:18:21+08:00` = the `ts` of the last note written, 3481's). Stale `ts` is therefore normal and the viewer only prints `HH:MM` (`AI 解讀 14:17`).
* `ts`: wall-clock of generation, ISO Taipei with seconds. Oct run: sequential 14:16:22 → 14:18:36 (one symbol every 15–20 s, started right after the 14:15 EOD, in watch-list row order 2330, 2317, 2454, 2308, 2882, 0050, 6789, 3481, 2881); Aug run: 2026-08-03 18:12:48 → 18:15:06 (an evening run, so the trigger is not strictly "after EOD").
* `rec_code`: the symbol's `rec_code` **at generation time**, not the current one (all nine Oct values match the 2026-10-12 daily report's verdicts — `STRONG_BUY`/`BUY`/`HOLD` — while the current rows are `HOLD`/`SELL`/`STRONG_SELL`). It lets a consumer see which recommendation the prose was written for.
* `text`: 3–5 short paragraphs of Traditional Chinese separated by `\n\n`, no markdown, ending with a disclaimer sentence; observed closers are `以上為數據解讀,非投資建議。`, `以上為系統數據解讀,非投資建議。`, `本內容為系統數據解讀，非投資建議。`, `以上為數據解讀，非投資建議。`. Content quotes the component scores (`技術分數 +1.9`, `籌碼面 -1.5`, `帶量下跌(-1.5)`), the 5-day forecast (`上漲機率 50%`, `±2.7%`), `trend.summary` fields (`slope120 已轉負`, `距 252 日高點`, `MA60 上方約 5%`), position P&L, and fresh news/calendar items — i.e. the prompt receives the whole symbol payload plus the row and position.
* `simple.html` repeats each note under `🤖 {code} {name} AI 解讀 {HH:MM}`.

---

## 11. Open questions (with proposed defaults)

1. **`market.regime_label` vocabulary beyond `偏多震盪 +0.5` / `偏空震盪 -0.5`.** Evidence for a bull state on 2026-10-12 and a bear state on 2026-08-03 exists only in AI prose, and the 08-02 report shows `偏空震盪` on a day the AI also calls bear. *Default:* implement the four-state rule of §1.2 (`多頭 +1.0`, `偏多震盪 +0.5`, `偏空震盪 -0.5`, `空頭 -1.0`) on `^TWII` daily bars; keep the two observed strings byte-exact; make the ±1.0 states easy to disable (collapse to ±0.5) if replay against future snapshots disagrees.
2. **Market state machine thresholds (`市場狀態:halt(大盤單日 -2.5%、5日 -3.6%)`).** *Default:* `halt` when 1-day `pct ≤ −2.0 %` or 5-day return `≤ −3.5 %` (evaluated at EOD; both printed with 1 dp); `caution` from the morning-briefing override (night futures ≤ −1 % or TSM ADR ≤ −1.5 %); `halt` blocks all buys, `caution` blocks adds and halves entries (`caution_scale`). State names `normal`/`caution`/`halt`.
3. **Fundamental thresholds and the missing `毛利率` chips** (§2.2). *Default:* ROE `≥ 20 % → 0.7`, `> 0 → 0.3`; revenue `≥ 20 % → 0.7`, `> 0 → 0.3`, `< 0 → −0.5`; earnings `> 0 → 0.4`, `< 0 → −0.4`; gross margin `≥ 25 % → 0.3`; PE `> 50 → −0.3`; skip any metric whose source field is `None`; emit the `基本面/中性` placeholder when nothing fires.
4. **Google News query string and item cap.** *Default:* `q = name` (`鴻海`), `hl=zh-TW&gl=TW&ceid=TW:zh-Hant`, keep the first 8 feed entries in feed order.
5. **Title sentiment scorer (AI prompt and lexicon both lost).** *Default:* AI path = fast model, prompt asking for one integer in −3…+3 per title; lexicon fallback with weights `跌停 −2, 重挫 −2, 慘跌 −2, 崩 −2, 砍目標價 −1, 虧損 −1, 下殺 −1, 創新高 +2, 漲停 +2, 大賺 +1, 買點 +1, 利多 +1`, summed and clipped to ±3; `sentiment` = sign.
6. **`news.score` aggregation** (§3.3; best single formula fits 10–11/18). *Default:* `round(Σ w_i s_i / 6, 2)`, `w_i = 0.5 ** (age_h / 24)` from the refresh time, clipped to ±3; emit `{code} {name} 消息面偏空 {score:.1f}({n} 則)` / `消息面偏多 +…` when `|score| ≥ 1.0`.
7. **60-min KD label set.** *Default:* `低檔` (+0.3) K<20; `低檔黃金交叉` (+0.5) K<20 and K crossed above D; `高檔` (−0.3) K>80; `高檔死亡交叉` (−0.5) K>80 and K crossed below D; otherwise `中性` 0.0; KD(9,3,3) on 60-minute bars.
8. **Gate `G2`** never appears in any surviving text. *Default:* reserve the number (e.g. "insufficient cash / qty 0") so the numbering G1 freshness, G3 market, G4 persistence stays as logged.
9. **Does a plain `BUY` order use `risk_frac × 1.0` and `STRONG_BUY` `× strong_mult`, or is 0.0075 a constant?** The published `suggest_qty` is `0.0075 × cash / atr14` for every row regardless of `rec_code`. *Default:* order size = `floor(min(cash × risk_frac × (strong_mult if STRONG_BUY else 1.0) / atr14, 0.30 × cash / price)) × (caution_scale if caution else 1)`, and publish `suggest_qty` as the strong-mult size (reproduces the data).
10. **Reference time for the 3-day/60-day `法人動能` z-score and zero handling in streaks.** *Default:* z = (sum of the last 3 `total` − mean of rolling 3-day sums over the last 60 trading days) / std of those sums; a `0` day breaks both the foreign streak and the 5-day 投信 run.
11. **`is_open` definition.** *Default:* `true` from 09:00:00 to 13:30:00 Taipei on TWSE trading days (holiday calendar from `行事曆同步`), else `false`; `label` derived from it.
