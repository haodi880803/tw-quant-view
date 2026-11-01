# tw-quant engine — consolidated implementation specification (Python 3.13 rebuild, params v10)

Status: single, self-contained spec for rebuilding the lost paper-trading engine that published this repository's data files. It consolidates the eight reverse-engineering notes in `docs/spec/01…08-*.md` (kept as appendices with the full evidence tables). Everything an implementer needs is in this file; the section files are only cited (`[01 §4.2]` = `docs/spec/01-data-json-contract.md`, section 4.2) so the evidence can be re-checked.

Evidence base: the viewer (`app.js` 2082 lines, `index.html`, `simple.html`, `app.css`), the last bake (git `8623d98`, `data.json` `generated_at` `2026-10-31T14:15:22+08:00`, the working tree) and the previous surviving bake (git `2e74138`, `2026-08-15T14:15:32+08:00`). No engine source survives. Confidence tags: **high** = reproduced exactly on every observation or read from code; **medium** = consistent with all data but under-determined; **low** = plausible reading of sparse evidence. Rules without a tag are high. Everything marked *default* in §10 is a proposal the implementer takes unless the owner objects.

Notation: `round(x, n)` is Python's `round` (half-even); `floor` is integer floor; money is NTD; "bar date" = a date that has a daily OHLCV bar (= TWSE trading day); "T" = Taipei calendar date of the run. All Chinese strings are verbatim and must be emitted byte-for-byte (ASCII `,` `(` `)` `;` `:` inside them are ASCII; `、` `。` `——` `「」` are full-width exactly where shown).

---

## 1. Purpose, constraints, runtime, time rules

### 1.1 Purpose

Reproduce, on GitHub Actions, the engine that (a) scores a fixed 9-symbol TWSE watchlist every scan, (b) runs a paper account with an autopilot, (c) records/resolves 1/5/20-day forecasts for two models, (d) tunes parameters weekly, (e) keeps a monthly reward scoreboard, (f) ran a shadow A/B test whose arm B is now adopted as params **v10**, and (g) bakes `data.json`, `symbol/<code>.json`, `orders.json`, `events.json`, `model-health.json`, `shadow.json` and `simple.html` for the unchanged read-only viewer.

### 1.2 Hard constraints

| # | Constraint | Why |
|---|---|---|
| C1 | `index.html`, `simple.html`'s template, `app.js`, `app.css`, `vendor/echarts.min.js` are **not** modified; every published file keeps the exact key order, types, enum strings, rounding and serialization of §7 | the viewer is the contract; it is frozen |
| C2 | `symbol/<code>.json.symbol` must equal `data.json.overview.rows[].symbol` byte-for-byte (`"2330.TW"`), else the viewer silently drops the detail (`app.js:809`) | [01 §1.1] |
| C3 | `events[].id`, `orders[].id`, `params_history[].id` and `version` continue from the surviving snapshot: next event id **6763**, next order id **109**, next params id **26**, next version **10** | the viewer dedups events by `id > last_id`; restarting ids below 6762 would hide new events until a reload [03 §2.2] |
| C4 | Never serialise `NaN`/`Infinity`; never emit `\uXXXX` escapes; one line, no trailing newline | `res.json()` would throw; byte parity |
| C5 | Timestamps are Taipei-local with explicit `+08:00`; the viewer never converts (`ts.slice(11,19)`, `iso.replace('T',' ').slice(0,16)`) | [01 §0], [03 §0] |
| C6 | The paper account, ledgers and counters live in `state/` committed to git (hosted runners are stateless); the original kept state outside the repo, which is why it was lost | [08 §3.6] |
| C7 | Orders are only ever filled on a trading day with a fresh quote; the original filled two orders on 2026-09-25 (a holiday) from stale quotes — do not reproduce | [08 §2.1] |
| C8 | `state/` and published files contain no secrets (the site root is public) | [08 §3.1] |

### 1.3 Runtime

Python 3.13, `pandas` + `numpy` (indicator formulas below are specified in pandas terms and were verified with pandas 2.x), `requests`/`urllib`, optional `anthropic` SDK. Runs as cold GitHub Actions jobs (§9); no in-process loop. Repository default branch holds engine, workflow, `state/` and the published files.

### 1.4 Time, date and number rules

