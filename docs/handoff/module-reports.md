# 已完成模組的代理回報(2026-11-01 雲端工作階段)

這是實作工作流中已完成代理的原始回報,給後續整合者參考。forecast 代理在回報前被中止,其模組與測試已寫完(全部測試通過),但沒有結構化回報。

## indicators
- files: /home/user/tw-quant-view/engine/indicators.py, /home/user/tw-quant-view/tests/test_indicators.py
- tests: 177 passed / 0 failed, confidence high

### 已驗證的規格主張
- ma5/ma20/ma60 = close.rolling(n).mean(): byte-exact (max err 0.0) on [n-1:] for all 9 fixture files (spec §4.1, 04 §2.1)
- bb_up/bb_low = ma20 ± 2.0·rolling std(20, ddof=1): ≤1.7e-11 on [19:] 9/9; (bb_up+bb_low)/2 == ma20; ddof=0 rejected (>1e-3 off) (04 §2.2)
- rsi = Cutler/SMA RSI-14: byte-exact (0.0) on [14:] 9/9; rsi == 50.0 only where 14-day mean gain == mean loss (04 §2.3)
- macd_sig[i] == 0.8·macd_sig[i-1] + 0.2·macd[i] on the published arrays within 1.4e-14 (all 249 steps, 9/9); macd_hist == macd − macd_sig exactly (0.0), ×2 convention rejected (04 §2.4)
- EMA12/EMA26 adjust=False recursion holds on the published macd with back-solved pre-window seeds: least-squares residual ≤2.4e-12 (9/9), signal-seed residual ≤1e-9, seeds are plausible prices (within 0.5×–2× close[0]) (04 §2.4)
- compute() itself reproduces the published macd/macd_sig/macd_hist to ≤9.1e-13 (9/9) when 3 synthetic pre-window bars place its EMA12/EMA26/signal states at the back-solved values — proves α=2/(span+1), adjust=False, first-value seeding
- window-only MACD error is a monotonically decaying transient: err[0] > err[100] > err[200] > err[249] ≤ 4.7e-7 (04 §2.4 / §2.7)
- KD(9,3,3) with bar highs/lows: compute() (first-rsv seed) ≤9.3e-9 on [70:] 9/9; 50/50 seed ≤8e-9 on [70:]; recursion seeded from published k[7]/d[7] reproduces k[8:]/d[8:] ≤1e-9 (04 §2.5)
- trend(): segments byte-identical (json.dumps compare) and summary dict-equal on 9/9 files; segments tile the window, ret = round(close[end]/close[start]−1, 4); summary.regime is the raw last-bar label (2308: last segment range, summary bear) (02 §9, spec §4.9)
- trend summary (slopes 2 dp, dist_ma60, high_252/low_252, pos_252) reproduces 9/9 from indicators computed on the 250-bar window alone; the last segment also matches 9/9
- atr14 = SMA-14 of TR incl. latest bar: matches appendix 05 §8.2 table to 4 dp on 9/9 and floor(min(0.0075·cash/atr14, 0.30·cash/price)) == rows[].suggest_qty on 9/9 (full-precision check, spec §4.11)
- sigma20 = std(ddof=1) of last 20 simple returns: equals the published baseline ci68[1] for h=1 within 1e-16 on 9/9; √h scaling for h=5/20 and 1.96× for ci95 hold (spec §4.10)
- published() yields 250 finite Python floats per key, keys in spec order, tail equal to the published arrays where warm-up is complete, and serialises with json.dumps(allow_nan=False) (spec §3.3, C4)