| Item | Rule | Example |
|---|---|---|
| "now" | `datetime.now(ZoneInfo("Asia/Taipei"))`; in replay `TWQ_NOW` | — |
| ISO timestamps | `.isoformat(timespec="seconds")` → explicit `+08:00`, no microseconds, never `Z`/UTC | `2026-10-31T14:15:22+08:00` |
| Quote/scan timestamps | real seconds of the scan (the Oct snapshot's `:00` came from a minute-truncated restart clock; Aug shows `20:50:42`) | `rows[].ts`, `engine.last_scan` |
| Dates | `YYYY-MM-DD` (bar dates, `ai_report.date`, series/shadow dates); months `YYYY-MM`; ISO weeks `YYYY-Www` | `2026-10-30`, `2026-10`, `2026-W31` |
| RSS `pubDate` | RFC-822 GMT → converted to Taipei, written with `+08:00` | `2026-10-30T12:37:47+08:00` |
| Cron | UTC; Taipei = UTC+8, no DST; the engine decides what to do from the Taipei clock at run time, never from the cron slot | `15 6 * * 1-5` = 14:15 Taipei |
| Forecast fan calendar | `pd.bdate_range(made_date, periods=21)` — weekdays only, Taiwan holidays **not** removed (reproduces the data) | `2026-10-30` → `2026-11-27` |
| Rounding | Python `round` (half-even) everywhere; prices/levels 2 dp, `total` 1 dp, signal scores 2 dp, series `mae` 6 dp / `hit_rate` 4 dp, shadow pct 4 dp | `round(0.625, 2) = 0.62` is load-bearing (§4.2) |
| Unrounded fields | `account.cash/equity/realized_pnl/unrealized_pnl`, `market.index/pct`, `orders[].pnl`, forecast `pred_ret/ci*/prob_up`, indicators, `ledger.by_horizon.mae/hit_rate`, shadow `stats.*.slip_bp`, `trades[].price` | full Python `repr` |

### 1.5 Serialization rules (all JSON files)

`json.dumps(obj, ensure_ascii=False)` with default separators (`", "`, `": "`), no indent, written without a trailing newline, UTF-8. Key order = insertion order exactly as listed in §7 (diff-stability; verified identical in both bakes). Booleans are JSON `true/false` except `params_history[].adopted` which is the integer `0`/`1`. `params_history[].params_json` is a JSON **string** produced by `json.dumps(params)` (default `ensure_ascii=True`; ASCII-only anyway). Round-trip property that must hold for every published file: `json.dumps(json.loads(raw), ensure_ascii=False) == raw`.

---

## 2. Module map (proposal; 13 modules)

Package `engine/`. Each module exposes the functions named; everything else is private. Section references say where the rules come from.

| Module | Responsibility | Public functions | Spec |
|---|---|---|---|
| `engine/__main__.py` | CLI: `python -m engine run --mode M --kind K`, `schedule decide …`, `bake`, `record --as-of`, `replay`; wires the mode pipelines of §9.4; exit code 1 only on push failure or unhandled exception | `main(argv)` | §9 |
| `engine/clock.py` | Taipei clock (`TWQ_NOW` override), ISO/date formatting, trading-day test (`holidays[]` + "no new `^TWII` bar"), cron→mode decision, `next_scan` slot | `now()`, `iso(dt)`, `is_trading_day(date)`, `decide(event, cron, mode, as_of) -> (mode, kind, reason)` | §1.4, §9.3, §9.8 |
| `engine/state.py` | `state/` load/save (JSON/JSONL), counters (`next_event_id`, `next_order_id`, `next_params_id`), event append (`log(level, source, message)`), AI pause flag, offline fixtures routing (`TWQ_OFFLINE`, `TWQ_AS_OF`) | `load() -> State`, `save(state)`, `log(state, level, source, msg)`, `next_id(state, kind)` | §8.1, §9.6 |
| `engine/datafeed.py` | Yahoo daily bars (adjusted), 60-min bars, quotes, `^TWII`/`TSM`/`^SOX`, fundamentals; Google News RSS; TWSE T86, ex-dividend calendar, holiday schedule; per-source cache with the degraded-response guard and fallbacks | `daily_bars(sym)`, `quote(sym)`, `bars_60m(sym)`, `fundamentals(sym)`, `news_items(sym)`, `t86(date)`, `calendar_sync()`, `index_quote()` | §3 |
| `engine/indicators.py` | MA/BB/RSI/MACD/KD on full history then `[-250:]`, ATR14, 60-min KD, trend segments + summary, 20-day σ | `compute(bars) -> Indicators`, `atr14(bars)`, `kd(bars60)`, `trend(bars, ind)` | §4.1, §4.9, §4.11 |
| `engine/scoring.py` | technical/fundamental/chips/news/60-min-KD signal items, market tilt & state, `total`→`rec_code`/`rec_text`/`changed`, G4 persistence inputs, `suggest_qty` | `tech_signals(ind, params)`, `fund_signals(info)`, `news_score(items, now)`, `chips_signals(t86_hist)`, `kd60_label(k, d, kprev, dprev)`, `market(twii_bars)`, `compose(row)`, `suggest_qty(cash, price, atr14, params)` | §4.2–4.8, §4.11 |
| `engine/forecast.py` | baseline + ridge forecasts, fan, prediction ledger record/resolve (upsert), `by_horizon`, `by_model_horizon`, `series`, `champion`, `model_health_brief`, quality-drop check | `forecast(bars, model)`, `record(state, sym, bars)`, `resolve(state, sym, bars) -> int`, `metrics(state)`, `quality_drop(state) -> (bool, hit_pct, mae_pct)` | §4.10 |
| `engine/broker.py` | paper account: fills (5 bp slippage), fee/tax, fee-inclusive average cost, pnl, positions (`peak/stop/trail/verdict/reasons`), order ledger + broker events, monthly reward settlement | `fill(state, side, sym, qty, price_hint, note, now)`, `mark(state, quotes)`, `account(state)`, `positions(state)`, `settle_month(state, twii)` | §5.1–5.3, §8.6 |
| `engine/autopilot.py` | per-scan decision table: exits → swaps → entries/adds; gates G1/G3/G4, halt/caution, 3-orders cap, sizing | `run_scan(state, rows, market_state, caution, now) -> list[order]` | §5.4–5.7 |
| `engine/tuner.py` | params object (v9/v10), walk-forward champion/challenger, candidate generator, `reward_points` backtest metric, adoption rule, `params_history` rows + tuner events, manual adoption helper | `active_params(state)`, `tune(state, bars_all, now)`, `adopt_manual(state, params, reason, now)` | §6, §8.2 |
| `engine/shadow.py` | two-arm ledger (M3 fills), rows/legs/stats/holdings/genes, hash chain, close-out, automatic verdict, manual seal, panel bake | `advance(state, date)`, `panel(state) -> dict`, `seal_manual(state, verdict, now)` | §6.7, §7.7, [08 §1] |
| `engine/ai.py` | Anthropic client (`sonnet`/`opus` aliases), global 3-failure/15-min circuit breaker persisted in state, title sentiment (AI → lexicon fallback), per-symbol notes, daily report, weekly review, `health.ai_*` bookkeeping | `score_title(title)`, `note(sym_payload)`, `daily_report(payload)`, `weekly_review(payload)`, `breaker(state)` | §3.11, §8.3 |
| `engine/publish.py` | bake every published file from state (`data.json`, 9 symbol files, `orders.json`, `events.json`, `model-health.json`, `shadow.json`, `simple.html`), `engine.health` + heartbeat, git commit/push protocol | `bake_all(state, now, kind)`, `health(state, now)`, `heartbeat(state, red)`, `commit_and_push(now)` | §7, §8.4–8.5, §9.6 |

Mode pipelines (which module does what, in order) are in §9.4. Rough dependency order: `clock` ← `state` ← `datafeed` ← `indicators` ← `scoring` ← `forecast`/`broker` ← `autopilot`/`tuner`/`shadow` ← `ai` ← `publish`.

---

## 3. Data inputs

### 3.1 Watchlist (fixed)

Nine TWSE symbols in this fixed array order (= `rows[]` order; the viewer sorts by `total` itself): `2330.TW 台積電`, `2317.TW 鴻海`, `2454.TW 聯發科`, `2308.TW 台達電`, `2882.TW 國泰金`, `0050.TW 元大台灣50`, `6789.TW 采鈺`, `3481.TW 群創`, `2881.TW 富邦金`. `code` = bare code with leading zeros kept; `name` = the Chinese short name exactly as in the snapshot (`data.json → rows[].name`). The watchlist is a config file (`state/watchlist.json`), not code. `.TWO` (OTC) symbols are accepted by the viewer regex but have no T86 data (§3.7).

### 3.2 Source table

| # | Data | Host / request (shape) | Response fields used | Cadence | Cache file | On failure / degraded | Event |
|---|---|---|---|---|---|---|---|
| D1 | daily OHLCV, dividend-adjusted | Yahoo chart API `GET https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=3y&interval=1d&events=div,splits` (fallback host `query2`); browser `User-Agent`; equivalent to `yfinance.Ticker(sym).history(period="3y", auto_adjust=True)` which is what the float32 artefacts in the data point to (**medium** on mechanism) | `chart.result[0].timestamp[]`, `indicators.quote[0].{open,high,low,close,volume}`, `indicators.adjclose[0].adjclose[]`, `meta.regularMarketTime` | every run (scan uses it for the last-bar check; EOD for the final bar) | `state/cache/bars/<code>.json` (full history ≥ 500 bars) | timeout/non-200/malformed → keep cache; **degraded** (last date older than cache) → keep cache + `WARN data` | `{symbol} 本次最新日期 {new_last} 落後快取 {cache_last}(疑似劣化回應),保留舊快取` (verbatim); download error → `{symbol} 下載失敗({exc}),保留舊快取` (*default*) |
| D2 | intraday quote | same endpoint `range=1d&interval=1m` → last non-null close + its timestamp; or `meta.regularMarketPrice`/`regularMarketTime` | price, ts | every scan | in-memory | fall back to cached last close, `quote_fresh=false`, `ts` = scan time; no buys for that symbol (G1) | — |
| D3 | 60-minute bars | `range=1mo&interval=60m` | OHLC | every scan (for `intraday_kd`); EOD | `state/cache/bars60/<code>.json` | keep last `intraday_kd` | — |
| D4 | fundamentals | yfinance `Ticker.info` (Yahoo `quoteSummary` modules `financialData`, `summaryDetail`, `defaultKeyStatistics`; needs the crumb handshake yfinance implements) | `returnOnEquity`, `revenueGrowth`, `earningsGrowth`, `grossMargins`, `trailingPE` (fractions; PE plain) | once per trading day (EOD) | `state/cache/info/<code>.json` | keep cache; missing key → that metric is skipped (§4.4) | — |
| D5 | news | `GET https://news.google.com/rss/search?q={urlencoded name}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant` (query = Chinese short name, `0050` for the ETF — *default*, [05 §11 Q4]) | `item.title`, `item.link`, `item.pubDate`, `item.source` text | per symbol when the cached list is older than 30 min during scans, and at EOD | `state/cache/news/<code>.json` (items + score + refreshed_at) | keep cached items/score | `{code} 新聞更新失敗({exc}),沿用快取` (*default*, `WARN news`) |
| D6 | 三大法人 (chips) | `GET https://www.twse.com.tw/rwd/zh/fund/T86?date={YYYYMMDD}&selectType=ALL&response=json` → `fields[]` + `data[][]` strings with thousands commas | per code: foreign = `外陸資買賣超股數(不含外資自營商)` + `外資自營商買賣超股數`; `invtrust` = `投信買賣超股數`; `dealer` = `自營商買賣超股數`; `total` = `三大法人買賣超股數` (identity `total == foreign+invtrust+dealer` held on 90/90 published rows) — column names **medium**, verify at implementation | EOD (data is published after the close) | `state/cache/t86/<date>.json`; keep ≥ 60 trading days | keep cache; chips unchanged | `WARN data` `T86 下載失敗({exc}),沿用快取` (*default*) |
| D7 | index | `^TWII` via D1/D2 | last close, previous close, 5-day return, MA20/MA60 | every run | `state/cache/twii.json` | keep cache | — |
| D8 | morning brief inputs | `TSM` and `^SOX` via D2 (previous US session % change); TAIEX night session: no known source → `無資料` unless `TWQ_NIGHT_SYMBOL` is configured (*default*); macro news count: RSS D5 with `q=台股`, items published in the last 24 h (*default*, **low**) | pct changes, counts | 08:30 (or first scan) | — | `夜盤 無資料` form of the message | §8.2 `晨會:…` |
| D9 | ex-dividend calendar | `https://www.twse.com.tw/rwd/zh/exRight/TWT49U?response=json` (*default* path, verify) | rows for watchlist codes within 30 days | EOD | `state/calendar.json.events[]` | keep cache | `行事曆同步失敗({exc})` (*default*, `WARN engine`) |
| D10 | holidays | `https://www.twse.com.tw/rwd/zh/holidaySchedule/holidaySchedule?response=json` (*default* path, verify) + hand-maintained list | dates | Saturday job | `state/calendar.json.holidays[]` | keep list | — |
| D11 | AI | `api.anthropic.com` via the `anthropic` SDK; aliases `sonnet` → a current Claude Sonnet model id, `opus` → a current Claude Opus model id (configure in `state/engine.json.ai_models`); published names stay the aliases | text | §3.11 | — | §8.3 breaker | `AI 呼叫失敗(…)` |
| D12 | heartbeat | `GET $HEARTBEAT_URL` (OK) / `GET $HEARTBEAT_URL/fail` with body = red strings joined by `、` (healthchecks-style, **medium**) | — | EOD, Saturday job | — | never fatal | `心跳已送(…)` / `心跳送出失敗({exc})` (*default*) |

Retries: 3 attempts with backoff (1 s, 3 s, 9 s) for D1–D10; a failure never aborts the run — the step degrades as listed and the run continues to the bake.

### 3.3 Daily bars — details

* Keep the full fetched history (≥ 500 bars; first fetch `range=3y`) in the cache; **compute every indicator on the full history and publish the last 250 bars** (no warm-up `NaN` reaches the file: `ma60[0]`, `rsi[0..13]`, `k[8]` are all populated in the data) [04 §1.2]. MACD needs ≈ 240 pre-window bars to match the lost engine to 1e-6 at `bars[0]`, KD ≈ 70, RSI 14, MA60 59 [04 §2.7].
* Prices are dividend/split back-adjusted (whole history rescales after an ex-date; `bars[-1][4]` equals the unadjusted last close) [02 §3.3]. Store OHLC adjusted as the source delivers them (float32 artefacts like `104.94999694824219` are tolerated by the viewer; do not round bars).
* Volume = integer shares.
* Degraded-response guard (per symbol, each refresh): compare the response's last bar date with the cache's: newer → replace cache, mark "updated" (new `made_date`); equal → replace (values may be revised, e.g. the Friday bar finalised on Saturday); older → reject with the `WARN data` event [07 §7.1].
* The Friday bar is corrected by the 14:15 EOD (`14:15 EOD 會再以完整日K做最終校正`); the 13:33 `收盤定盤` scan re-prices with the exchange fixing (`其中 {k} 檔取得交易所定盤價`).

### 3.4 Quotes and `quote_fresh`

`rows[].price` = last quote; `rows[].ts` = time the quote was taken (scan time); `quote_fresh = market.is_open and (now − quote_time) ≤ 20 min` (*default*, [07 §7.2]); after the close `price` = last close and `quote_fresh=false` (the viewer then shows `延` with `延遲價(非交易所即時報價),擷取 HH:MM`). `positions[].price` uses the same quote. The bar used for indicators on an intraday scan is the cached daily history with today's bar replaced/appended from the quote (open/high/low/volume from `range=1d&interval=1m` aggregation; *default*, needed only for intraday `rec_code` flips).

### 3.5 Trading-day and holiday handling

A date is a trading day iff it is Mon–Fri, not in `state/calendar.json.holidays[]`, and (for scans) `^TWII` has a bar / `meta.regularMarketTime` dated today once the Taipei clock is ≥ 09:05 (retry once after 60 s before 09:05) — "no new bar ⇒ holiday" [08 §3.8]. A non-trading-day scan returns `skip` (no state write, no commit, no event). EOD always runs (records 0 predictions, heartbeat, bake). Observed non-bar weekdays in the data: 2026-09-25, 09-28, 10-09, 10-23, 10-26.

### 3.6 AI inputs (summary; rules in §8.3)

Callers and models: `news` → `sonnet` (title sentiment, ≤ 1 call per symbol per scan when the item list changed); `ai` → `opus` (9 per-symbol notes + daily report after EOD, weekly review Saturday); `tuner` → `opus` (one call per tuner run, optional candidate). Without `ANTHROPIC_API_KEY`: `engine.ai.enabled=false`, `health.ai_enabled=false`, no AI events, lexicon path for news, notes/report keep their last values.


---

## 4. Computation specs

### 4.1 Indicators (`symbol/<code>.json → indicators{}`) — all **high**, recomputed to ≤ 1e-11 on 9/9 files [04 §2]

Inputs: full cached history `H` with columns `open, high, low, close, volume` (adjusted prices). Rolling windows use `min_periods = n`. Publish `[-250:]` of each array, aligned with `bars[]` (`indicators.X[i]` ↔ `bars[i]`), 11 keys in this order: `ma5, ma20, ma60, bb_up, bb_low, rsi, macd, macd_sig, macd_hist, k, d`, floats at full repr.

```
ma_n[i]      = mean(close[i-n+1..i])                                  n ∈ {5, 20, 60}
sigma20[i]   = std(close[i-19..i], ddof=1)                            # pandas default ddof; ddof=0 is off by up to 35
bb_up[i]     = ma20[i] + 2.0·sigma20[i];   bb_low[i] = ma20[i] − 2.0·sigma20[i]
gain[i]      = max(close[i]−close[i-1], 0);  loss[i] = max(close[i-1]−close[i], 0)
rsi[i]       = 100 − 100/(1 + mean(gain[i-13..i]) / mean(loss[i-13..i]))   # Cutler/SMA RSI(14); Wilder is off 12–24 pts
               loss-mean 0 → 100.0; gain-mean = loss-mean = 0 → 50.0  [defaults, unobserved]
ema_s[i]     = ema_s[i-1] + 2/(s+1)·(x[i] − ema_s[i-1]), ema_s[0] = x[0]   # pandas ewm(span=s, adjust=False)
macd[i]      = ema_12(close)[i] − ema_26(close)[i]
macd_sig[i]  = ema_9(macd)[i]
macd_hist[i] = macd[i] − macd_sig[i]                                  # plain difference, NOT ×2
H9[i]        = max(high[i-8..i]);  L9[i] = min(low[i-8..i])            # bar highs/lows, not closes
rsv[i]       = (close[i] − L9[i]) / (H9[i] − L9[i]) · 100              # H9 == L9 → 50.0 [default]
k[i]         = (2/3)·k[i-1] + (1/3)·rsv[i]                            # pandas rsv.ewm(alpha=1/3, adjust=False); seed = first rsv
d[i]         = (2/3)·d[i-1] + (1/3)·k[i]
atr14[i]     = mean(TR[i-13..i]),  TR[t] = max(high[t]−low[t], |high[t]−close[t-1]|, |low[t]−close[t-1]|)   # §4.11
```

Edge facts: `rsi == 50.0` exactly when mean gain == mean loss is genuine; `(bb_up+bb_low)/2 == ma20`.

60-minute KD (`intraday_kd`): the same KD(9,3,3) recursion on the 60-minute bars of D3 (parameters **medium** — unobservable; the daily KD parameters are assumed), `k`/`d` published rounded to 1 dp, label rules in §4.7.

### 4.2 Technical signals (`signals[]`) and `tech_total` [04 §3–§5]

Item schema (key order): `{"indicator": str, "label": str, "score": float, "note": str}`; `score = round(base × weights[key], 2)` (per-signal rounding is load-bearing: 3481's `tech_total 1.37` = …+0.62, not 1.375→1.38). `tech_total = round(Σ score, 2)` — plain sum, no clipping. Evaluate on the last bar `i` (`c` = close, `c₋₁` previous close, `k₋₁/d₋₁` previous K/D). Emission order: `均線排列`, (`均線交叉` if it fires), `RSI`, `MACD` always; then `KD`, `布林通道`, `成交量` only when they fire (a silent group contributes 0).

| Group (weight key) | Condition | `label` | base | `note` (verbatim template; `%d` = `round()` to int, `%.1f` one decimal) | Confidence |
|---|---|---|---|---|---|
| `均線排列` (`ma_align`), always | `ma5 > ma20 > ma60` | `多頭排列` | +2.0 | `MA5>MA20>MA60,趨勢偏多` | high |
| | `ma5 < ma20 < ma60` | `空頭排列` | −2.0 | `MA5<MA20<MA60,趨勢偏空` | high |
| | otherwise | `糾結` | 0.0 | `均線糾結,方向不明` | high |
| `均線交叉` (`ma_cross`), conditional | `ma5₋₁ ≤ ma20₋₁ and ma5 > ma20` (same-day cross only) | `黃金交叉` | +1.0 | `MA5 上穿 MA20,短線轉強` | *default* (never observed; weight key exists) |
| | `ma5₋₁ ≥ ma20₋₁ and ma5 < ma20` | `死亡交叉` | −1.0 | `MA5 下穿 MA20,短線轉弱` | *default* |
| `RSI` (`rsi`), always | `rsi < 30` | `超賣` | +1.5 | `RSI=%d<30,跌深可能反彈` | high (base ±1.5 with w 0.5 — §6.1) |
| | `rsi > 70` | `超買` | −1.5 | `RSI=%d>70,漲多可能回檔` | score medium / note *default* |
| | else | `中性` | 0.0 | `RSI=%d` | high |
| `MACD` (`macd`), always | `macd_hist ≥ 0` | `紅柱` | +0.5 | `柱狀體在零軸上,動能偏多` | high (`== 0` → 紅柱 *default*) |
| | `macd_hist < 0` | `綠柱` | −0.5 | `柱狀體在零軸下,動能偏空` | high |
| `KD` (`kd`), if/elif, cross before zone | `k₋₁ ≥ d₋₁ and k < d` | `死亡交叉` | −1.5 | `K=%d 下穿 D=%d` (current K, D) | high |
| | `k₋₁ ≤ d₋₁ and k > d` | `黃金交叉` | +1.5 | `K=%d 上穿 D=%d` | medium / note *default* |
| | elif `k < 20` | `低檔` | +1.0 | `K=%d<20,低檔區` | high (test is on K only) |
| | elif `k > 80` | `高檔` | −1.0 | `K=%d>80,高檔區` | *default* |
| | else | nothing | | | high |
| `布林通道` (`bb`), conditional | `close < bb_low` | `觸下軌` | +1.0 | `跌破下軌,偏弱但可能超跌反彈` | high (close vs low indistinguishable; use close) |
| | `close > bb_up` | `觸上軌` | −1.0 | `突破上軌,偏強但可能過熱` | medium / note *default* |
| `成交量` (`volume`), conditional | `ratio ≥ 1.5 and close < c₋₁` | `帶量下跌` | −1.0 | `量為均量 %.1f 倍,量增價跌` | high (threshold ∈ (1.25, 1.55], *default* 1.5) |
| | `ratio ≥ 1.5 and close > c₋₁` | `帶量上漲` | +1.0 | `量為均量 %.1f 倍,量增價漲` | medium / note *default* |

`ratio = volume[i] / mean(volume[i-19..i])` (20 bars **including** today; reproduces 0050; 2308/2454 published ratios came from a realtime volume at scan time — *default*, [04 §3.3.6]). Boundary equalities: strict `<`/`>` for RSI, KD zones and bands; `≥ 0` for 紅柱; `≥ 1.5` for volume.

Weighted scores under v9 (`ma_align 1.5, ma_cross 1.0, rsi 0.5, macd 1.0, kd 0.5, bb 0.625, volume 1.5`): `±3.0, ±1.0, ±0.75, ±0.5, ∓0.75/±0.5, ±0.62, ±1.5`. Under v10 (§6.8): `±3.7, ±0.45, ±1.18, ±0.63, ∓0.37/±0.24, ±1.28, ±1.45`.

### 4.3 Market tilt (`overview.market`, `rows[].mkt_score`) and market state [05 §1]

```json
"market": {"is_open": false, "label": "收盤", "index": 45211.828125, "pct": -2.4941593686153634, "regime_label": "偏空震盪", "score": -0.5}
```

| Field | Rule |
|---|---|
| `index` | `^TWII` last close (or last intraday quote while open), unrounded |
| `pct` | `(index / previous_close − 1) × 100`, unrounded |
| `is_open` | `true` 09:00:00–13:30:00 Taipei on a trading day, else `false` (*default*) |
| `label` | `"盤中"` if `is_open` else `"收盤"` (the only two strings the viewer knows) |
| `regime_label` / `score` | from the raw daily label of `^TWII`'s last bar (same rule as §4.9 step 1): `range` and `close > ma20` → `偏多震盪` / `+0.5` (observed); `range` and `close < ma20` → `偏空震盪` / `-0.5` (observed); `bull` (`close > ma20 > ma60`) → `多頭` / `+1.0` (*default*, prose only); `bear` (`close < ma20 < ma60`) → `空頭` / `-1.0` (*default*); `close == ma20` → `盤整` / `0.0` (*default*). Emit `score` as a short literal (`-0.5`, `1.0`) — the viewer concatenates it raw |
| `rows[].mkt_score` | `= market.score` for every row when `use_market` else `0.0` |

Market **state** (gate G3, not additive): `halt` when 1-day `pct ≤ −2.0 %` or 5-day return `≤ −3.5 %` at EOD (*default* [05 §11 Q2]; event `市場狀態:halt(大盤單日 {pct:+.1f}%、5日 {pct5:+.1f}%)` observed as `市場狀態:halt(大盤單日 -2.5%、5日 -3.6%)`); `caution` set by the morning brief override (`風險覆蓋 caution` when 夜盤, TSM and 費半 are all negative, *default*; observed −1.4/−1.8/−1.4); otherwise `normal`. Event on state change only: `市場狀態:{state}(大盤單日 {pct}、5日 {pct})`. Effects in §5.5.

### 4.4 Fundamentals (`fund_signals[]`, `rows[].fund_total`) [05 §2]

Emission order `ROE`, `營收成長`, `盈餘成長`, `毛利率`, `本益比` (only those that fire); metric with a missing source field is skipped; if nothing fires emit the single placeholder. Scores 1 dp.

| `indicator` | Condition (fraction `x`) | `label` | `score` | `note` |
|---|---|---|---|---|
| `ROE` | `x ≥ 0.20` | `f"{x*100:.0f}%"` | `0.7` | `股東權益報酬率高,獲利能力強` |
| `ROE` | `0 < x < 0.20` | same | `0.3` | `ROE 尚可` |
| `營收成長` | `x ≥ 0.20` | same | `0.7` | `營收年增率高,成長強` |
| `營收成長` | `0 < x < 0.20` | same | `0.3` | `營收正成長` |
| `營收成長` | `x < 0` | same | `-0.5` | `營收衰退` |
| `盈餘成長` | `x > 0` | same | `0.4` | `獲利成長` |
| `盈餘成長` | `x < 0` | same | `-0.4` | `獲利衰退` |
| `毛利率` | `x ≥ 0.25` | same | `0.3` | `高毛利,具競爭力` |
| `本益比` | `pe > 50` | `f"{pe:.0f}"` (no `%`) | `-0.3` | `本益比偏高,評價偏貴` |
| `基本面` | nothing fired | `中性` | `0.0` | `基本面無明顯偏多或偏空訊號` |

Thresholds are **medium** (cuts bracketed: ROE (19 %, 24 %], revenue (19 %, 29 %], PE (30, 55]). `fund_total = round(clip(Σ score, −fund_cap, +fund_cap), 1)` with `fund_cap = 1.5` (**high**, e.g. 2330 Σ 2.1 → `1.5`; 2317 Σ 1.4000000000000001 → `1.4`). When `use_fundamentals` is false: `fund_signals = []`, `fund_total = 0.0`.

### 4.5 News (`news{}`, `rows[].news_total`) [05 §3]

* `items[]`: the first **8** feed entries in feed order (not time-sorted), each `{"title", "link", "source", "published", "sentiment", "score"}`; `published` = `pubDate` → Taipei ISO; `source` = RSS `<source>` text.
* Per-item `score`: integer in [−3, +3] emitted as float (`-2.0`); `sentiment` = `"pos"` if `score > 0`, `"neg"` if `< 0`, `"neu"` if `== 0` (142/142). Scorer: AI title classification with `sonnet` asking for one integer −3…+3; fallback lexicon (*default*, the original lexicon is lost): `跌停 −2, 重挫 −2, 慘跌 −2, 崩 −2, 砍目標價 −1, 虧損 −1, 下殺 −1, 創新高 +2, 漲停 +2, 大賺 +1, 買點 +1, 利多 +1`, summed and clipped to ±3.
* Aggregate `news.score` (= `rows[].news_total`, 2 dp): **not fully determined** (best single formula fits 10–11/18 cases; Σ/6 is the backbone). *Default:* `round(Σ_i w_i·s_i / 6, 2)` with `w_i = 0.5 ** (age_hours_i / 24)` measured from the refresh time, over the ≤ 8 kept items, clipped to ±3.
* Refresh is independent of the scan: `news_total` is overwritten whenever refreshed while `total`/`rec_code` stay as computed at the last scan (observed in Aug) — reproduce this: recompute `total` only in a scan, write `news_total` whenever refreshed.
* Event when `|score| ≥ 1.0` after a refresh (**medium**): `{code} {name} 消息面偏空 {score:+.1f}({n} 則)` (observed) / `{code} {name} 消息面偏多 {score:+.1f}({n} 則)` (*default* wording).
* Missing/empty → `{"score": 0.0, "items": []}`.

### 4.6 Chips / 三大法人 (`chips{}`, `rows[].chips_total`) [05 §4]

* `recent[]`: last 10 trading days newest first, `{"date", "foreign", "invtrust", "dealer", "total"}` ints in shares; engine keeps ≥ 60 days for the rules. `.TWO` symbols or no data → `{"score": 0.0, "signals": [], "recent": []}`.
* `signals[]` order `外資動向`, `投信動向`, `法人動能`:

| `indicator` | Rule (newest day backwards) | `label` | `score` | `note` |
|---|---|---|---|---|
| `外資動向` | streak `n` of days with `foreign > 0`, `n ≥ 5` | `外資連買{n}日` | `1.5` | `外資連續 {n} 個交易日買超` |
| `外資動向` | `3 ≤ n < 5` (**medium**, prose only) | same | `1.0` | same |
| `外資動向` | streak of `foreign < 0`, `n ≥ 5` / `3 ≤ n < 5` | `外資連賣{n}日` | `-1.5` / `-1.0` | `外資連續 {n} 個交易日賣超` |
| `投信動向` | all of the last 5 days `invtrust > 0` / all `< 0` (a 0 day breaks it, *default*) | `投信買超` / `投信賣超` | `0.5` / `-0.5` | `近 5 日投信買賣超同向(無反向日)` |
| `法人動能` | `z ≥ +1` / `z ≤ −1`, `z` = (sum of last 3 `total` − mean of rolling 3-day sums over the last 60 trading days) / std of those sums (**medium**) | `法人買盤動能` / `法人賣壓動能` | `0.5` / `-0.5` | `近 3 日三大法人合計 z 分數 {z:+.2f}(相對近 60 日)` |

`chips.score = round(clip(Σ signals[].score, −1.5, +1.5), 1)` (**high**: 0050-Aug 1.5+0.5 → `1.5`). Streaks of ≤ 2 days emit nothing.

### 4.7 60-minute KD (`intraday_kd{}`, `rows[].kd60`, `rows[].kd60_total`) [05 §5]

`{"score": s, "k": round(k,1), "d": round(d,1), "label": L, "note": f"60分K線 K={k_raw:.0f} D={d_raw:.0f}"}` (note formatted from the **unrounded** values). Labels: `低檔` `+0.3` when `K < 20` and no fresh cross; `低檔黃金交叉` `+0.5` when `K < 20` and K crossed above D on the latest bar; `高檔` `-0.3` (`K > 80`) and `高檔死亡交叉` `-0.5` (*default*, unobserved); otherwise `中性` `0.0`. `rows[].kd60` = the same object without `score`; `rows[].kd60_total = score`.

### 4.8 Composition: `total` → `rec_code`, `changed`, persistence [05 §0, §6]

```
total    = round(tech_total + mkt_score + fund_total + news_total + chips_total + kd60_total, 1)   # 9/9 exact
rec_code = STRONG_BUY  if total ≥ strong_th (5.0)
         = BUY         if buy_th (3.0) ≤ total < strong_th            # 3.0 → BUY (inclusive)
         = STRONG_SELL if total ≤ strong_sell_th (−5.0)
         = SELL        if strong_sell_th < total ≤ sell_th (−3.0)     # −3.1 → SELL, −2.8 → HOLD
         = HOLD        otherwise
rec_text = {STRONG_BUY: 強力買進, BUY: 買進, HOLD: 觀望, SELL: 賣出, STRONG_SELL: 強力賣出}[rec_code]
changed  = rec_code != rec_code at the previous scan of this symbol   (true only on the flipping scan)
```

Comparison on the published 1-dp `total`. Every scan recomputes `rec_code`; on each flip log `{code} {name}:{old rec_text}→{new rec_text}` (INFO `engine`, one line per symbol in row order). `strong_th = buy_th + strong_gap`, `strong_sell_th = sell_th − strong_gap` (`strong_gap 2.0`). Persistence for buys (gate G4, §5.5): the previous trading day's **EOD** `total ≥ buy_th` as well.

### 4.9 Trend segments, summary, per-symbol `regime` [02 §9]

Computed on the served 250-bar window (reproduces 9/9):

1. Raw daily label for bar `i`: `bull` if `close > ma20 > ma60`; `bear` if `close < ma20 < ma60`; else `range`.
2. Single left-to-right pass over runs of equal raw label: a run **shorter than 5 bars** adopts the label of the bar immediately before it (which may itself have been relabelled); the first run is kept; runs ≥ 5 bars start a new segment.
3. Merge consecutive equal labels → `segments[] = {"start", "end", "regime", "ret"}` with `ret = round(close[end]/close[start] − 1, 4)`; segments tile the window (`start` of the next = next bar after `end`).

`summary = {"regime": raw label of the LAST bar (not the last segment's), "slope20/60/120": OLS slope of log(close) over the last N bars × 252 × 100, 2 dp, "dist_ma60": round(close[-1]/ma60[-1] − 1, 4), "high_252"/"low_252": max/min close over the trailing 252 closes of the full history, 2 dp (*default* 252), "pos_252": round((close[-1] − low)/(high − low), 4)}`. `rows[].regime = summary.regime` ∈ `bull | bear | range` (viewer chips `多頭`/`空頭`/`盤整`); it does not feed `total` or sizing.

### 4.10 Forecasts, ledger, model health [07 §1–§2]

**baseline** (random walk, **high**, exact to 1e-16): `σ = std(ddof=1)` of the last 20 simple daily returns `close.pct_change().tail(20)`; for `h ∈ (1, 5, 20)`: `pred_ret = 0.0`, `prob_up = 0.5`, `ci68 = [−σ√h, +σ√h]`, `ci95 = [−1.96σ√h, +1.96σ√h]` (1.96 exactly), unrounded.

**ridge** (shape **high**, internals lost): `ci68 = [pred − s_h, pred + s_h]`, `ci95 = pred ± 1.96 s_h`, `prob_up = Φ(pred_ret / s_h)` (27/27 to 6 dp). *Default internals* [07 §8 Q1]: per symbol per horizon, ridge regression (`α = 1.0`) on the last 250 bars with features {1-, 5-, 20-day returns, RSI14, MACD hist, K, D, BB %b, 20-day volume ratio}, target = forward `h`-day simple return, `s_h` = residual std; name must stay `"ridge"`.

**fan** (21 points, **high**): `dates = pd.bdate_range(made_date, periods=21)`; `median[i] = base_price·exp(np.interp(i, [0,1,5,20], [0, ln(1+pred_1), ln(1+pred_5), ln(1+pred_20)]))`; `lo68/hi68/lo95/hi95` likewise with the band edges (log-linear interpolation between the knots).

**Published forecast** = the `champion["5"]` model for all three horizons (Aug: all `ridge` while only h=5's champion was ridge; **medium-high**); `made_date = bars[-1][0]`, `base_price = bars[-1][4]`; recomputed at every bake from the latest bars; `rows[].forecast5 = {pred_ret, prob_up, ci68_lo, ci68_hi, model}` of the h=5 entry.

**Ledger** (`state/predictions.jsonl`), key `(symbol, model, horizon, made_date)`:
* Record at EOD for every symbol that received a new bar: 9 × 2 models × 3 horizons = **54** rows (`記錄 54 筆預測`); 0 when no new bar; idempotent upsert.
* Resolve: `target bar = bar index of made_date + h`; `realized = close[target]/close[made] − 1` (simple); `abs_err = |pred_ret − realized|`; `hit = (pred_ret ≥ 0) == (realized ≥ 0)` (`≥` verified). Store `realized/abs_err/hit` **at resolution and never recompute** (bars re-adjust later). *Default (deviation from the lost engine, which orphaned forecasts whose target day a symbol missed):* resolve **every** pending row whose target bar exists; count → `兌現 {r} 筆`.
* Per-symbol `ledger.by_horizon[]` = `{model, horizon, n, mae (unrounded), hit_rate (unrounded)}` ordered `(horizon asc, model asc)`; rows with `n = 0` omitted (*default*).
* `metrics.by_model_horizon[]` = same over all symbols, `mae` 6 dp, `hit_rate` 4 dp.
* `metrics.series[]` = groups keyed by **the Monday of the ISO week containing the target bar date** (resolution week — **high**: week 2026-10-26 has h=20 rows that could not have been created that week; the 2026-08-03 row reproduces exactly on target dates), `(date asc, model asc, horizon asc)`, `{date, model, horizon, mae (6 dp), hit_rate (4 dp), n}`; rebuilt from the ledger at every bake; no `n=0` rows.
* `metrics.champion = {"1": m, "5": m, "20": m}` (string keys): the model with the lower `mae` in `by_model_horizon` when `n ≥ 30` (*default* threshold), else `baseline`.
* `model_health_brief = {"hit_rate_5d": champion-5 row hit_rate, "mae_5d": its mae, "n_resolved": Σ by_model_horizon[].n (both models, all horizons; 3408 in Oct), "champion": champion["5"]}`.
* Quality-drop trigger (after a trading-day EOD, *default* thresholds [07 §8 Q7]): `hit5 < 0.40 and mae5 / mae_ref > 1.5`, `hit5/mae5` = champion 1-day forecasts over the last 5 trading days, `mae_ref` = trailing 60-day MAE → event `偵測到預測品質下降(命中率 {hit5*100:.0f}%,MAE 惡化 {(mae5/mae_ref−1)*100:.0f}%),自動觸發調參` then a tuner run (§6).

### 4.11 `suggest_qty` and ATR [05 §8, 06 §5.1] — **high**, 18/18 rows

```
atr14       = SMA_14(TR) on the daily bars including the latest bar (§4.1)
q_risk      = risk_frac × strong_mult × cash / atr14        # v9: 0.005 × 1.5 = 0.0075 (constant pinned to [0.007497, 0.007505])
q_cap       = 0.30 × cash / price                           # 30 % of CASH (not equity), pinned to [0.29999, 0.30036)
suggest_qty = floor(min(q_risk, q_cap))                     # shares; may be 0
```

`cash = account.cash`, `price = rows[].price`. The published value is the strong-signal (×`strong_mult`) size regardless of `rec_code` (*default* interpretation, reproduces all rows). Viewer: BUY/STRONG_BUY rows show `(qty×price/equity×100).toFixed(1)%`.


---

## 5. Paper-trading rules (decision tables) [06, 03 §1]

### 5.1 Account model

| Field | Definition | Confidence |
|---|---|---|
| `initial_cash` | `1000000.0`; the account was reset to exactly 1 000 000 cash / no positions on 2026-08-05 (orders 17→26 replay to the Aug cash to the cent) | high |
| `cash` | running float: BUY `cash −= qty×filled_price + fee`; SELL `cash += qty×filled_price − fee − tax` | high |
| `positions_value` | `Σ positions[].value`, `value = qty × price` | high |
| `equity` | `cash + positions_value` (float sum) | high |
| `realized_pnl` | cumulative `Σ pnl` of every SELL since the reset, unrounded (`-23213.919999999875`) | high |
| `unrealized_pnl` | `Σ qty × (price − avg_price_2dp)` using the **emitted 2-dp** `avg_price` (exact in both bakes; the unrounded average is off by a few NTD) | high |

Rebuild seed: `cash 269729.55000000005`, `realized_pnl -23213.919999999875`, the 4 positions of the snapshot with their unrounded averages re-derived from `orders.json` where the lot is in-window (otherwise seed `avg` from the 2-dp value), `peak` as published.

### 5.2 Broker (fills, fees, tax, cost basis, pnl) — all **high**, 60/60 orders

| Quantity | Formula |
|---|---|
| `price_hint` | the quote the decision was made on, 2 dp |
| `filled_price` | BUY `round(price_hint × 1.0005, 2)`; SELL `round(price_hint × 0.9995, 2)` (deterministic 5 bp slippage) |
| `gross` | `qty × filled_price` |
| `fee` | `max(20, round(gross × 0.001425 × 0.6))` (0.1425 % × 60 % discount, NT$20 minimum), stored as float with integer value |
| `tax` | SELL `round(gross × 0.003)`; BUY `0.0` |
| cost basis | fee-inclusive, **unrounded** internally: on BUY `cost += gross + fee; qty += q; avg = cost/qty`; on SELL the remaining lot keeps `avg` (exits sell everything anyway) |
| `pnl` (SELL) | `gross − fee − tax − qty × avg_unrounded`, **unrounded**; BUY → `null` |
| `created_at == filled_at` | scan time, second precision; up to 3 orders share a second |
| `status` | `FILLED` (paper fills are immediate); `REJECTED` rows with `filled_price:null, filled_at:null, fee:0.0, tax:0.0, pnl:null, note:<reason>` for KILL/risk-cap rejections (*default*); never `PENDING`/`CANCELLED` |
| `source` | `"autopilot"` for engine orders; `"manual"` for operator orders (*default*) |
| `mode` | `"paper"` |

Broker events (INFO `broker`, same second as the order): BUY `紙上買單成交:{code} {name} {qty} 股 @ {filled_price:.2f},手續費 {fee:.0f} 元,總支出 {round(gross+fee):,} 元。`; SELL `紙上賣單成交:{code} {name} {qty} 股 @ {filled_price:.2f},手續費 {fee:.0f} 元,證交稅 {tax:.0f} 元,已實現損益 {round(pnl):+,} 元。` (`qty` without thousands separator; money totals with).

Order `note` templates (`{s}` = `{total:+.1f}`, prices 2 dp; `{sp}`/`{tp}` = `round(stop_pct×100)`/`round(trail_pct×100)` of the active params → `8`/`12` under v9, `8`/`21` under v10):

| Situation | `note` |
|---|---|
| BUY opening | `訊號進場({rec_text},評分 {s})` |
| BUY adding | `訊號加碼({rec_text},評分 {s})` |
| SELL stop-loss | `觸發停損:現價跌破進場價 -{sp}%({stop_price:.2f})` |
| SELL trailing | `觸發移動停利:從高點 {peak:.2f} 回落 -{tp}%({trail_price:.2f})` |
| SELL both | the two above joined with `;` (stop first) |
| SELL rotation | `換股:讓位給 {code} {name}(評分差 {d:+.1f})` with `d = score_new − score_sold` |
| SELL signal exit | `訊號出場({rec_text},評分 {s})` (*default*; unobserved) |

### 5.3 Positions (`overview.positions[]`)

| Field | Rule |
|---|---|
| `qty` | int shares, odd lots allowed |
| `avg_price` | `round(avg_unrounded, 2)` |
| `price`, `value` | last quote; `qty × price` |
| `ret_pct` | `round((price/avg_unrounded − 1) × 100, 2)` |
| `peak` | running max of every price the position was marked at: `peak = max(peak, filled_price)` on each BUY and `peak = max(peak, price)` at every scan while held; reset when fully closed (**medium-high**: peaks sit between daily closes and daily highs; 2317 re-entry restarted at 245.62/246.0) |
| `stop_price` | `round(avg_unrounded × (1 − stop_pct), 2)` |
| `trail_price` | `round(peak × (1 − trail_pct), 2)` |
| `verdict` | `"hold"` normally; `"exit"` (*default*; CSS class `verdict-exit`, badge `該賣`) when an exit condition holds and the autopilot did not sell (KILL/autopilot off) |
| `reasons` | `[]`; for `exit` *default* strings `跌破停損價 {stop:.2f}`, `回落至移停價 {trail:.2f}`, `建議轉賣出` |

Array order: insertion order of the first fill, which in both bakes is code-ascending (`2317, 2330, 2881, 2882`); keep insertion order.

### 5.4 Per-scan decision table (run after quotes/scores are refreshed; `orders_left = 3`)

| Step | Condition | Action | Conf. |
|---|---|---|---|
| 0 | `engine.kill` or `autopilot == false` | place nothing; still update `peak/stop/trail/verdict/reasons` | high |
| 1 | every held symbol | `peak = max(peak, price)`; `stop = round(avg×(1−stop_pct), 2)`; `trail = round(peak×(1−trail_pct), 2)` | high |
| 2 | held and `price ≤ stop` and/or `price ≤ trail` (inclusive; `440.0 ≤ 440.00` fired) | SELL **all** @ `round(price×0.9995, 2)`; note per §5.2 (both → joined `;`); `realized += pnl`; `orders_left −= 1`; evaluated at every scan incl. the 09:00 open and 13:30 slots | high |
| 3 | held and `rec_code ∈ {SELL, STRONG_SELL}` | SELL all, note `訊號出場(…)` | medium |
| 4 | market state `halt`, or `quote_fresh == false` for the symbol (G1) | skip buys (all / that symbol); G1 event `閘門攔截 {code} 買進:G1:報價過期({age} 分)` (*default* text) | medium / low |
| 5 | candidates = symbols with `rec_code ∈ {BUY, STRONG_BUY}` and previous trading day's EOD `total ≥ buy_th`; otherwise log `閘門攔截 {code} 買進:G4:{prev_date} 收盤評分 {prev_total:+.1f} 未達 buy_th {buy_th:+.1f},訊號未跨日持續` and drop; process candidates in **descending `total`** (tie → watchlist order); the queue drains over successive scans because of the cap | | high |
| 6 | candidate **not held**, and `min(total of held) ≤ total_candidate − strong_gap (2.0)` (*default* gap; observed 2.1/2.3/5.0), not cash-conditional, at most one swap per scan | SELL the lowest-scored holding entirely, note `換股:讓位給 {code} {name}(評分差 {d:+.1f})`, event `自動換股:賣出 {code} {name}(評分 {s:+.1f})讓位給 {code2} {name2}(評分 {s2:+.1f})`; then continue with step 8 for the candidate using the post-sale cash | medium |
| 7 | candidate held and (state `caution` → log `閘門攔截 {code} 買進:G3:市場 caution(晨會覆蓋:隔夜情勢(caution)),禁加碼`; or already added once today) | skip (adds: at most **one add per symbol per day**; entry + one add on the same day is allowed) | high |
| 8 | sizing (§5.6) → `qty ≥ 1` | BUY @ `round(price×1.0005, 2)`; note `訊號進場(…)` if new else `訊號加碼(…)`; update `avg` (fee-inclusive), `peak = max(peak, filled_price)`; `orders_left −= 1`; stop when `orders_left == 0` | high |
| 9 | end of scan | bake `positions[]`, `account`, `orders.json` (last 50), events | high |

Re-entry after an exit is allowed on any later scan (next-day re-entries observed; same-day never observed — *default* allowed). No cash reserve (cash fell to 547 NTD); no position-count limit below the watchlist size; single position ≤ 40 % of equity (`單一持股 ≤ 權益 40%`, autopilot text; never observed binding) — cap `qty` so `(pos_value + qty×price) ≤ 0.40 × equity`.

### 5.5 Gates summary

| Gate | Trigger | Effect | Message |
|---|---|---|---|
| KILL | `engine.kill` (file `state/KILL` exists) | no orders at all; viewer badge `KILL 已啟動 — 下單全面封鎖` | — |
| G1 freshness | stale/missing quote | no buy of that symbol | *default* `閘門攔截 {code} 買進:G1:報價過期({age} 分)` |
| G2 | reserved (never seen) | — | — |
| G3 market | `caution` (morning override) | adds blocked; new entries sized × `caution_scale` | `閘門攔截 {code} 買進:G3:市場 caution(晨會覆蓋:隔夜情勢(caution)),禁加碼` |
| halt | EOD market state `halt` | no buys at all; exits still run (*default*: no buys also while `market.score ≤ −1.0`) | `市場狀態:halt(大盤單日 {pct}、5日 {pct})` |
| G4 persistence | previous EOD `total < buy_th` | no buy | `閘門攔截 {code} 買進:G4:{date} 收盤評分 {s:+.1f} 未達 buy_th {th:+.1f},訊號未跨日持續` |

### 5.6 Sizing of autopilot orders (**medium**, 24/50 exact; the formula is literally what the UI promises: `按建議部位 %`)

```
atr_pct = atr14 / close[-1]                                     (previous close at the time of the scan)
f       = min(0.30, risk_frac × (strong_mult if rec_code == STRONG_BUY else 1.0) / atr_pct)   # strong_mult applied BEFORE the 0.30 cap
if market state == caution: f ×= caution_scale                  # AFTER the cap (order 108: floor(0.15 × 317175.21 / 245.5) = 193 exact)
qty     = floor(f × cash_now / price_hint)                      # cash updated order by order inside the scan
qty     = max(1, qty) if cash_now ≥ price_hint × 1.0005         # orders 62, 98 filled 1 share where the formula gave 0
qty     = min(qty, floor((0.40 × equity − pos_value) / price_hint))   # 40 % single-position cap
if qty ≥ 1000: qty −= qty % 1000                                # round lots (low: order 18 = 2000 vs 2463)
```

Known residual: 26/50 historical BUYs deviate (17 filled at the full 30 % cap in low-cash states, 4 large-cash entries at f ≈ 0.2245); accepted (§10.2 Q-S1).

### 5.7 Exit and swap evidence (for the record)

Stops: `price_hint ≤ stop` (50.0 ≤ 50.06; 4210 ≤ 4243.32; 1660 ≤ 1666.03). Trails: `price_hint ≤ trail` inclusive (440.0 ≤ 440.00; 4725 ≤ 4725.60). Exits always sell the whole position (10/10). Swaps observed: 2882 (+2.0) → 6789 (+4.1), 2317 (+1.5) → 2454 (+3.8), 0050 (−2.0) → 2317 (+3.0, cash 152 k, so not cash-conditional). Exits and the replacement buy share the same second (`先出場 … 再進場`).

---

## 6. Parameters: v9, shadow genes, v10 adoption, sealing the shadow

### 6.1 Params object

```
{"buy_th": float, "strong_th": float, "sell_th": float, "strong_sell_th": float,
 "weights": {"ma_align", "ma_cross", "rsi", "macd", "kd", "bb", "volume"},
 "fund_cap": 1.5, "use_market": true, "use_fundamentals": true,
 "exit": {"stop_pct": float, "trail_pct": float},
 "sizing": {"risk_frac", "strong_mult", "caution_scale", "persistence"}}      # new key from v10 on (see 6.5)
```

Base scores live in code (§4.2: `ma_align ±2, ma_cross ±1, rsi ±1.5, macd ±0.5, kd ±1.5 cross / ±1.0 zone, bb ±1.0, volume ±1.0`); weights live in params; the published signal score is `round(base × weight, 2)`. **Resolution of the RSI ambiguity** [04 §4.3]: the last adopted row (id 12, v9) has `rsi 0.5` and the published RSI score `0.75` = 1.5 × 0.5; `params_history[0]` (id 25, `rsi 0.25`) is a rejected challenger. Base ±1.5 / weight 0.5 is the live pair. Under v10 the RSI score becomes `round(1.5 × 0.7840884945834798, 2) = 1.18`.

### 6.2 Active v9 (`params_history` id 12, adopted 2026-08-19T14:16:14+08:00) — exact `params_json` string

```
{"buy_th": 3.0, "strong_th": 5.0, "sell_th": -3.0, "strong_sell_th": -5.0, "weights": {"ma_align": 1.5, "ma_cross": 1.0, "rsi": 0.5, "macd": 1.0, "kd": 0.5, "bb": 0.625, "volume": 1.5}, "fund_cap": 1.5, "use_market": true, "use_fundamentals": true, "exit": {"stop_pct": 0.08, "trail_pct": 0.12}}
```

SAFE constants (not in `params_json` since v5; "安全參數自此移出調參搜索空間(tuner SAFE_*)"): `risk_frac 0.005`, `strong_mult 1.5`, `caution_scale 0.5`, `persistence 2.0`, `strong_gap 2.0`, order cash cap `0.30`.

### 6.3 Shadow genes (`shadow.json → genes[]`, fixed order; A = incumbent-v6, B = risk-exit-consensus) — exact values

| gene | A | B | differs |
|---|---|---|---|
| `w_ma_align` | `1.0` | `1.8490543082236912` | true |
| `w_ma_cross` | `1.0` | `0.45138791133375156` | true |
| `w_rsi` | `1.0` | `0.7840884945834798` | true |
| `w_macd` | `1.0` | `1.2517538359316402` | true |
| `w_kd` | `0.5` | `0.24447732513006493` | true |
| `w_bb` | `1.25` | `1.2827766433755723` | true |
| `w_volume` | `1.5` | `1.4532856064819977` | true |
| `buy_th` | `3.0` | `3.0` | false |
| `strong_gap` | `2.0` | `2.0` | false |
| `sell_th` | `-3.0` | `-3.0` | false |
| `stop_pct` | `0.08` | `0.08300581937609232` | true |
| `trail_pct` | `0.12` | `0.206062542287206` | true |
| `risk_frac` | `0.005` | `0.008025956907855073` | true |
| `strong_mult` | `1.5` | `1.487336088988674` | true |
| `caution_scale` | `0.5` | `0.5500015169427086` | true |
| `persistence` | `2.0` | `2.0` | false |

Arm A equals v6's `weights` (`ma_align 1.0, ma_cross 1.0, rsi 1.0, macd 1.0, kd 0.5, bb 1.25, volume 1.5`) — same scale as `params_json.weights`, so B's `w_*` map 1:1.

### 6.4 Gene → `params_json` key mapping

| gene | key | v10 value |
|---|---|---|
| `w_ma_align … w_volume` | `weights.ma_align … weights.volume` | B values verbatim |
| `buy_th` | `buy_th` | `3.0` |
| `buy_th + strong_gap` | `strong_th` | `5.0` |
| `sell_th` | `sell_th` | `-3.0` |
| `sell_th − strong_gap` | `strong_sell_th` | `-5.0` |
| `stop_pct` | `exit.stop_pct` | `0.08300581937609232` |
| `trail_pct` | `exit.trail_pct` | `0.206062542287206` |
| `risk_frac`, `strong_mult`, `caution_scale`, `persistence` | `sizing.*` (new key appended **after** `exit`, so existing key order is untouched; the viewer parses only `buy_th`, `stop_pct`, `trail_pct`) | B values verbatim |
| — (no gene) | `fund_cap 1.5`, `use_market true`, `use_fundamentals true` | kept at v9 |

### 6.5 v10 — exact `params_json` to adopt (byte-exact `json.dumps(params)` output, verified to round-trip)

```
{"buy_th": 3.0, "strong_th": 5.0, "sell_th": -3.0, "strong_sell_th": -5.0, "weights": {"ma_align": 1.8490543082236912, "ma_cross": 0.45138791133375156, "rsi": 0.7840884945834798, "macd": 1.2517538359316402, "kd": 0.24447732513006493, "bb": 1.2827766433755723, "volume": 1.4532856064819977}, "fund_cap": 1.5, "use_market": true, "use_fundamentals": true, "exit": {"stop_pct": 0.08300581937609232, "trail_pct": 0.206062542287206}, "sizing": {"risk_frac": 0.008025956907855073, "strong_mult": 1.487336088988674, "caution_scale": 0.5500015169427086, "persistence": 2.0}}
```

**Rounding policy for `stop_pct`/`trail_pct` (decision): store and use the full-precision floats `0.08300581937609232` and `0.206062542287206`; round only for display.** Reasons: (1) the shadow validated exactly these numbers and "B adopted as-is" is the content of the manual cut-over; (2) byte parity between `genes[].b`, the sealed `shadow.json`, the `params_json` tooltip and the v10 row — any rounding would make the record disagree with the experiment it cites; (3) Python's `repr` round-trips them exactly and the viewer prints them with its own formatting (`fmtGene` → `8.30%`/`20.61%`, params summary `停損8% 移停21%` via `Math.round`); (4) the economic difference of rounding (≤ 0.006 % of price on a stop line) is nil, so there is no benefit to offset the record mismatch. Display rules that follow from it: order notes print `-{round(stop_pct×100)}%` = `-8%` and `-{round(trail_pct×100)}%` = `-21%`; `simple.html`'s legend prints `跌破停損價(-8%)或從高點回落至移停價(-21%)`; the `reason` text below prints 2 dp (`8.30%`/`20.61%`). Stop/trail prices are computed with the full floats: `stop = round(avg × 0.9169941806239077, 2)`, `trail = round(peak × 0.793937457712794, 2)`.

Policy conflict resolved: the v5 note froze the SAFE exits at 8 %/12 % "不再由任何回測決定". The owner's instruction is to adopt arm B, whose safety leg passed (MDD 3.99 % vs 5.88 %) over 55 trading days; so v10 takes B's exits and the `reason` says so explicitly, while the SAFE constants stay outside the tuner's search space (the tuner never writes `exit` or `sizing`; §6.9).

### 6.6 `params_history` row for v10 (prepend as `params_history[0]`; `active_version = 10`; `engine.params_version = 10`)

```
{"id": 26, "adopted_at": "<cut-over time, e.g. 2026-11-01T12:00:00+08:00>", "version": 10,
 "params_json": "<the exact string of 6.5>",
 "train_metric": null, "valid_metric": null, "champion_metric": null, "adopted": 1,
 "reason": "手動採用:影子對照 B 臂(risk-exit-consensus)勝出——55 個交易日(2026-08-07~2026-10-29)報酬 +13.21% 對 A 臂 +3.29%(差 +9.92pp),最大回撤 3.99% 對 5.88%,滑價 11.65bp 對 10.66bp,四腿全數通過,人工提前結案採用 B 臂基因為正式參數。出場保護改為停損 8.30%/移動停利 20.61%(影子驗證值);安全參數仍不進入調參搜索空間。"}
```

Event (INFO, source `tuner`, same second): `調參採用新參數 v10:` + the `reason` string. The viewer renders the row `v10 ●`, `是`, `— — —`, reason, and the summary `buy_th=3 停損8% 移停21%`. The numbers come from `shadow.json` (`legs.return.ret_b 0.132083 / ret_a 0.032851 / diff 0.099232`, `legs.safety.mdd_b 0.0399 / mdd_a 0.0588`, `legs.realization.slip_bp_b 11.65 / slip_bp_a 10.66`, `progress.n_days 55`, `rows[0].date 2026-08-07`, `rows[-1].date 2026-10-29`). This single wording supersedes the two drafts in [07 §3.6] and [08 §1.8]; the verdict `next` text in 6.7 is made consistent with it.

### 6.7 Sealing `shadow.json` (manual verdict in favour of B)

Keep every other field frozen at the last bake (rows 55, legs, stats, turnover, trades 50/43, holdings, genes, `arms`, `closeout`, `start_date`, `mode`, `initial_cash`, `schema 1`, `state_key`, `chain_ok true`, `freeze_ok true`, `warnings []`, `generated_at 2026-10-30T14:50:28+08:00` unchanged, `active true`). Change only:

```json
"progress": {"n_days": 55, "closed_b": 2, "ready": true, "capped": false},
"verdict": {"adjudicated": "2026-11-01 手動採用", "pass": true, "capped": false,
            "next": "採用 B(risk-exit-consensus)為正式參數 v10;影子對照結案",
            "kind": "manual", "winner": "b", "sealed_at": "<same cut-over time as 6.6>", "sealed_by": "operator",
            "n_days": 55, "closed_b": 2,
            "legs_at_seal": {"operational": true, "safety": true, "return": true, "realization": true},
            "reason": "主機損毀、引擎重建;影子窗 55/60 交易日四腿全過(B−A +9.92pp,MDD B 4.0% vs A 5.9%,滑價 11.65bp vs 10.66bp),人工提前結案採用 B"},
"verdict_sealed": true, "computing": false, "refresh_failed": false
```

Renders as `裁決(2026-11-01 手動採用):通過 → 採用 B(risk-exit-consensus)為正式參數 v10;影子對照結案` above the frozen tables. Rules from the renderer: `verdict` must be an object; `pass` boolean; `capped` must be `false` (else the banner adds `(120 日硬上限)`); never set `active:false` (blanks the tab); never put the explanation in `warnings[]` (renders with `⚠`). Companion event (INFO `engine`): `影子對照裁決:B 組勝出,手動採用(第 55/60 交易日,B 平倉 2/10);risk-exit-consensus 升為正式參數 v10`. After sealing, the daily job skips the shadow step and never rewrites `shadow.json`.

### 6.8 Derived v10 numbers (for tests)

| Quantity | v9 | v10 |
|---|---|---|
| `均線排列` score | ±3.0 | ±3.7 (`round(2×1.849…, 2)`) |
| `均線交叉` | ±1.0 | ±0.45 |
| `RSI` | ±0.75 | ±1.18 |
| `MACD` | ±0.5 | ±0.63 |
| `KD` cross / zone | ∓0.75 / ±0.5 | ∓0.37 / ±0.24 |
| `布林通道` | ±0.62 | ±1.28 |
| `成交量` | ±1.5 | ±1.45 |
| sizing constant `risk_frac×strong_mult` | 0.0075 | 0.011937295357720796 |
| `caution_scale` | 0.5 | 0.5500015169427086 |
| stop / trail multipliers | 0.92 / 0.88 | 0.9169941806239077 / 0.793937457712794 |
| note literals | `-8%` / `-12%` | `-8%` / `-21%` |
| thresholds | 3/5/−3/−5 | unchanged |

### 6.9 Tuner (weekly champion/challenger) [07 §3]

* Schedule: Saturday 10:00 Taipei (`開始調參:walk-forward champion/challenger…` INFO `engine`), plus the quality trigger (§4.10). Always writes a `params_history` row and a result event (the lost engine once died mid-run without a row).
* Search space (*default* generator): 64 random single-coordinate perturbations of the incumbent — one weight × `{0.5, 0.75, 1.25, 1.5}`, or the four thresholds shifted together by ±0.5 keeping `strong = buy + 2`, `sell = −buy` — seeded by run date, de-duplicated (observed `嘗試 59–64 組`). `fund_cap`, `use_*`, `exit`, `sizing` are never touched.
* Walk-forward (*default* windows): train = bars −250…−61, valid = last 60 bars, same windows for champion and challengers; challenger = best candidate by `train_metric`.
* Metric: `reward_points` (name since 2026-07-25; `calmar` before) — *default* definition: Σ over backtest days of `round(daily_ret × 1000)` + 10 per new equity high; magnitudes observed train ≈ 306–363, valid ≈ 808–1028.
* Adoption: `adopt = valid_metric > champion_metric × 1.02` (checked on all 24 automatic rows).
* Row: adopted → `version = active + 1`, `params_json` = challenger, `adopted 1`, reason `樣本外 reward_points {valid:.3f} 勝過現任 {champ:.3f}(門檻 +2%,嘗試 {k} 組)`; rejected → `version = active`, `params_json` = losing challenger, `adopted 0`, reason `樣本外 reward_points {valid:.3f} 未勝過現任 {champ:.3f}(門檻 +2%,嘗試 {k} 組)`; `adopted_at` = run completion time; metrics `%.3f` in the reason.
* Events (`tuner` INFO): `調參採用新參數 v{n}:{reason}` / `調參維持現任參數 v{n}:{reason}`. One optional `opus` call per run (an extra LLM-suggested candidate; failure non-fatal → `AI 呼叫失敗(opus,rc=…)` WARN `tuner`).
* `active_version` = version of the newest `adopted = 1` row = `engine.params_version`.


---

## 7. Output contracts (exact schemas)

Common: serialization per §1.5; "req" = the viewer breaks or hides a whole block without it; everything else degrades to `—`/hidden. Line numbers refer to `app.js`.

### 7.1 `data.json` [01]

Top level, key order: `{"generated_at": iso, "overview": {…}, "ai_report": {…}}`. `overview.ts == generated_at` (bake time). `overview` is **req** (missing → red dot `連線中斷 — 無法取得 /api/overview`).

`overview` key order: `ts, market, engine, account, positions, rows, reward, model_health_brief, disclaimer`.

**`overview.market`** (§4.3): `is_open` bool; `label` `收盤`|`盤中`; `index` float unrounded; `pct` float percent unrounded; `regime_label` string; `score` number (viewer concatenates raw → emit `-0.5`, `0.5`, `1.0`). Rendered `偏空震盪 -0.5`; chip hidden when `regime_label` falsy.

**`overview.engine`** (key order):

| Field | Type | Value / rule |
|---|---|---|
| `running` | bool | `true` |
| `scanning` | bool | `false` at bake time |
| `tuning` | bool | `false` |
| `last_scan` | iso | time of the last scan that produced `rows[]`; equals every `rows[].ts`; the viewer re-fetches the open symbol when it changes |
| `last_scan_kind` | string | `盤中` / `收盤定盤` / `EOD` for scheduled runs, `啟動` for `workflow_dispatch` runs (only `啟動` observed; shown as `18:17:00(啟動)`); the morning job does not change `last_scan` |
| `next_scan` | iso | next cron slot (`last_scan + scan_interval_min`); unused by the viewer |
| `scan_interval_min` | int | the real cadence (`30` under Actions; original `5`); unused by the viewer |
| `mode` | `"paper"` | (`"real"` → `實盤` badges) |
| `kill` | bool | `state/KILL` exists |
| `params_version` | int | `10` after adoption (`參數 v10`) |
| `autopilot` | bool | `true` |
| `ai` | object | `{"enabled": bool, "model_fast": "sonnet", "model_deep": "opus"}` (aliases, never real model ids); `enabled` = key configured |
| `health` | object | §8.4 (key order `configured, share_days, ai_days, share_enabled, ai_enabled, ai_last_success, ai_last_error, ai_hard_failure, red, checked_at`) |

**`overview.account`** (key order `cash, initial_cash, positions_value, equity, realized_pnl, unrealized_pnl`): all floats, unrounded; rules §5.1.

**`overview.positions[]`** (key order `symbol, code, name, qty, avg_price, price, ret_pct, value, stop_price, trail_price, peak, verdict, reasons`): `symbol` **req**; `qty` int; `avg_price/ret_pct/stop_price/trail_price` 2 dp; `price`, `value`, `peak` as computed; `verdict` `"hold"`|`"exit"`; `reasons` string[]. Empty array → `目前無持股`.

**`overview.rows[]`** (fixed watchlist order; key order `symbol, code, name, price, ts, quote_fresh, pct, total, tech_total, mkt_score, fund_total, news_total, chips_total, kd60_total, kd60, rec_code, rec_text, changed, regime, forecast5, suggest_qty, ai_note`):

| Field | Type / format | Rule |
|---|---|---|
| `symbol`, `code`, `name` | str | **req**; `symbol` = `symbol/<code>.json.symbol` |
| `price` | float | last quote = `bars[-1][4]` after the close (same float) |
| `ts` | iso | quote time |
| `quote_fresh` | bool | §3.4 |
| `pct` | float 2 dp, percent | `round((price/prev_close − 1)×100, 2)` |
| `total` | float 1 dp | §4.8 (`null` sorts last; avoid) |
| `tech_total` | float ≤ 2 dp | §4.2 (printed raw in a tooltip; must be a number) |
| `mkt_score` | number | `market.score` |
| `fund_total` | float 1 dp | §4.4 |
| `news_total` | float 2 dp | `news.score` |
| `chips_total` | float 1 dp | `chips.score` |
| `kd60_total` | float 1 dp | `intraday_kd.score` |
| `kd60` | object | `{"k", "d", "label", "note"}` (no `score`) |
| `rec_code` | enum | `STRONG_BUY`/`BUY`/`HOLD`/`SELL`/`STRONG_SELL` |
| `rec_text` | str | `強力買進`/`買進`/`觀望`/`賣出`/`強力賣出` |
| `changed` | bool | §4.8 |
| `regime` | enum | `bull`/`bear`/`range` |
| `forecast5` | object | `{"pred_ret", "prob_up", "ci68_lo", "ci68_hi", "model"}` (fractions, unrounded) or `null` |
| `suggest_qty` | int | §4.11 |
| `ai_note` | object or `null` | `{"ts": iso, "rec_code": enum at generation time, "text": str}` identical to the symbol file's |

Tooltip the viewer builds (shows why every numeric field must be present): `技術 {tech_total} ・ 大盤 {mkt_score} ・ 基本面 {fund_total} ・ 消息 {±news_total} ・ 籌碼 {±chips_total} ・ 60分KD {kd60.label}`.

**`overview.reward`** (§8.6; key order `total, provisional, history`): `total` int; `provisional` `{"month": "YYYY-MM", "ret_pct": 2 dp, "points": int, "settled": false}` or `null` — **when present, `points` and `ret_pct` must be numbers or the viewer throws and stops rendering**; `history[]` newest first: settled `{"month", "equity_open", "equity_close", "partial", "ret_pct", "twii_ret_pct", "base_points", "beat_market", "bonus_beat", "new_high", "bonus_high", "points", "total_after"}`, skipped `{"month", "skipped": true, "reason": "缺月初或月底權益基準(該月系統未完整運行)"}`. Whole `reward` missing/null → card hidden.

**`overview.model_health_brief`**: `{"hit_rate_5d": 4 dp fraction, "mae_5d": 6 dp fraction, "n_resolved": int, "champion": str}` (§4.10).

**`overview.disclaimer`** (verbatim): `本工具僅為技術分析參考,非投資建議;所有訊號與預測由公式機械式計算,必有誤差且會失準,下單請自行判斷風險。資料來源 Yahoo Finance,可能延遲 15–20 分鐘。`

**`ai_report`** (key order `ai, date, generated_at, content, weekly_review`): `ai` = copy of `engine.ai`; `date` `YYYY-MM-DD` of the last **successful** report (stale on purpose while AI fails); `generated_at` iso; `content` markdown (`## ` headings `大盤與市場氛圍`, `觀察清單重點`, `持倉與損益`, `模型健康`, `明日留意`; `- **code name** — …` bullets; the viewer's `mdToHtml` supports `#`–`####`, `- `, `**bold**`, paragraphs; tables/numbered lists render as plain lines); `weekly_review` `{"week": "YYYY-Www", "generated_at": iso, "text": markdown}` or `null` (never rendered; keep emitting). Missing `content` → card shows `收盤後自動產生`.

### 7.2 `symbol/<code>.json` [02, 04]

File name `symbol/<bare code>.json`; key order `symbol, code, name, bars, indicators, signals, fund_signals, news, chips, intraday_kd, trend, forecast, ledger, ai_note`; all 14 keys always present.

| Key | Shape | Rules |
|---|---|---|
| `bars` | `[[date, open, high, low, close, volume]] × 250` | **req**; oldest first; `volume` int shares; last close == `rows[].price`; adjusted prices (§3.3) |
| `indicators` | 11 × `float[250]` | §4.1; no nulls |
| `signals`, `fund_signals` | `[{"indicator","label","score","note"}]` | §4.2, §4.4; `score` always a float literal (`0.0`) |
| `news` | `{"score": 2 dp, "items": [{"title","link","source","published","sentiment","score"}]}` | §4.5; `link` must match `^https?://` to be clickable |
| `chips` | `{"score": 1 dp, "signals": [...], "recent": [{"date","foreign","invtrust","dealer","total"}] × 10 newest first}` | §4.6 |
| `intraday_kd` | `{"score","k","d","label","note"}` | §4.7 |
| `trend` | `{"segments": [{"start","end","regime","ret"}], "summary": {"regime","slope20","slope60","slope120","dist_ma60","high_252","low_252","pos_252"}}` | §4.9 |
| `forecast` | `{"made_date", "model", "base_price", "horizons": [{"horizon_days", "pred_ret", "ci68": [lo,hi], "ci95": [lo,hi], "prob_up", "model"}] × (1,5,20), "fan": {"dates"[21], "median"[21], "lo68"[21], "hi68"[21], "lo95"[21], "hi95"[21]}}` | §4.10; `made_date == bars[-1][0]`, `base_price == bars[-1][4]`; missing/empty horizons → `預測:資料累積中` |
| `ledger` | `{"by_horizon": [{"model","horizon","n","mae","hit_rate"}] × 6}` | not read by the viewer; §4.10 |
| `ai_note` | `{"ts","rec_code","text"}` or `null` | identical object to `rows[].ai_note` |

Viewer-side consistency (checked by tests): `rows[].price == bars[-1][4]`; `rows[].pct == round((bars[-1][4]/bars[-2][4]−1)×100, 2)`; `rows[].regime == trend.summary.regime`; `rows[].forecast5` == flattened h=5 horizon; `rows[].kd60`/`kd60_total` == `intraday_kd` split; `rows[].news_total == news.score`; `rows[].chips_total == chips.score`; `rows[].ai_note == ai_note`. Bake all nine files and `data.json` from the same in-memory state.

### 7.3 `orders.json` [03 §1]

`{"orders": [ … ]}` — the **50 most recent** orders, **newest first** by `id`; key order per row `id, created_at, symbol, code, name, side, qty, price_hint, status, filled_price, filled_at, fee, tax, pnl, mode, source, note`. Enums: `side` `BUY`|`SELL` (anything else renders as 賣); `status` `FILLED`|`REJECTED`|`PENDING`|`CANCELLED` → `成交`/`拒絕`/`等待`/`取消`; `mode` `paper`|`real` → `紙上`/`實盤`; `source` `autopilot` → chip `自動`. `fee`/`tax` floats with integer values; `pnl` `null` on BUY, unrounded float on SELL; `note` not rendered. Empty → `尚無訂單`.

### 7.4 `events.json` [03 §2]

`{"events": [ … ], "last_id": int}` — the **100 most recent** events in **ascending** `id` order; `last_id = max(id)`. Row key order `id, ts, level, source, message`; `level` ∈ `INFO`|`WARN`|`ERROR`; `source` ∈ `engine`|`news`|`ai`|`tuner`|`broker`|`heartbeat`|`data`; `message` single line (no newlines). Rendered `{ts[11:19]} [{source}] {message}` with `.ev-WARN` amber, `.ev-ERROR` red bold. `id` strictly increasing forever (§1.2 C3).

### 7.5 `model-health.json` [03 §3]

Key order `metrics, params_history, active_version`; `metrics` key order `by_model_horizon, champion, series`.

| Field | Shape |
|---|---|
| `metrics.by_model_horizon[]` | `{"model","horizon","n","mae" (6 dp),"hit_rate" (4 dp)}` ordered `(horizon asc, model asc)`: baseline/1, ridge/1, baseline/5, ridge/5, baseline/20, ridge/20 |
| `metrics.champion` | `{"1": str, "5": str, "20": str}` (string keys); chip `1日冠軍:baseline` with tooltip `樣本數足夠時取 MAE 較低者`; the chart dashes the line named `baseline` |
| `metrics.series[]` | `{"date" (Monday), "model", "horizon", "mae" (6 dp), "hit_rate" (4 dp), "n"}` sorted `(date, model, horizon)`; numbers must be numbers (viewer multiplies by 100) ; empty → `資料累積中 — 預測需等到期兌現後才有誤差統計,第一天沒有資料是正常狀態。` |
| `params_history[]` | all rows newest first; key order `id, adopted_at, version, params_json (string), train_metric, valid_metric, champion_metric, adopted (0/1), reason`; viewer summary `buy_th={buy_th} 停損{round(stop_pct*100)}% 移停{round(trail_pct*100)}%`; `adopted:1 && version == active_version` → ` ●` |
| `active_version` | int → `目前參數 v10` |

### 7.6 `shadow.json` [03 §4, 08 §1]

Key order `schema, active, generated_at, state_key, start_date, mode, initial_cash, arms, closeout, progress, chain_ok, freeze_ok, warnings, rows, legs, stats, turnover, trades, holdings, genes, verdict, verdict_sealed, computing, refresh_failed`.

| Field | Shape / rule | Viewer |
|---|---|---|
| `schema` | `1` | — |
| `active` | bool | `false` → whole tab = `reason` or `shadow 尚未起錶` |
| `reason` | string, only when inactive | — |
| `generated_at` | iso of the bake | — |
| `state_key` | 64-hex SHA-256 of the ledger state (*default* recipe [08 §1.3]) | — |
| `start_date`, `mode` (`"M3"`), `initial_cash` (`1000000.0`) | frozen spec | `起始日 …` when no rows |
| `arms` | `{"a": "incumbent-v6", "b": "risk-exit-consensus"}` | brief `A 現任(…)` / `B 候選(…)` |
| `closeout` | `{"min_days": 60, "target_closed": 10, "hard_cap_days": 120}` | chip denominators |
| `progress` | `{"n_days": len(rows), "closed_b": rows[-1].closed_b, "ready": bool, "capped": bool}` | `第 55/60 交易日 ・ B 平倉 2/10` |
| `chain_ok`, `freeze_ok` | bool; `false` → `帳本雜湊鏈驗證失敗` / `凍結封條驗證失敗` | warning line |
| `warnings` | string[] joined by `；` after `⚠ ` | |
| `rows[]` | ascending by bar date, one per bar date ≥ `start_date`, last row = T−1: `{"date","eq_a","eq_b" (2 dp),"ret_a_pct","ret_b_pct" (4 dp, vs row 0),"diff_pp","day_pp" (4 dp, differenced on unrounded),"closed_a","closed_b" (cumulative SELL counts)}` | table newest first, chart in file order; numbers **req** |
| `legs` | `{"operational": {"prefix_breaks", "pass"}, "safety": {"doom", "mdd_b", "mdd_a" (4 dp), "pass"}, "return": {"ret_b", "ret_a", "diff" (6 dp), "pass"}, "realization": {"slip_bp_b", "slip_bp_a" (2 dp), "reject_b", "reject_a", "pass"}}` | chips `操作腿 ✓ prefix_breaks=0`, `安全腿 ✓ MDD B 4.0% / A 5.9%`, `報酬腿 ✓ B−A +9.92pp`, `實現腿 ✓ B 滑價 11.65bp(門檻 max(2×A, 5bp))` |
| `stats` | `{"a": {"slip_bp","reject_rate","turnover_notional","n_fills","n_starved"}, "b": {…}}` unrounded | not read |
| `turnover` | `{"a": float, "b": float}` (= `turnover_notional`) | not read |
| `trades` | `{"a": [...], "b": [...]}` rows `{"type","symbol","date","price" (unrounded),"qty" (null on SELL),"score" (2 dp, null on SELL),"reason" (null on BUY; `停損`/`移動停利`/`訊號`),"ret" (fraction, null on BUY)}` ascending by date | merged, newest first |
| `holdings` | `{"a": [...], "b": [...]}` rows `{"symbol","qty","avg_entry" (2 dp),"first_buy","age_days","last","last_date","peak" (highest close since entry),"ret_pct","stop_line","dist_stop_pct","trail_line","dist_trail_pct" (2 dp)}`; `stop_line = avg_entry×(1−stop_pct_arm)`, `trail_line = peak×(1−trail_pct_arm)`, `dist = (last/line − 1)×100` | `< 3` → `near-exit` |
| `genes[]` | 16 rows `{"gene","a","b","differs"}` in the order of §6.3 | `fmtGene`: `_pct`/`risk_frac` → `x.xx%`, integers raw, else 3 dp |
| `verdict` | `null` or object with `adjudicated` (str), `pass` (bool), `capped` (bool), `next` (str) + free extra keys | banner `裁決({adjudicated}):{通過\|未通過}{(120 日硬上限)}? → {next}` |
| `verdict_sealed`, `computing`, `refresh_failed` | bool; `computing:true` → chip `更新中…`, with `refresh_failed` → `更新失敗` | |

Formulas (**high**): `ret_x_pct = round((eq_x[i]/eq_x[0] − 1)×100, 4)`; `diff_raw = (eq_b[i]/eq_b[0] − eq_a[i]/eq_a[0])×100`; `diff_pp = round(diff_raw, 4)`; `day_pp = round(diff_raw[i] − diff_raw[i−1], 4)` (0 on row 0); `mdd_x` = max peak-to-trough drawdown of `eq_x`; `ret_x = round(eq_x[-1]/eq_x[0] − 1, 6)`; `diff = ret_b − ret_a`; `slip_bp_x = round(stats.x.slip_bp, 2)`. Leg pass rules: `operational: prefix_breaks == 0` (medium); `realization: slip_bp_b ≤ max(2×slip_bp_a, 5) and reject_b ≤ max(2×reject_a, 0.01)` (first half high, printed on the chip); `safety: not doom and mdd_b ≤ max(1.5×mdd_a, 0.10)`, `doom = min(eq_b) ≤ 0.8×eq_b[0]` (*default*); `return: diff > 0` (*default*). Close-out: `capped = n_days ≥ 120`; `ready = (n_days ≥ 60 and closed_b ≥ 10) or capped`; automatic verdict when `ready and not verdict_sealed`: `pass = all legs`, `adjudicated = bar date`, `next = "採用 B(risk-exit-consensus)為正式參數 v{n+1};影子對照結案"` on pass else `"維持 A 現任(incumbent-v6);影子對照結案"` (*default* strings). Arm mechanics (if the experiment is ever continued): decisions at D−1's close with the arm's genes, fills at D's open with M3 friction `open × (1 ± (10 bp + 3.2 bp × sqrt(qty/volume × 1e4)))` (*default*, [08 §1.5]), B capped at 0.20 of cash and 1000-share lots, exits `停損`/`移動停利`/`訊號` at D, mark at D's close, append row, extend the hash chain. After the manual seal of §6.7 none of this runs.

### 7.7 `simple.html` [03 §5] — full template (byte-exact reproduction of both snapshots)

Rules: single-quoted attributes; no indentation; **no trailing newline**; physical newlines only inside the `<style>` block, inside raw AI-note texts, and between converted report blocks; Python formatting (`'{:,.0f}'` is round-half-even — `47381.5 → 47,382`); `cls(v)` = `up` if `v > 0`, `down` if `v < 0`, else `flat`; `reccls` = `hold` for HOLD, `buy` for BUY/STRONG_BUY, `sell` for SELL/STRONG_SELL; escape AI/report text with `html.escape(s, quote=False)` (*default*; reproduces both snapshots).

Head (line 1 up to `<style>`, then the CSS lines verbatim, then line 26 continues into the body):

```
<!DOCTYPE html><html lang='zh-Hant'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><meta http-equiv='refresh' content='300'><title>tw-quant 家用唯讀快照</title><style>
:root{color-scheme:dark}
body{margin:0;padding:16px;background:#0d1220;color:#dbe2f1;
  font:15px/1.65 "Microsoft JhengHei","PingFang TC",system-ui,sans-serif}
.wrap{max-width:860px;margin:0 auto}
h1{font-size:20px;margin:0 0 2px}
h2{font-size:16px;margin:26px 0 8px;color:#9fb0d0;border-bottom:1px solid #232b44;padding-bottom:4px}
h3,h4{margin:14px 0 4px;color:#c7d2ea}
.meta{color:#7787a8;font-size:12.5px}
table{width:100%;border-collapse:collapse;margin:8px 0;font-size:14px}
th{color:#7787a8;font-weight:600;text-align:right;padding:6px 8px;border-bottom:1px solid #232b44}
td{padding:6px 8px;text-align:right;border-bottom:1px solid #1a2138}
th:first-child,td:first-child{text-align:left}
.up{color:#ff5d5d}.down{color:#3ddc84}.flat{color:#8b98b8}
.rec{display:inline-block;padding:1px 8px;border-radius:4px;font-size:12.5px}
.rec.buy{background:#3a1520;color:#ff8a8a}.rec.sell{background:#0f2b1d;color:#5fe3a1}
.rec.hold{background:#1a2138;color:#8b98b8}
.ai{margin:2px 0 12px;padding:8px 12px;background:#121a30;border-left:3px solid #5b8cff;
  border-radius:0 6px 6px 0;font-size:13.5px;color:#b9c6e2}
.ai .t{color:#5b8cff;font-weight:600;font-size:12px;margin-right:6px}
.report{padding:4px 14px;background:#101730;border:1px solid #232b44;border-radius:8px}
.report ul{margin:4px 0;padding-left:20px}
.foot{margin-top:28px;padding-top:10px;border-top:1px solid #232b44;color:#66759a;font-size:12px}
.badge{display:inline-block;padding:1px 8px;border-radius:10px;background:#1a2138;
  color:#8b98b8;font-size:12px;margin-left:8px}
</style></head><body><div class='wrap'>
```

Body, in order, all on the same physical line unless noted (`{…}` = Python format of the named `data.json` field):

1. `<h1>tw-quant 台股監控 <span class='badge'>唯讀快照</span><span class='badge'>紙上交易(虛擬資金)</span></h1>`
2. `<div class='meta'>產生時間 {generated_at[:16].replace('T',' ')}(台北時間).本頁每次掃描後自動更新;瀏覽器每 5 分鐘自動重新整理。</div>`
3. `<div class='meta' style='margin-top:6px'>加權指數 <span class='{cls(market.pct)}'>{market.index:,.0f}({market.pct:+.2f}%)</span>.大盤環境:{market.regime_label}</div>`
4. `<h2>觀察清單與 AI 解讀</h2><table><tr><th>代碼/名稱</th><th>價格</th><th>漲跌%</th><th>評分</th><th>建議</th></tr>` + for each row sorted by `total` descending (stable): `<tr><td>{code} {name}</td><td>{price:,.2f}</td><td class='{cls(pct)}'>{pct:+.2f}%</td><td>{total:+.1f}</td><td><span class='rec {reccls}'>{rec_text}</span></td></tr>` + `</table>`
5. For each row (same order) that has `ai_note`: `<div class='ai'><span class='t'>🤖 {code} {name} AI 解讀 {ai_note.ts[11:16]}</span>{escape(ai_note.text)}</div>` (text inserted with its raw newlines)
6. `<h2>紙上帳戶(虛擬 {initial_cash/10000:.0f} 萬起步)</h2><div>權益 <b>{equity:,.0f}</b> 元(<span class='{cls(eqpct)}'>{eqpct:+.2f}%</span>).現金 {cash:,.0f}.已實現 {realized_pnl:+,.0f}.未實現 {unrealized_pnl:+,.0f}</div>` with `eqpct = (equity/initial_cash − 1)×100` (zero prints `+0`)
7. `<table><tr><th>持股</th><th>股數</th><th>均價</th><th>現價</th><th>報酬%</th><th>市值</th><th>停損價</th><th>移停價</th><th>狀態</th></tr>` + per position in array order: `<tr><td>{code} {name}</td><td>{qty:,}</td><td>{avg_price:,.2f}</td><td>{price:,.2f}</td><td class='{cls(ret_pct)}'>{ret_pct:+.2f}%</td><td>{value:,.0f}</td><td>{stop_price:,.2f}</td><td>{trail_price:,.2f}</td><td><span class='rec hold'>續抱</span></td></tr>` (`verdict != hold` → `<span class='rec sell'>該賣</span>`, *default*) + `</table>` (header row only when no positions, *default*)
8. `<div class='meta'>賣出主要由出場機制執行:跌破停損價(-{round(stop_pct*100)}%)或從高點回落至移停價(-{round(trail_pct*100)}%)時狀態轉「該賣」,自動交易開啟時會自動出場。</div>` (v9 → `-8%`/`-12%` as observed; v10 → `-8%`/`-21%`)
9. `<h2>AI 收盤日報</h2><div class='meta'>{ai_report.date} 產生於 {ai_report.generated_at[11:16]}</div><div class='report'>{md_to_html(content)}</div>` (no report yet → `<div class='meta'>尚未產生</div>` and no `.report` div, *default*)
10. `<div class='foot'>本頁為唯讀快照,由程式自動產生(含 AI 生成之解讀文字,可能有誤).所有交易皆為紙上模擬、非真實資金。<br>{overview.disclaimer}</div></div></body></html>`

`md_to_html` (line-based, blocks joined with `\n`): strip each line; blank → dropped (closes an open list); `## text` → `<h4>text</h4>` (general rule `#`×k → `<h{k+2}>`); `- text` → `<li>text</li>` with the run wrapped in `<ul>` … `</ul>` on their own lines; anything else → `<p>text</p>`; inline `**x**` → `<strong>x</strong>` after escaping.

### 7.8 Published set and cadence

Every scan/EOD bake writes all of: `data.json`, `symbol/{9}.json`, `orders.json`, `events.json`, `model-health.json`, `simple.html`; `shadow.json` only until it is sealed (then never). The Saturday job bakes too (`資料時間` and `share_days` stay fresh). One git commit per bake (§9.6).


---

## 8. Events taxonomy, engine health, heartbeat, reward points

### 8.1 Event record

`{id, ts, level, source, message}` appended to `state/events.jsonl` with a global autoincrement (≈ 74/day historically); `ts` = Taipei ISO at append time; ids monotonic with `ts`; the bake publishes the last 100 + `last_id`. `ERROR` is reserved for unhandled exceptions in a step (`{step} 失敗:{exception}`, *default*; never observed). Messages are single-line; `{pct}` placeholders print `+0.8%`/`-1.4%` (1 dp, signed).

### 8.2 Catalogue (verbatim templates)

| Source | Level | Template | When |
|---|---|---|---|
| `engine` | INFO | `{code} {name}:{old}→{new}` (old/new ∈ `觀望` `買進` `強力買進` `賣出` `強力賣出`) | every scan, per flipped symbol |
| `engine` | INFO | `{code} {name} 消息面偏空 {score:+.1f}({n} 則)` / `{code} {name} 消息面偏多 {score:+.1f}({n} 則)` (偏多 *default*) | news refresh with `\|score\| ≥ 1.0` |
| `engine` | INFO | `晨會:夜盤 {pct}、TSM {pct}、費半 {pct};近 {d} 日事件 {k} 筆、宏觀新聞 {m} 則;{無覆蓋\|風險覆蓋 caution}` (`夜盤 無資料` when missing; `d` = 3) | morning brief |
| `engine` | INFO | `閘門攔截 {code} 買進:G3:市場 caution(晨會覆蓋:隔夜情勢(caution)),禁加碼` | add blocked under caution |
| `engine` | INFO | `閘門攔截 {code} 買進:G4:{date} 收盤評分 {s:+.1f} 未達 buy_th {th:+.1f},訊號未跨日持續` | persistence gate |
| `engine` | INFO | `閘門攔截 {code} 買進:G1:報價過期({age} 分)` (*default*) | stale quote |
| `engine` | INFO | `自動換股:賣出 {code} {name}(評分 {s:+.1f})讓位給 {code2} {name2}(評分 {s2:+.1f})` | swap |
| `engine` | INFO | `收盤定盤掃描完成:{n} 檔以收盤世界重新定價(其中 {k} 檔取得交易所定盤價);14:15 EOD 會再以完整日K做最終校正。` | 收盤定盤 scan |
| `engine` | INFO | `市場狀態:{state}(大盤單日 {pct}、5日 {pct})` (only `halt` observed) | EOD, state change |
| `engine` | INFO | `EOD 完成:更新 {n} 檔資料,記錄 {p} 筆預測,兌現 {r} 筆。` | end of EOD |
| `engine` | INFO | `行事曆同步:TWSE 除權息 {n} 筆` | after EOD |
| `engine` | WARN | `{code} 未來 30 天無任何行事曆事件記錄——法說會/除權息可能未收錄` | per symbol with an empty 30-day calendar |
| `engine` | WARN | `偵測到預測品質下降(命中率 {p}%,MAE 惡化 {q}%),自動觸發調參` | quality trigger |
| `engine` | INFO | `開始調參:walk-forward champion/challenger…` | tuner start |
| `engine` | INFO | `影子對照裁決:B 組勝出,手動採用(第 55/60 交易日,B 平倉 2/10);risk-exit-consensus 升為正式參數 v10` | manual seal (once) |
| `engine` | WARN | `行事曆同步失敗({exc})` (*default*) | calendar fetch failed |
| `tuner` | INFO | `調參採用新參數 v{n}:{reason}` / `調參維持現任參數 v{n}:{reason}` | tuner result |
| `broker` | INFO | `紙上買單成交:…` / `紙上賣單成交:…` (§5.2) | per fill |
| `heartbeat` | INFO | `心跳已送(FAIL:{red joined by 、})` / `心跳已送(OK)` (OK *default*) | EOD, Saturday |
| `heartbeat` | WARN | `心跳送出失敗({exc})` (*default*) | request failed |
| `data` | WARN | `{symbol} 本次最新日期 {new_last} 落後快取 {cache_last}(疑似劣化回應),保留舊快取` | degraded bars |
| `data` | WARN | `{symbol} 下載失敗({exc}),保留舊快取`, `T86 下載失敗({exc}),沿用快取` (*default*) | fetch failed |
| `news` | WARN | `{code} 新聞更新失敗({exc}),沿用快取` (*default*) | RSS failed |
| `news`/`ai`/`tuner` | WARN | `AI 呼叫失敗({model},rc={rc}):{error tail}` (`model` = `sonnet` for `news`, `opus` otherwise; `rc` = exit code / HTTP status; tail may be empty) | each failed AI call |
| `news`/`ai`/`tuner` | WARN | `AI 連續失敗 3 次,暫停 AI 呼叫 15 分鐘(期間自動改用非 AI 路徑)` | 3rd consecutive failure (replaces the 3rd `失敗` line) |

### 8.3 AI circuit breaker (**high**)

One **global** consecutive-failure counter across `news`/`ai`/`tuner`, persisted in `state/engine.json` (`ai_fail_count`, `ai_pause_until`). Each failure logs `AI 呼叫失敗(…)`; on the 3rd consecutive failure log `AI 連續失敗 3 次,暫停 AI 呼叫 15 分鐘(期間自動改用非 AI 路徑)` **instead of** a third failure line and set `ai_pause_until = now + 15 min`. While paused, AI calls are skipped silently and the rule-based path is used (lexicon news scores; notes/report keep their last values). A success resets the counter; the pause end resets it. `health.ai_last_success` = start time of the last successful call; `health.ai_last_error = {"ts", "model", "rc", "error"}` of the last failure.

AI outputs: per-symbol note (`opus`, ≤ 5 short paragraphs separated by `\n\n`, plain text, ending with `以上為數據解讀,非投資建議。`; prompt receives the whole symbol payload + row + position; stored with `ts` and the symbol's `rec_code` at generation time); daily report (`opus`, markdown with the five `## ` headings of §7.1, `date` = T, `generated_at` = finish time); weekly review (`opus`, Saturday, `week = ISO week`). Generation order after EOD: report, then notes in watchlist order, sequentially. Failures leave the previous artefacts untouched (the viewer shows the stale date on purpose).

### 8.4 `engine.health` (computed at every bake; key order as listed) [07 §6]

| Field | Rule |
|---|---|
| `configured` | `HEARTBEAT_URL` set |
| `share_days` | calendar days from the last successful publish (previous commit) to `checked_at`'s date, evaluated before this publish (Saturday → 1) |
| `ai_days` | `(checked_at.date − ai_last_success.date).days` |
| `share_enabled` | publishing on (`true`) |
| `ai_enabled` | `= engine.ai.enabled` |
| `ai_last_success` | iso or `null` |
| `ai_last_error` | object or `null` |
| `ai_hard_failure` | `true` only when the client cannot be constructed / network unreachable (*default*; `false` after 19 days of auth failures) |
| `red` | strings: `AI 日報 {ai_days} 天未產生` when `ai_enabled and ai_days > 3`; `家用快照 {share_days} 天未更新` when `share_days > 3` (*default* thresholds and second string); `資料更新失敗` when every bar fetch failed (*default*) |
| `checked_at` | `= overview.ts` |

### 8.5 Heartbeat (**medium**)

Once per EOD and per Saturday job, before `EOD 完成`: if not `configured` skip silently; if `red` empty `GET HEARTBEAT_URL` → `心跳已送(OK)`; else `GET HEARTBEAT_URL + "/fail"` with body `、`.join(red) → `心跳已送(FAIL:{、-joined red})`. Never fatal; not sent in dry run. Viewer tooltip semantics: `監控紅燈:每日 EOD 會把它送到外部心跳的 /fail 端點`.

### 8.6 Monthly reward points (`overview.reward`) [07 §4] — **high** on all observed months

```
equity_open(M)  = equity_close(M−1), or the first EOD equity the engine recorded in M (then partial = true)
equity_close(M) = account.equity at the last EOD of M
ret_frac        = equity_close/equity_open − 1
ret_pct         = round(ret_frac × 100, 2)
base_points     = int(round(ret_frac × 1000))                 # from the UNROUNDED return: 2.4537 % → 25, 1.5475 % → 15
new_high        = equity_close > max(initial_cash, all earlier month-end equities)      (strict; July 1 000 000 → false)
bonus_high      = 10 if new_high else 0
beat_market     = (ret_pct > twii_ret_pct) and not partial     (default; July 0.0 > −6.52 was false)
bonus_beat      = 10 if beat_market else 0                     (value never observed; default 10)
points          = base_points + bonus_beat + bonus_high
total_after     = previous total_after + points;  reward.total = newest total_after
provisional     = {"month": current, "ret_pct": round((equity_now/equity_close(M−1) − 1)×100, 2),
                   "points": int(round((equity_now/equity_close(M−1) − 1)×1000)), "settled": false}
skipped month   = {"month", "skipped": true, "reason": "缺月初或月底權益基準(該月系統未完整運行)"}
```

`twii_ret_pct` = `^TWII` close on the last trading day of M vs M−1, 2 dp (*default* endpoints). Settlement runs in the first EOD dated in M+1 before the new provisional is computed. `history` is newest first and must be seeded from the snapshot (`2026-09 … 2026-06`); October settles from `equity_open 1040392.13`.

---

## 9. Scheduling and GitHub Actions [08 §2–§3]

### 9.1 Original timeline (what is being mapped)

08:30 晨會 → 09:00–13:30 scans every 5 min (first scan at 09:00 fires stops on the opening quote; orders seen 09:00:21 … 13:29:04) → ≈ 13:33 `收盤定盤掃描` → 14:15 EOD (market state, heartbeat, record/resolve, calendar sync, model health, reward, quality trigger, AI notes + report, bake, commit `snapshot {ISO}` by `tw-quant <tw-quant@localhost>`) → shadow bake after EOD on trading days → Saturday 09:30 weekly review, 10:00 tuner, 14:15 EOD (`記錄 0 筆預測`) → the process also scanned after hours and on restart (`啟動`). The engine amended one rolling commit and force-pushed; host clock was `+09:00`, all engine stamps `+08:00` (explicit `Asia/Taipei`).

### 9.2 Cron mapping (UTC; Taipei = UTC+8)

| Taipei | Mode | Cron | Notes |
|---|---|---|---|
| 08:30 Mon–Fri | `morning` | `30 0 * * 1-5` | may be folded into the first scan (`scan` runs the brief if none exists today) |
| 09:00–13:30 every 30 min Mon–Fri | `scan` | `*/30 1-5 * * 1-5` | 10 slots; the 13:30 slot (Taipei clock ≥ 13:30) acts as `收盤定盤` |
| 14:15 Mon–Fri | `eod` | `15 6 * * 1-5` | runs on holidays too |
| Sat 10:00 | `tune` | `0 2 * * 6` | weekly review → tuner → Saturday bake/commit |
| any | `workflow_dispatch` | — | inputs `mode` (`auto\|morning\|scan\|eod\|tune\|bake\|replay`), `dry_run`, `as_of` |

Dropped: Sunday EOD (original ran daily); after-hours scans. `scan_interval_min` is published as `30`; `next_scan` = next slot. GitHub may delay or skip slots; every run derives its action from the Taipei clock and is idempotent.

### 9.3 Mode decision (`engine.clock.decide`)

```
now = TWQ_NOW or now(Asia/Taipei)
workflow_dispatch with mode != auto → that mode, kind = 啟動 (bake/replay: kind unchanged)
cron '30 0 * * 1-5' → morning | '*/30 1-5 * * 1-5' → scan | '15 6 * * 1-5' → eod | '0 2 * * 6' → tune
scan: kind = 收盤定盤 if now.time() ≥ 13:30 else 盤中
morning/scan on a non-trading day (§3.5) → skip, reason 非交易日 (no state write, no commit)
eod/tune: never skipped
```

### 9.4 Mode pipelines

| Mode | Steps in order |
|---|---|
| `morning` | load state → D8 fetch → write `state/engine.json.override` (`無覆蓋`/`風險覆蓋 caution`) + `晨會:…` event → bake `data.json` (engine block only) → commit |
| `scan` | if no 晨會 today: morning steps → quotes for 9 symbols + `^TWII` (D1/D2/D3) → indicators → signals/scores → `rec_code` + flip events → autopilot (§5.4) → news refresh for symbols older than 30 min (AI when allowed) → bake all published files with `engine.last_scan = now`, `last_scan_kind = kind`; for `收盤定盤` also log `收盤定盤掃描完成:…` → commit |
| `eod` | final daily bars (D1, degraded guard) → `^TWII` state (`市場狀態:…` if changed) → fundamentals, T86, 60-min bars → scores/positions marked at the close → health + heartbeat → forecasts record/resolve → `EOD 完成:…` → calendar sync + 30-day WARNs → model health (`metrics`, champion, brief) → reward month settlement (first EOD of a new month) → quality check (→ tuner run) → AI report + notes (`opus`) → shadow step (skipped once sealed) → bake everything → commit |
| `tune` | refresh bars → weekly review (`opus` → `ai_report.weekly_review`) → `開始調參:…` → tuner → result event + `params_history` row → heartbeat → bake (`記錄 0 筆預測`) → commit |
| `bake` | re-render every published file from `state/` without network (repair) |
| `replay` | offline (§9.9) |

### 9.5 Workflow file (`.github/workflows/engine.yml`)

```yaml
name: tw-quant engine
on:
  schedule:
    - cron: '30 0 * * 1-5'      # 08:30 Taipei 晨會
    - cron: '*/30 1-5 * * 1-5'  # 09:00–13:30 Taipei 盤中掃描 (10 slots)
    - cron: '15 6 * * 1-5'      # 14:15 Taipei EOD
    - cron: '0 2 * * 6'         # Sat 10:00 Taipei 週檢討 + 調參 + 週六快照
  workflow_dispatch:
    inputs:
      mode:    {description: 'auto | morning | scan | eod | tune | bake | replay', type: choice, options: [auto, morning, scan, eod, tune, bake, replay], default: auto}
      dry_run: {description: 'no commit/push; upload outputs as an artifact', type: boolean, default: false}
      as_of:   {description: 'Taipei date YYYY-MM-DD for replay (uses fixtures/<date>/)', type: string, default: ''}
permissions: {contents: write}
concurrency: {group: tw-quant-engine, cancel-in-progress: false}
env: {PYTHONUNBUFFERED: '1', TWQ_TZ: Asia/Taipei}
jobs:
  engine:
    runs-on: ubuntu-latest
    timeout-minutes: 40
    steps:
      - uses: actions/checkout@v4
        with: {fetch-depth: 1}
      - uses: actions/setup-python@v5
        with: {python-version: '3.13', cache: pip, cache-dependency-path: requirements.txt}
      - run: pip install -r requirements.txt
      - name: Decide mode
        id: mode
        run: python -m engine schedule decide --event "${{ github.event_name }}" --cron "${{ github.event.schedule }}" --mode "${{ inputs.mode || 'auto' }}" --as-of "${{ inputs.as_of }}" >> "$GITHUB_OUTPUT"
      - name: Run engine
        if: steps.mode.outputs.mode != 'skip'
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          HEARTBEAT_URL: ${{ secrets.HEARTBEAT_URL }}
          TWQ_DRY_RUN: ${{ inputs.dry_run == true && '1' || '0' }}
          TWQ_AS_OF: ${{ inputs.as_of }}
        run: python -m engine run --mode "${{ steps.mode.outputs.mode }}" --kind "${{ steps.mode.outputs.kind }}"
      - name: Publish snapshot
        if: steps.mode.outputs.mode != 'skip' && inputs.dry_run != true
        run: |
          git config user.name "tw-quant"; git config user.email "tw-quant@localhost"
          git add -A -- state data.json orders.json events.json model-health.json shadow.json simple.html symbol
          if git diff --cached --quiet; then echo "no changes"; exit 0; fi
          ISO=$(python -c 'import datetime,zoneinfo;print(datetime.datetime.now(zoneinfo.ZoneInfo("Asia/Taipei")).isoformat(timespec="seconds"))')
          git commit -m "snapshot $ISO"
          for i in 1 2 3; do git pull --rebase origin "$GITHUB_REF_NAME" && git push origin "HEAD:$GITHUB_REF_NAME" && exit 0; sleep 15; done
          echo "push failed" >&2; exit 1
      - name: Upload dry-run outputs
        if: inputs.dry_run == true
        uses: actions/upload-artifact@v4
        with: {name: 'dry-run-${{ github.run_id }}', path: "data.json\norders.json\nevents.json\nmodel-health.json\nshadow.json\nsimple.html\nsymbol/\nstate/", retention-days: 7}
```

A second workflow `test.yml` (`on: [push, pull_request]`, `python -m pytest`) runs the offline replay tests (§9.9); no secrets, no network. The `schedule decide` step prints `mode=…`, `kind=…`, `reason=…` lines.

### 9.6 State layout, seeding, commit protocol

```
state/
  engine.json          next_event_id 6763, next_order_id 109, next_params_id 26, params_version 10, last_scan, last_scan_kind,
                       override, market_state, ai_fail_count, ai_pause_until, ai_last_success, ai_last_error, last_publish, ai_models
  watchlist.json       the 9 symbols (§3.1)
  params.json          active params (v10 object of §6.5)
  account.json         cash, realized_pnl, positions[] (qty, cost, avg, peak, first_fill, adds_today), reward history + provisional
  orders.jsonl         every order (bake → last 50)
  events.jsonl         every event (bake → last 100 + last_id)
  predictions.jsonl    forecast ledger rows (§4.10)
  params_history.json  ids 1–25 seeded from model-health.json + new rows
  calendar.json        events[], holidays[]
  cache/bars/<code>.json  cache/bars60/<code>.json  cache/news/<code>.json  cache/t86/<date>.json  cache/info/<code>.json  cache/twii.json
  shadow/spec.json  shadow/seal.json  shadow/ledger.jsonl  shadow/fills_a.jsonl  shadow/fills_b.jsonl  shadow/panel.json (frozen after seal)
  ai/report.md  ai/notes/<code>.json  ai/weekly.md
  KILL                 (presence = engine.kill)
```

Seeding from the surviving snapshot: counters per §1.2 C3; `account` from `data.json` (§5.1); `orders.jsonl` from the 50 published orders; `events.jsonl` from the 100 published events; `params_history` from `model-health.json`; the prediction ledger cannot be recovered row by row — seed `by_model_horizon` totals and `series` rows as frozen "history" aggregates that new rows are added to (so published counts continue from 639/603/462 and the 92 series rows persist); `reward.history` from `data.json`; shadow from `shadow.json` (rows → ledger, trades → fills, genes/arms/closeout → spec + seal) then sealed per §6.7; AI artefacts from `ai_report` and `rows[].ai_note`.

Commit protocol: stage `state/` + published files → skip if nothing staged → one commit `snapshot {ISO}` by `tw-quant <tw-quant@localhost>` → `git pull --rebase` → push, 3 attempts; a failed push fails the job (the next run retries from the committed state). ≈ 12 commits per trading day; an optional manual `squash` dispatch, never automatic.

### 9.7 Secrets and variables

| Name | Required | Absent behaviour |
|---|---|---|
| `ANTHROPIC_API_KEY` | no | `engine.ai.enabled false`, `health.ai_enabled false`, lexicon news, no AI events, no AI red light |
| `HEARTBEAT_URL` | no | `health.configured false`, no heartbeat events |
| `GITHUB_TOKEN` (`contents: write`) | yes | — |
| `TWQ_DRY_RUN`, `TWQ_AS_OF`, `TWQ_NOW`, `TWQ_OFFLINE`, `TWQ_NIGHT_SYMBOL` | no | §9.9 / §3.2 D8 |

Facts to respect: schedules are disabled after 60 days without repository activity (the bot commits count; the heartbeat is the dead-man switch) and only run from the default branch; `GITHUB_TOKEN` pushes do not trigger other workflows but branch-sourced Pages still rebuilds (verify on first deployment; fallback `actions/deploy-pages`); the site root is public.

### 9.8 Holidays — see §3.5. A skipped scan writes nothing; EOD on a holiday records 0, heartbeats, bakes and commits.

### 9.9 Dry run, offline replay, tests

* Dry run: everything runs (network, AI) but no commit/push, no heartbeat; outputs uploaded as an artifact.
* Offline replay: `python -m engine run --mode eod --offline --as-of 2026-10-30` with `TWQ_OFFLINE=1 TWQ_NOW=2026-10-30T14:15:22+08:00`; fetches served from `fixtures/<as_of>/{bars,news,t86,calendar,info}/…` recorded by `python -m engine record --as-of …`; AI and heartbeat disabled; `state/` from a fixture copy.
* Golden tests (`pytest`): (1) indicators recomputed from the 9 published `bars[]` match `indicators{}` to 1e-9 on `[n:]`; (2) technical/fund/chips signals and `tech_total`/`fund_total`/`chips.score`/`total`/`rec_code` reproduce all 9 rows; (3) `suggest_qty` 9/9; (4) baseline forecast + fan to 1e-12; (5) trend segments 9/9; (6) broker fee/tax/pnl on the 60 orders; (7) shadow rows/legs reproduce from the seeded ledger (55 rows byte-identical); (8) `simple.html` byte-identical from `data.json`; (9) every published file satisfies the round-trip property of §1.5 and the key orders of §7; (10) viewer smoke test (Playwright) that `index.html` renders without console errors against the baked files.

### 9.10 First deployment checklist

1. Commit engine, `requirements.txt`, workflows, `fixtures/2026-10-31/`, seeded `state/` on the default branch.
2. Apply §6.6 (v10 row, `active_version 10`, `params_version 10`, tuner event) and §6.7 (sealed `shadow.json`, engine event) in one `bake` run; verify the viewer shows `參數 v10`, `v10 ●`, the verdict banner.
3. Add secrets (optional); `workflow_dispatch` `mode: bake, dry_run: true`; compare the artifact with the current files; then `mode: eod` on a weekday after 14:15 Taipei.
4. Confirm Pages rebuilt (`資料時間` updates); otherwise switch to `actions/deploy-pages`.
5. Create the heartbeat check with a 36-hour grace period.


---

## 10. Contradictions resolved, open questions with defaults, risks

### 10.1 Contradictions between the section files (which evidence wins)

| # | Topic | Section files | Resolution |
|---|---|---|---|
| R1 | `metrics.series[].date` semantics | 03 §3.4 says creation-week Monday (medium-high); 07 §2.5 says target/resolution-week Monday (high) | **07 wins**: week 2026-10-26 carries h=5/h=20 rows (n=36) that could not have been created and resolved in that week, and week 2026-08-03 reproduces exactly on target dates. Use the resolution week (§4.10) |
| R2 | Volume-ratio default | 02 §15 Q1 `vol[-1]/mean(vol[-21:-1])` (excluding today); 04 §3.3.6 `vol[-1]/mean(vol[-20:])` (including today) | **04 wins**: including today reproduces 0050's published `2.0` exactly (§4.2) |
| R3 | `news.score` aggregation default | 02 Q2 recency-weighted mean with 24 h half-life; 05 Q6 `round(Σ 0.5^(age_h/24)·s / 6, 2)` | **05 wins** (brute-force fit on 18 cases; Σ/6 is the backbone) (§4.5) |
| R4 | `halt` thresholds | 05 Q2 `1d ≤ −2.0 % or 5d ≤ −3.5 %`; 06 Q6 `1d ≤ −2.5 % or 5d ≤ −3.5 %` | **05's** (both fit the single observation −2.49 %/−3.6 %; −2.0 avoids depending on 1-dp rounding of the 1-day leg) (§4.3) |
| R5 | Health red thresholds | 01 Q4 `≥ 2 days`; 07 Q13 `> 3`; 08 Q10 raise to 3 because Sundays have no run | **> 3** (§8.4); the Sunday gap would otherwise trip the family-page light every Monday |
| R6 | `last_scan_kind` vocabulary | 01/06: `啟動 / 盤中 / 收盤定盤 / EOD`; 08 adds `晨會` | `盤中 / 收盤定盤 / EOD` for scheduled runs, `啟動` for `workflow_dispatch`; the morning job does not touch `last_scan` (§7.1) |
| R7 | `scan_interval_min` | 5 (original) vs 30 (Actions) | publish the real cadence `30`; unused by the viewer |
| R8 | v10 `reason` / verdict `next` wording | 03 §4.5, 07 §3.6 and 08 §1.8 give three different drafts | one canonical set in §6.6–6.7 (reason, event, `next`) |
| R9 | `suggest_qty` formula | 01 Q8 guessed an equity/ci68 rule; 05 §8 / 06 §5.1 verified `floor(min(0.0075·cash/ATR14, 0.30·cash/price))` 18/18 | **05/06 win** (§4.11) |
| R10 | `rec_code` thresholds | 01 "approx."; 05 §6.1 inclusive ±3/±5 verified | **05 wins** (§4.8) |
| R11 | `peak` definition | live positions: max of fills and scan quotes (06); shadow holdings: highest close since entry (03/08) | not a contradiction — two modules; keep both (§5.3, §7.6) |
| R12 | Shadow bake cadence | 03 Q14 after every trading-day EOD; 08 synchronous inside EOD | same thing; moot after the manual seal |
| R13 | Sunday EOD | original ran daily; 08 drops it | dropped; `share_days` threshold raised (R5) |
| R14 | SAFE_* exits frozen at 8 %/12 % (v5 note) vs adopting B's `0.0830/0.2061` | 06 §6 / 07 Q18 | adopt B's values by owner instruction; keep them out of the tuner (§6.5) |

### 10.2 Open questions — the implementer takes the default unless the owner objects

**Scoring**

| # | Question | Default |
|---|---|---|
| Q-A1 | `market.regime_label`/`score` beyond `偏多震盪 +0.5` / `偏空震盪 -0.5` | 4-state rule of §4.3 (`多頭 +1.0`, `空頭 -1.0`, `盤整 0.0`); keep the two observed strings byte-exact; make the ±1.0 states a config switch |
| Q-A2 | halt/caution thresholds | §4.3: `1d ≤ −2.0 %` or `5d ≤ −3.5 %` → `halt`; brief override `caution` when 夜盤, TSM, 費半 all negative; `halt` clears at the next EOD that does not meet it |
| Q-A3 | RSI base/weight pair | base ±1.5, weight from params (0.5 in v9, 0.784… in v10) |
| Q-A4 | `ma_cross` signal (never emitted) | `均線交叉`, same-day MA5/MA20 cross, `黃金交叉`/`死亡交叉` base ±1.0, notes `MA5 上穿 MA20,短線轉強` / `MA5 下穿 MA20,短線轉弱`, emitted after `均線排列` |
| Q-A5 | Volume ratio | `vol[-1]/mean(vol[-20:])`, threshold 1.5, `%.1f` |
| Q-A6 | Unobserved branch strings (`超買`, `黃金交叉`, `高檔`, `觸上軌`, `帶量上漲`, `消息面偏多`, `投信賣超`, `法人買盤動能`, `外資連買N日`, 60-min `高檔*`) | the strings and symmetric scores in §4.2–4.7 |
| Q-A7 | Boundary equalities | strict for RSI/KD/bands/MA-align; `macd_hist ≥ 0 → 紅柱`; `ratio ≥ 1.5` |
| Q-A8 | Degenerate denominators | RSI loss 0 → 100, both 0 → 50; KD `H9 == L9` → rsv 50; never `NaN` |
| Q-A9 | Fundamental thresholds and the missing `毛利率` chips | §4.4 thresholds; skip a metric when the source field is `None` |
| Q-A10 | Google News query / cap | `q = name` (`0050` for the ETF), first 8 feed entries in feed order |
| Q-A11 | Title sentiment scorer | AI (`sonnet`, one integer −3…+3) with the lexicon of §4.5 as fallback |
| Q-A12 | `news.score` aggregation | `round(Σ 0.5^(age_h/24)·s_i / 6, 2)`, clipped ±3; event at `\|score\| ≥ 1.0` |
| Q-A13 | Foreign-streak tier 3–4 days; `法人動能` z definition; zero days in streaks | ±1.0 for 3–4 days; z = (last-3-day sum − mean of rolling 3-day sums over 60 days)/std; a 0 day breaks both streaks |
| Q-A14 | 60-min KD parameters and high-side labels | KD(9,3,3) on 60-min bars; `高檔 -0.3`, `高檔死亡交叉 -0.5` |
| Q-A15 | `high_252`/`low_252` window; trend segments on longer history | 252 closes of the full history; segments on the served 250-bar window |
| Q-A16 | `is_open` / `quote_fresh` | `is_open` 09:00–13:30 on trading days; `quote_fresh = is_open and age ≤ 20 min` |
| Q-A17 | `total` vs asynchronously refreshed `news_total` | recompute `total`/`rec_code` only in a scan; write `news_total` whenever refreshed |

**Forecasts, tuner, reward**

| # | Question | Default |
|---|---|---|
| Q-F1 | `ridge` internals | §4.10 default (ridge α=1.0 on 250 bars, 9 features, residual-std error scale, `prob_up = Φ(pred/s_h)`) |
| Q-F2 | champion sufficiency threshold | `n ≥ 30`, else `baseline` |
| Q-F3 | which model fills `symbol.forecast` | `champion["5"]` for all three horizons |
| Q-F4 | orphaned forecasts / Saturday `兌現 6` | resolve every pending row whose target bar exists; resolution is an upsert; counts in the same message |
| Q-F5 | `ledger` rows with `n = 0` | omit |
| Q-F6 | tuner candidate generator, windows, `reward_points` definition, purpose of the `opus` call | §6.9 defaults (64 single-coordinate perturbations, train −250…−61 / valid last 60, Σ `round(daily_ret×1000)` + 10 per new high, LLM-suggested extra candidate) |
| Q-F7 | quality-trigger thresholds (33 % reproduced, 155 % not) | `hit5 < 0.40 and mae5/mae_ref > 1.5` over the last 5 trading days vs trailing 60 |
| Q-F8 | `bonus_beat`, `beat_market`, `new_high`, `twii_ret_pct` endpoints, settlement moment | `bonus_beat 10`; `ret_pct > twii_ret_pct and not partial`; strict new high vs all earlier month-ends and `initial_cash`; `^TWII` month-end closes; settle in the first EOD of M+1 |

**Trading**

| # | Question | Default |
|---|---|---|
| Q-S1 | autopilot order budget (26/50 historical BUYs deviate from the ATR rule) | size with §5.6 exactly (`按建議部位 %`); accept the drift |
| Q-S2 | swap gap and conditions | gap ≥ `strong_gap` 2.0, unconditional, one swap per scan, sell the lowest-scored holding |
| Q-S3 | signal-exit note | `訊號出場({rec_text},評分 {s:+.1f})` |
| Q-S4 | G1 text/threshold; G3 beyond caution; G2 | `閘門攔截 {code} 買進:G1:報價過期({age} 分)`; no buys when `halt` or `market.score ≤ −1.0`; G2 reserved |
| Q-S5 | round lots ≥ 1000 and the minimum-one-share rule (single-evidence) | implement both (§5.6) |
| Q-S6 | `verdict`/`reasons[]` non-hold values | `"exit"` with `跌破停損價 {stop:.2f}`, `回落至移停價 {trail:.2f}`, `建議轉賣出` |
| Q-S7 | same-day re-entry after an exit | allowed |
| Q-S8 | `source` for manual orders; non-FILLED rows | `manual`; `REJECTED` rows written, never `PENDING`/`CANCELLED` |
| Q-S9 | 40 % single-position cap | implement as a `qty` cap (never observed binding) |
| Q-S10 | `realized/unrealized` vs `equity − initial_cash` identity | do not force it; `unrealized` uses the 2-dp average |

**Files, health, schedule**

| # | Question | Default |
|---|---|---|
| Q-P1 | heartbeat OK text, separator, `/fail` shape | `心跳已送(OK)`; `、`; healthchecks-style `GET url` / `GET url/fail` |
| Q-P2 | red thresholds and the family-page string; `ai_hard_failure` | `> 3` days; `家用快照 {n} 天未更新`; hard failure only when the client cannot start |
| Q-P3 | `last_scan_kind` vocabulary | `盤中 / 收盤定盤 / EOD / 啟動` |
| Q-P4 | `simple.html` unobserved branches (no `ai_note`, no positions, exit verdict, no report, escaping) | omit the note block; header row only; `<span class='rec sell'>該賣</span>`; `<div class='meta'>尚未產生</div>`; `html.escape(quote=False)` |
| Q-P5 | `虛擬 100 萬起步` and the `-8%/-12%` legend static or derived | derived from `initial_cash` and the active `exit` params (v10 → `-8%/-21%`) |
| Q-P6 | `shadow` `state_key`/hash chain, leg pass rules, M3 formula, `reject_rate`/`n_starved`, `eq_b[0] = 1000015.36`, automatic verdict strings, `warnings[]` vocabulary | §7.6 defaults; all moot once sealed; the seed keeps the archived rows verbatim |
| Q-P7 | Sunday/Saturday EOD scope | Saturday bake inside `tune`; no Sunday run |
| Q-P8 | morning-brief 夜盤 source and macro-news count | `無資料` unless `TWQ_NIGHT_SYMBOL`; RSS `q=台股` items in the last 24 h |
| Q-P9 | exact TWSE endpoints (T86 columns, dividend calendar, holiday schedule) | §3.2 defaults; verify at implementation; hand-maintained `calendar.json` fallback |
| Q-P10 | News AI cost cap | ≤ 1 summary per symbol per scan when the item list changed (alternative: morning + EOD only) |
| Q-P11 | Pages rebuild on `GITHUB_TOKEN` pushes; repository growth | verify on first deployment, fallback `actions/deploy-pages`; accept ≈ 12 commits/day, optional manual squash |
| Q-P12 | AI prompts (notes, report, weekly review, news) are lost | minimal prompts producing the observed shapes (§8.3); Chinese, plain text for notes, markdown with the five headings for the report |
| Q-P13 | Seeding the prediction ledger (row-level history lost) | keep frozen aggregates for `by_model_horizon`/`series`/`by_horizon` and add new rows on top so published counts continue from 639/603/462 |

### 10.3 Risks

| # | Risk | Mitigation |
|---|---|---|
| K1 | Yahoo endpoints change or rate-limit hosted runners (the original already saw degraded 0050 responses) | cache + degraded guard (§3.3); `quote_fresh=false` blocks buys; `[data] WARN` events; fallback host; browser UA; replay fixtures for tests |
| K2 | 30-minute scans instead of 5-minute: stops/trails fire later; intraday `rec_code` flips are coarser | documented (viewer-neutral); the EOD mark and the 13:30 slot still apply exits; consider a 15-min cadence if the quota allows |
| K3 | Un-reproducible internals (ridge, news aggregation, tuner metric, AI prompts) make `model-health` and `news_total` drift from the lost engine | shapes are exact; values are new history from day one; flagged in the reasons/events so the owner is not misled |
| K4 | v10 changes signal magnitudes (`均線排列` ±3.7, `布林` ±1.28) while thresholds stay 3/5 → more frequent STRONG signals; sizing constant 0.0119 (≈ 1.6× v9) and trail 20.6 % change risk | shadow-validated; monitor the first weeks; a rollback is one `adopt_manual` row with the v9 string of §6.2 |
| K5 | Counter collision with open viewers if seeding is wrong (events below 6762, orders below 108) | §1.2 C3 and a test asserting the seeded counters |
| K6 | GitHub disables schedules after 60 days of inactivity or when the workflow leaves the default branch; delayed/skipped slots | bot commits keep activity; heartbeat with a 36 h grace; every run idempotent from the Taipei clock |
| K7 | `simple.html`/JSON byte drift breaking the viewer | golden tests (§9.9) on the surviving snapshot; round-trip property check on every bake |
| K8 | Prediction-ledger seeding by aggregates means per-symbol `ledger.by_horizon` and `series` history cannot be recomputed if a bug is found later | keep the seeded aggregates immutable and additive; log the seed provenance in `state/predictions.jsonl` header |
| K9 | Public repository exposes `state/` (paper account only) | no secrets in state; API keys only as Actions secrets |
| K10 | AI costs (≤ 90 `sonnet` calls/day + 10 `opus`) | cap per §Q-P10; circuit breaker persisted across runs |

---

## Appendix A — section files (evidence appendices)

| File | Owns |
|---|---|
| `docs/spec/01-data-json-contract.md` | `data.json` field-by-field, viewer shim, formatting helpers, `reward`, `model_health_brief` |
| `docs/spec/02-symbol-json-contract.md` | `symbol/<code>.json` shapes, bars/adjustment, trend, forecast fan, ledger, viewer rendering map |
| `docs/spec/03-orders-events-health-shadow-contract.md` | `orders.json`, `events.json`, `model-health.json`, `shadow.json` contracts; `simple.html` template |
| `docs/spec/04-indicators-and-technical-signals.md` | indicator recomputation proofs, technical signal inventory, weights/aggregation |
| `docs/spec/05-market-fund-news-chips-kd60-scoring.md` | market/fund/news/chips/60-min KD rules, `total`/`rec_code`, `suggest_qty` verification |
| `docs/spec/06-paper-trading-autopilot-rules.md` | account/broker/autopilot evidence, sizing residuals, shadow genes |
| `docs/spec/07-forecast-model-health-tuner-reward-events.md` | forecast models, ledger, series, tuner, reward, event catalogue, health/heartbeat, data freshness |
| `docs/spec/08-shadow-test-schedule-and-github-actions.md` | shadow A/B semantics, operational schedule evidence, GitHub Actions design |