### 偏離 / 預設選擇
- KD seed: the stub docstring said k0=d0=50, spec §4.1 / 04 §2.5 say seed = first rsv (pandas ewm(alpha=1/3, adjust=False)); I followed the spec. kd(bars, seed=50.0) gives the 50/50 convention; both converge to the published values (tested), so output is unaffected with ≥70 pre-window bars.
- published() short-history policy: non-finite head of the window is back-filled with the first finite value of the window (later gaps forward-filled); if a whole array is non-finite (history shorter than the warm-up) the fallback is the bar closes for ma5/ma20/ma60/bb_up/bb_low, 50.0 for rsi/k/d, 0.0 for macd/macd_sig/macd_hist. Never NaN.
- trend(bars, ind, n=250): accepts either the full history (with compute() output) or the published window (with published() output), both aligned; segments and summary.regime use the last n bars, high_252/low_252 use the trailing 252 closes of the bars given (spec Q-A15), slopes use the last 20/60/120 closes or all of them when shorter. Guards: dist_ma60 = 0.0 when ma60 is not finite, pos_252 = 0.0 when high == low, segment ret = 0.0 when the start close is 0.
- atr14 with fewer than 14 bars = mean of the available true ranges; empty list → 0.0; TR of the very first bar = high − low (no previous close).
- sigma20 → 0.0 when fewer than 2 returns exist or the std is not finite (flat series gives 0.0).
- kd60 with fewer than 9 bars → (50.0, 50.0, 50.0, 50.0); with exactly one KD value k_prev/d_prev repeat k/d (no cross can fire). Values are unrounded; rounding/labels/note belong to scoring.kd60_block.
- RSI degenerate branches (loss-mean 0 → 100.0, both 0 → 50.0) and KD H9 == L9 → rsv 50.0 are the spec Q-A8 defaults; unobserved in the snapshot, unit-tested on synthetic data only.
- Extra public helpers added beyond the stub (names kept): kd(bars, seed=None) → (k_list, d_list), true_range(bars), rsi_series(close), regime_label(close, ma20, ma60).
- Not verifiable from the fixture: the 60-minute KD parameters (no bars60 fixture — synthetic hand-recursion test only), the KD seed convention (irrelevant to output), whether high_252 uses 252 or 250 bars (indistinguishable in the snapshot; 252 implemented), and BB byte-exactness (pandas rolling std is the closest variant at ≤1.7e-11 but not bit-identical to the lost engine).

### 整合注意事項
- Pipeline order for a symbol: ind_full = indicators.compute(full_history_bars); bars250, ind250 = indicators.published(full_history_bars, ind_full); trend = indicators.trend(full_history_bars, ind_full) (gives the 252-close lookback of Q-A15; trend(bars250, ind250) is identical except high/low look back only 250 closes). Always serialise ind250, never ind_full (it holds NaN during warm-up).
- trend() cannot reproduce the head segments when the indicators were computed on only 250 bars (ma60[0..58] needs pre-window history) — the cache must hold ≥310 bars (≥500 recommended per spec §3.3) for byte-identical segments; the summary is unaffected.
- kd60(bars60) consumes datafeed.bars_60m rows [iso_ts, o, h, l, c, v] (columns 2/3/4 used) and returns unrounded (k, d, k_prev, d_prev); scoring.kd60_block(k, d, k_prev, d_prev) must do round(·,1), the %.0f note from the raw values, and the label/score rules.
- scoring.suggest_qty(cash, price, atr14, params) and autopilot.size(..., atr14, ...) should pass indicators.atr14(bars) computed on the daily bars including the latest bar (only the last 15 bars matter); verified to reproduce rows[].suggest_qty 9/9 with 0.0075/0.30.
- forecast baseline should use indicators.sigma20(bars) (equals close.pct_change().tail(20).std(ddof=1)); it matches the published ci68/ci95 within 1e-16.
- publish must emit trend.summary.regime as rows[].regime; trend() returns the summary keys already in the spec order (regime, slope20, slope60, slope120, dist_ma60, high_252, low_252, pos_252) and segments keys (start, end, regime, ret).
- No helper was needed from clock.py/state.py; nothing there was touched. engine/scoring.py shows as modified in the working tree (523 insertions) by a parallel agent — not by me.

## scoring
- files: /home/user/tw-quant-view/engine/scoring.py, /home/user/tw-quant-view/tests/test_scoring.py
- tests: 99 passed / 0 failed, confidence high

### 已驗證的規格主張
- §4.2 tech_signals: signals[] byte-exact (indicator/label/score/note, emission order, float scores) and tech_total for 9/9 fixture symbols under v9 from fixture indicators{} + bars; 2308/2454 need the scan-time volume implied by their published ratio (23,003,745 / 12,476,069 shares substituted into bars[-1][5], spec [04 §3.3.6]); from the baked bars only their volume note differs (1.7/1.6 vs 2.1/1.7), label/score/order/tech_total unchanged. 0050 ratio 1.98→'2.0' reproduces with volume[-1]/mean(volume[-20:]).
- §4.2 per-item rounding: 3481 tech_total 1.37 (0.625→0.62 half-even), not 1.38; RSI/KD %d use round() (19.84→20).
- §6.8 v10 numbers with json.loads(tuner.V10_PARAMS_JSON): 均線排列 ±3.7, 均線交叉 ±0.45, RSI ±1.18, MACD ±0.63, KD cross ∓0.37 / zone ±0.24, 布林 ±1.28, 成交量 ±1.45 on the fixture symbols and on synthetic cases for every unobserved branch; sizing constant risk_frac×strong_mult == 0.011937295357720796; v9 0.005×1.5 == 0.0075.
- §4.4 fund_signals: fund_signals[] byte-exact and fund_total for 9/9 from reconstructed yfinance-style dicts (returnOnEquity/revenueGrowth/earningsGrowth/grossMargins/trailingPE); cap 2.1→1.5 (2330), 1.4000000000000001→1.4 (2317), placeholder for 0050, None fields skipped.
- §4.7 kd60_block: intraday_kd byte-exact for 9/9 from the published k/d (3481 given a prior bar with k_prev≤d_prev for 低檔黃金交叉; 2881 fed raw d=47.46 because its note 'D=47' proves the raw value was <47.5), plus rows[].kd60 / kd60_total split.
- §4.8 compose: total/rec_code/rec_text for 9/9 rows; inclusive thresholds 3.0→BUY, -3.0→SELL, ±5.0 strong; 0.75→0.8 and -2.78→-2.8 rounding; never emits -0.0.
- §4.11 suggest_qty: 9/9 rows from account.cash, rows[].price and a local SMA-14 true-range ATR over the published bars (cap binds for 2330/2317/0050, risk for the rest).
- §4.3 market_block: overview.market byte-exact ({is_open,label,index,pct,regime_label,score} key order) for the ^TWII values implied by the snapshot — previous close 46368.328125 (float32-representable); pct = (index − prev)/prev×100 reproduces -2.4941593686153634 byte-exactly whereas (index/prev − 1)×100 does not; regime range & close<ma20 → 偏空震盪 -0.5; Aug observation 偏多震盪 +0.5 reproduced on synthetic bars; four-state 多頭/空頭 ±1.0 with a switch (four_state=False collapses to ±0.5).
- §4.3 market_state: Q-A2 thresholds (1d ≤ -2.0 % or 5d ≤ -3.5 %); market_returns formats the observed event text '市場狀態:halt(大盤單日 -2.5%、5日 -3.6%)'.
- §4.6 chips_block: recent[] (10 newest first, ints, key order) 9/9; 投信動向 9/9 from the 10 rows; whole block byte-exact for 2317/2882/2881/2308 from the 10 rows (2308's 法人賣壓動能 note 'z 分數 -2.06' reproduces exactly with population std over rolling 3-day sums); 外資連賣16日 (score -1.5, note) for 2330/2454/0050 once 6 older selling days are prepended (10 rows alone give 外資連賣10日); 3-4 day tier ±1.0, zero day breaks streaks, ±1.5 cap verified synthetically.
- §4.5 news_block: items[] shape/key order/sentiment/float score byte-exact 9/9; Q-A12 default aggregate at 2026-10-31T14:15:22+08:00 reproduces news.score for 2317 (0.0) and 3481 (-1.07) only; the other 7 keep the sign (checked) but not the value. lexicon_score unit-tested on 8 headlines; against the 70 Oct items the spec lexicon matches 60/70 exactly, 62/70 in sign.

### 偏離 / 預設選擇
- news.score: kept the Q-A12 default; it reproduces 2/9 at the snapshot time (2317, 3481) and 1/9 at the 18:17 last-scan time; 2330 (0.5), 2454 (-0.33), 2308 (-1.34), 2882 (-0.83), 0050 (0.17), 6789 (-0.37), 2881 (0.42) are not reproduced (refresh times lost; spec says the original formula is undetermined). news_block also caps at the first 8 items and re-emits each item with the exact key order and sentiment derived from the score sign.
- chips 法人動能 z: population std (ddof=0) over rolling 3-day sums of the last ≤60 days — chosen because it reproduces 2308's published -2.06 byte-exactly from the 10 rows (sample std gives -1.92); minimum 10 days of history (CHIPS_Z_MIN_DAYS) else no signal; std 0 → no signal. 0050 (-1.08), 6789 (-1.02) and 3481's silence need the real 60-day T86 history the snapshot does not hold (10 rows give +0.08 / -1.26 / -1.12).
- kd60: 低檔 (+0.3) also when K<20 with a death cross (only a golden cross upgrades to 低檔黃金交叉); mid-range crosses → 中性 0.0; k_prev/d_prev may be None (no cross).
- tech_signals raises ValueError on non-finite indicator values or <2 bars (indicators guarantee finiteness per §4.1); a missing weight key counts as 1.0.
- fund_signals: ROE ≤ 0, growth == 0, margin < 0.25, PE ≤ 50 fire nothing; non-numeric/NaN source fields treated as None; fund_cap taken from params (default 1.5).
- market_block: with index_now the previous close is the last bar's close unless that bar is dated at.date() (then the bar before it); regime from the bars as given (ma20/ma60 of closes, min_periods semantics: <60 bars → no bull/bear, <20 → 盤整 0.0); empty bars → index 0.0, pct 0.0, 盤整.
- compose zeroes mkt_score / fund_total when use_market / use_fundamentals is false and derives strong thresholds from STRONG_GAP when absent; suggest_qty returns 0 for non-positive cash/price/atr14.
- Added public helpers beyond the stub: volume_ratio(bars), chips_zscore(totals_asc), market_returns(twii_bars) → (pct1, pct5), sizing(params) (SAFE constants fallback, duplicated locally because tuner.sizing is still a stub), sentiment(score); module constants LEXICON, MARKET_FOUR_STATE, HALT_*_PCT, CHIPS_*, NEWS_* are the documented defaults.

### 整合注意事項
- Volume ratio is computed from bars[-1][5]; for a live intraday scan the pipeline must write the realtime quote volume into the last bar (or a copy) before calling tech_signals — this is how the published 2308/2454 notes (2.1/1.7) arose.
- fund_signals expects yfinance Ticker.info keys (returnOnEquity, revenueGrowth, earningsGrowth, grossMargins, trailingPE; fractions, PE plain); datafeed should pass None for missing keys.
- chips_block takes ascending [(date, {foreign,invtrust,dealer,total}), ...]; datafeed should keep ≥ 60 trading days of T86 (streaks of 16 and the 60-day z need it); .TWO / empty → {score 0.0, signals [], recent []}. total is recomputed when absent.
- kd60_block needs the last two 60-minute K/D values from the indicators module (KD(9,3,3) on 60-min bars); pass the unrounded values — rounding to 1 dp and the %.0f note are done inside; rows[].kd60 = block minus 'score', rows[].kd60_total = block['score'].
- news_block(items, at): items already scored (ai.py / lexicon_score fallback), 'at' = the refresh time; the symbol news.score must be written to rows[].news_total on every refresh while total/rec_code are recomputed only in a scan (Q-A17). The 消息面 event (|score| ≥ 1.0) is the caller's job.
- market_block(twii_bars, at, is_open, index_now): caller decides is_open from clock.is_open; pass ^TWII daily bars oldest first; rows[].mkt_score = market['score'] when use_market else 0.0. market_state() / market_returns() feed the G3 halt gate and the '市場狀態:halt(大盤單日 {pct1:+.1f}%、5日 {pct5:+.1f}%)' event text.
- suggest_qty uses params['sizing'] when present (v10) else SAFE constants; published value is the strong-mult size regardless of rec_code; autopilot order sizing (×caution_scale, BUY vs STRONG_BUY, 40 % cap, round lots) is out of scope here (§5.6).
- No -0.0 / NaN is ever produced (all rounded outputs go through round()+0.0); every block round-trips through state.dumps. git status also shows engine/indicators.py and tests/test_indicators.py modified by another agent — not touched by me.
