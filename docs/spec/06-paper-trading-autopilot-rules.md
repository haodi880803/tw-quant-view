# 06 — Paper-trading account, broker and autopilot rules (reconstructed from evidence)

Scope: the rules that turn the watchlist scores (specs 01/04) into paper orders, positions and the account figures baked into `data.json`, `orders.json`, `events.json` and `shadow.json`. Written for the Python 3.13 rebuild; nothing here is engine code.

Evidence base (all read-only):

| Source | What it gives |
|---|---|
| `orders.json` @ 2026-10-31 (ids 108…59, 50 rows) and `git show 2e74138:orders.json` @ 2026-08-15 (ids 26…17, 10 rows) | 60 fills: 50 BUY, 10 SELL |
| `data.json` @ 2026-10-31 and @ 2026-08-15 | `overview.account`, `positions[]`, `rows[].suggest_qty`, `engine`, `market`, `reward`, `ai_report` (the 2026-10-12 report lists all 8 positions, cash and realized P&L at 14:16 that day; the 2026-08-01 weekly review names the gates G1/G3/G4 and the tuner rules) |
| `events.json` @ both dates (100 rows each) | broker fills, gate blocks, swap, 晨會, halt, EOD, tuner messages |
| `shadow.json` @ both dates | the two-arm shadow experiment incl. `genes[]` |
| `model-health.json.params_history[]` | the active parameter set (`buy_th 3.0, strong_th 5.0, sell_th -3.0, strong_sell_th -5.0, exit {stop_pct 0.08, trail_pct 0.12}`) |
| `app.js` l.296–322 (`DEFAULT_FEES`/`estimate`), l.1928–1938 (autopilot confirm text), l.1934, `simple.html:68` | fee model and the autopilot's own description |
| `symbol/<code>.json.bars` (current, dividend-adjusted) and the 2026-08-15 copies | daily OHLC used to test peak tracking and the sizing volatility |

Conventions: all timestamps are Taipei ISO strings with explicit offset, second precision, e.g. `"2026-10-31T14:15:22+08:00"`; money is NTD; `floor()` is integer floor; `round(x, 2)` is Python's round. Confidence: **high** = reproduced exactly on every observation; **medium** = consistent with all observations but under-determined; **low** = plausible reading of sparse evidence.

Autopilot's own description (verbatim, `app.js:1931–1938`, shown when switching it on):

```
開啟「自動交易(紙上)」?

引擎將在每輪掃描後自動買賣【虛擬】部位:
・先出場:持股觸發停損/移動停利、或建議轉賣出 → 全數賣出
・再進場:買進/強力買進訊號 → 按建議部位 %(自己的本金換算)買入;已持有可加碼
  (每檔每天最多加碼 1 次,單一持股 ≤ 權益 40%)
・每輪最多 3 筆,風控上限與 KILL 開關照常生效
・每筆自動單都會在訂單紀錄標「自動」並寫入運作日誌

此開關只影響紙上虛擬帳戶;真錢每一筆永遠需要你手動確認。
```

`simple.html:68` legend: `賣出主要由出場機制執行:跌破停損價(-8%)或從高點回落至移停價(-12%)時狀態轉「該賣」,自動交易開啟時會自動出場。`

---

## 1. Account model

### 1.1 Reset and starting state (**high**)

* `initial_cash = 1000000.0`. Replaying orders 17→26 forward from cash = 1 000 000 with the cash-flow rule of §1.2 reproduces the 2026-08-15 `account.cash = 55760.09000000002` to the cent, so on 2026-08-05 09:15 (order 17) the account held exactly 1 000 000 cash and **no positions**. The July account (3 positions, equity 1 015 076 on 2026-07-16 per the old `index.html`) was wiped; `reward.history` shows `2026-07 … equity_close 1000000.0, partial: true` and `2026-08 equity_open 1000000.0`, i.e. the reset happened between 2026-07-18 (params v5/v6, "v4 於 7/17 崩盤日無停損的教訓") and 2026-08-01, with `realized_pnl` reset to `0.0`.
* Order ids are a global autoincrement that survived the reset (July orders were ids 1–16; the first post-reset order is 17; the gap 27–58 is simply the 32 orders between 2026-08-15 and 2026-09-21 that fall outside both 50/10-row windows).

### 1.2 Fields and identities (`overview.account`) (**high**, exact in both snapshots)

| Field | Definition | Evidence |
|---|---|---|
| `cash` | running float; BUY: `cash -= qty×filled_price + fee`; SELL: `cash += qty×filled_price − fee − tax` | forward ledger 1 000 000 → 55 760.09 (Aug, 10 orders) and backward ledger from 269 729.55 reaches the AI-report cash `14,249` at 2026-10-12 14:16 (±0.5) |
| `positions_value` | `Σ positions[].value`, `value = qty × price` | 0.000000 residual, both snapshots |
| `equity` | `cash + positions_value` (float sum, no rounding) | 0.000000 residual |
| `realized_pnl` | cumulative `Σ pnl` over every SELL since the reset (unrounded float, e.g. `-23213.919999999875`) | Σ pnl of the 10 window SELLs = 3 577.91 → pre-window realized = −26 791.83; the 2026-10-12 report's `已實現 -4,332` = −26 791.83 + Σ pnl(ids 71,73,89,97 = 22 459.45) = −4 332.38 ✓ |
| `unrealized_pnl` | `Σ qty × (price − avg_price)` using the **2-dp `avg_price`** that is emitted | 0.000000 residual in both snapshots (using the unrounded average gives 33 314.49 ≠ 33 314.96) |
| identity | `equity − initial_cash == realized_pnl + Σ qty×(price − avg_unrounded)` | exact (0.0000) in Aug where every lot is in-window; the published `unrealized_pnl` differs from that term by the rounding of `avg_price` (−2.99 Oct, −9.13 Aug) |

### 1.3 Position ledger (`overview.positions[]`)

| Field | Rule | Confidence / evidence |
|---|---|---|
| `qty` | shares; odd lots allowed (1, 2, 17 … observed) | high |
| `avg_price` | **fee-inclusive** average cost: `cost += qty×filled_price + fee` on each BUY, `avg = cost / qty`; kept unrounded internally, emitted `round(avg, 2)`; on a SELL the remaining lot keeps the same average | high — all 6 SELLs whose lot was bought entirely inside the window reproduce `pnl` to the cent only with this average (§2.4); the 2026-10-12 report's `2308 … 17 … 1,928.96` = (32 731.29 + 61)/17 |
| | consequence: the NT$20 minimum fee inflates tiny lots — the 21-share 3481 lot of 2026-09-22/23 (fills 51.63/51.83/50.63, three × NT$20) carries `avg = 54.411`, so its stop `50.06` sat **above** the market and fired the next scan after the third add (order 71) | high |
| `price` | last quote at bake time (= `rows[].price`) | high |
| `value` | `qty × price` | high |
| `ret_pct` | `round((price / avg_unrounded − 1) × 100, 2)` | high (8/10 exact on the 2-dp average, the 2 misses are 0.01 rounding) |
| `stop_price` | `round(avg_unrounded × (1 − stop_pct), 2)`, `stop_pct = 0.08` | high (10/10 incl. 3 cases that only match with the unrounded average) |
| `peak` | running max of **every price the position has been marked at**: each BUY `filled_price` and the quote at every scan while held; reset when the position is fully closed | medium-high, see §4.3 |
| `trail_price` | `round(peak × (1 − trail_pct), 2)`, `trail_pct = 0.12` | high (10/10) |
| `verdict` | `"hold"` or an exit value; `reasons[]` strings | only `hold`/`[]` observed (autopilot sells on the same scan, so a non-hold verdict never survives to a bake) |

### 1.4 Monthly scoreboard (`overview.reward`, for completeness) (**high** on the observed rows)

`base_points = round(ret × 1000)` where `ret = equity_close/equity_open − 1` (2026-09: 1 040 392.13/1 015 475.4 → 24.54 → `25`; 2026-08 → 15.48 → `15`; provisional 2026-10: 1 010 098.05/1 040 392.13 → −29.1 → `-29`); `bonus_high = 10` when `new_high`; `bonus_beat = 0` observed (never beat the index); `points = base + bonuses`; `total_after` cumulative; a month without a full equity series is `{"month": …, "skipped": true, "reason": "缺月初或月底權益基準(該月系統未完整運行)"}`.

---

## 2. Broker model (`orders.json`)

### 2.1 Order record (**high**, 60/60)

| Field | Rule |
|---|---|
| `id` | autoincrement int, newest first in the file (window = last 50) |
| `created_at` = `filled_at` | scan time at second precision; paper fills are immediate; up to 3 orders share one timestamp |
| `symbol` / `code` / `name` | `"2317.TW"` / `"2317"` / `"鴻海"` |
| `side` | `"BUY"` / `"SELL"` |
| `qty` | int shares (§5) |
| `price_hint` | the quote the decision was made on, 2 dp (`245.5`, `112.65`, `46.95`) |
| `status` | `"FILLED"` on all 60; viewer vocabulary `FILLED 成交, REJECTED 拒絕, PENDING 等待, CANCELLED 取消` (app.js l.36–38) |
| `filled_price` | `round(price_hint × (1 + 0.0005), 2)` for BUY, `round(price_hint × (1 − 0.0005), 2)` for SELL — deterministic 5 bp slippage (`slippage_bps: 5`, app.js l.307) |
| `fee` | `max(20, round(gross × 0.001425 × 0.6))`, `gross = qty × filled_price` (0.1425 % × 60 % discount, NT$20 minimum), float with integer value |
| `tax` | SELL: `round(gross × 0.003)`; BUY: `0.0` |
| `pnl` | BUY: `null`; SELL: `qty×filled_price − fee − tax − qty×avg_unrounded`, **not rounded** (`-3664.7299999999586`) |
| `mode` | `"paper"` (viewer also knows `"real"` → `實盤`) |
| `source` | `"autopilot"` on all 60 (viewer chips it `自動`); manual orders unobserved |
| `note` | template, §2.3 |

Exits always sell the **entire** position (10/10; e.g. order 107 sold all 1 571 shares of 0050 held per the 2026-10-12 report).

### 2.2 Events emitted per fill (`source: "broker"`, `level: "INFO"`, same second as the order) (**high**)

* BUY: `紙上買單成交:{code} {name} {qty} 股 @ {filled_price},手續費 {fee} 元,總支出 {round(gross+fee):,} 元。` → `紙上買單成交:2317 鴻海 193 股 @ 245.62,手續費 41 元,總支出 47,446 元。`
* SELL: `紙上賣單成交:{code} {name} {qty} 股 @ {filled_price},手續費 {fee} 元,證交稅 {tax} 元,已實現損益 {round(pnl):+,} 元。` → `紙上賣單成交:0050 元大台灣50 1571 股 @ 105.15,手續費 141 元,證交稅 496 元,已實現損益 -3,665 元。` (sign always printed, thousands separator)
* Swap adds an `engine` INFO line: `自動換股:賣出 {code} {name}(評分 {s:+.1f})讓位給 {code2} {name2}(評分 {s2:+.1f})` → `自動換股:賣出 0050 元大台灣50(評分 -2.0)讓位給 2317 鴻海(評分 +3.0)`

### 2.3 `note` templates — every distinct template in the 60 orders (**high**)

| Template (verbatim) | Count | Meaning |
|---|---|---|
| `訊號進場({rec_text},評分 {s:+.1f})` | 14 | BUY opening a position; `rec_text` was `買進` in all 14 (scores 3.0–4.9) |
| `訊號加碼({rec_text},評分 {s:+.1f})` | 36 | BUY adding to a held position; `買進` 19 ×, `強力買進` 17 × |
| `觸發停損:現價跌破進場價 -8%({stop_price:.2f})` | 3 | stop-loss exit |
| `觸發移動停利:從高點 {peak:.2f} 回落 -12%({trail_price:.2f})` | 3 | trailing-stop exit |
| `觸發停損:現價跌破進場價 -8%({stop:.2f});觸發移動停利:從高點 {peak:.2f} 回落 -12%({trail:.2f})` | 1 | both triggered on the same scan, joined with `;` |
| `換股:讓位給 {code} {name}(評分差 {d:+.1f})` | 3 | rotation sell; `d = score_new − score_sold` |

`-8%` / `-12%` are `round(stop_pct×100)` / `round(trail_pct×100)` of the active params; prices inside notes are 2 dp (`2085.00`, `53.90`). No `訊號出場`/signal-driven sell note was observed (§4.4).

### 2.4 Cost basis / pnl verification

| SELL id | lot (buy ids) | fee-incl. avg | `pnl` file | recomputed | with fee-free avg | with 2-dp avg |
|---|---|---|---|---|---|---|
| 71 (3481) | 66, 67, 70 | 54.4110 | −116.05 | −116.05 | −56.05 | −116.03 |
| 99 (2308) | 62, 78, 91 | 1928.9582 | −2579.42 | −2579.42 | −2518.42 | −2579.45 |
| 103 (2454) | 98 | 4612.30 | −437.40 | −437.40 | −417.40 | −437.40 |
| 104 (2308) | 102 | 1810.90 | −333.46 | −333.46 | −313.46 | −333.46 |
| 105 (6789) | 74, 77, 87, 92 | 477.1219 | −8977.63 | −8977.63 | −8848.63 | −8977.20 |
| 106 (3481) | 82, 83, 86, 95, 100 | 51.9084 | −2888.90 | −2888.90 | −2788.90 | −2889.80 |

---

## 3. Inputs the autopilot reads each scan

| Input | Where | Values |
|---|---|---|
| per-symbol `total` score and `rec_code`/`rec_text` | `rows[]` (spec 01/04) | thresholds from the active params: `BUY` ≥ `buy_th 3.0`, `STRONG_BUY` ≥ `strong_th 5.0`, `SELL` ≤ `sell_th -3.0`, `STRONG_SELL` ≤ `strong_sell_th -5.0`, else `HOLD`; labels `買進 / 強力買進 / 觀望 / 賣出 / 強力賣出` |
| per-symbol quote | `rows[].price` → `price_hint` (2 dp) | |
| market regime | `market.regime_label` / `market.score` (`偏多震盪 +0.5`, `偏空震盪 -0.5`); the 晨會 override `無覆蓋` / `風險覆蓋 caution`; the EOD `市場狀態:halt(大盤單日 -2.5%、5日 -3.6%)` | see §4.1 gate G3 |
| previous close score | used by gate G4 | |
| `engine.kill` | KILL file → all order placement blocked (`KILL 檔存在,下單封鎖中`) | |
| `engine.autopilot` | master switch (`true` in both snapshots) | |

Recommendation changes are logged as `engine` INFO events `{code} {name}:{old}→{new}` (e.g. `2317 鴻海:觀望→強力買進`) at the scan that changes them; `rows[].changed = true` for those symbols.

---

## 4. Decision rules

Order of operations inside one scan (from the autopilot text `先出場 … 再進場` and the same-second SELL→BUY pairs 73/74, 97/98, 99/100, 107/108): **(1) exits, (2) swaps, (3) entries/adds in descending score order**, at most **3 orders per scan** (max observed per timestamp = 3; 7 timestamps carry exactly 3; the ids inside every same-second group are in descending score order, e.g. 76/77/78 = +7.5/+6.9/+6.0, 94/95/96 = +5.0/+4.5/+3.5).

### 4.1 Buy gates (logged as `engine` INFO `閘門攔截 {code} 買進:G{n}:{detail}`)

| Gate | Observed message (verbatim) | Rule | Confidence |
|---|---|---|---|
| G1 / freshness | none in the two windows; the 2026-08-01 weekly review: `G1/freshness — … 擋下 132 筆` | reject a buy when the quote is stale (`quote_fresh == false` / older than the scan interval) | low (template unknown) |
| G3 / regime | `閘門攔截 2881 買進:G3:市場 caution(晨會覆蓋:隔夜情勢(caution)),禁加碼` (3 ×, 2026-10-30; all three symbols were already held) | under `caution` (set by the 晨會 override) **adds are forbidden**; a new entry is still allowed but sized ×0.5 (§5.3, order 108 the same day); the review says this gate blocked 365 buys in May–Aug, i.e. it also blocks on the regime score itself (`大盤環境不利 → 全面禁買`) | medium |
| G4 / persistence | `閘門攔截 6789 買進:G4:2026-08-13 收盤評分 -0.6 未達 buy_th +3.0,訊號未跨日持續` | a buy requires the **previous close's** score ≥ `buy_th` as well (gene `persistence = 2` scans/days) | high |
| halt | `市場狀態:halt(大盤單日 -2.5%、5日 -3.6%)` (EOD 2026-10-30) | market state `halt` → no buys (exits still run) | medium (thresholds unknown) |
| KILL | `engine.kill` | no orders at all | high (viewer) |

### 4.2 Entry / add rules

| # | Rule | Evidence | Confidence |
|---|---|---|---|
| E1 | Entry when `rec_code ∈ {BUY, STRONG_BUY}` and the symbol is not held → `訊號進場` | 14 entries, all with `買進` | high |
| E2 | Add when BUY/STRONG_BUY and already held → `訊號加碼`; at most **one add per symbol per day** (entry + one add on the same day is allowed: 2317 08-05 09:15/09:25, 3481 09-22 11:11/11:16, 3481 10-01 09:10/09:15) | 36 adds, never 2 adds of one symbol on one day | high |
| E3 | Adds are not conditioned on the position's P&L or on cash level (adds of 1–3 shares with cash 547–1 894 NTD on 2026-09-22/23) | orders 62–72 | high |
| E4 | No cash reserve: cash fell to 547.52 NTD after order 70 and 924 after 68 | ledger | high |
| E5 | Minimum 1 share when `cash ≥ price` (orders 62, 98 where the sizing formula yields 0) | §5.4 | medium |
| E6 | Single position ≤ 40 % of equity (`單一持股 ≤ 權益 40%`) | autopilot text; max observed 36 % (2317 Aug, 2330 Oct) — never seen binding | medium |
| E7 | Max positions: none below the watchlist size (9 held on 2026-10-12 after order 98) | ledger | high |
| E8 | Re-entry after an exit is allowed on the next trading day (2308 sold 10-13 11:27 → bought 10-14 11:46; 2454 sold 10-08 → bought 10-12; 2882 sold 09-25 → bought 09-29); same-day re-entry never observed | ledger | medium (no same-day evidence either way) |
| E9 | Entries/adds use `rec_text` of the scan; `強力買進` only changes sizing (§5.3) and the note | | high |

### 4.3 Swap (`換股`) rule

| Observation | sold (score) | bought (score) | `評分差` | cash before the sell | positions before |
|---|---|---|---|---|---|
| 2026-09-25 09:02:37, ids 73/74 | 2882 (+2.0) | 6789 (+4.1, new) | +2.1 | 1 125 | 7 |
| 2026-10-12 10:01:27, ids 97/98 | 2317 (+1.5) | 2454 (+3.8, new) | +2.3 | 2 767 | 8 |
| 2026-10-30 12:58:20, ids 107/108 | 0050 (−2.0, `觀望` at the time; `賣出` only from 18:17) | 2317 (+3.0, new) | +5.0 | 152 622 | 4 |

Rule (medium): when a **non-held** symbol gets a BUY signal and some held symbol's score is lower by at least **X**, sell the lowest-scored holding completely (`換股:讓位給 …`, event `自動換股:…`) and then open the new one in the same scan, sized on the post-sale cash (§5.3 reproduces 193 shares exactly). Smallest observed gap is 2.1 → X ≤ 2.1; proposed X = 2.0 (= gene `strong_gap`). The 2026-10-30 case shows the swap is **not** conditional on cash starvation (152 k cash) — unless the engine also keeps an unobserved cash-reserve test; see Open questions. Adds never trigger a swap.

### 4.4 Exit rules

| # | Rule | Evidence | Confidence |
|---|---|---|---|
| X1 | Stop-loss: at every scan, if `price_hint ≤ stop_price` sell all → `觸發停損:現價跌破進場價 -8%({stop})` | ids 71, 103, 104 (+106): 50.0 ≤ 50.06, 4210 ≤ 4243.32, 1660 ≤ 1666.03 | high |
| X2 | Trailing stop: if `price_hint ≤ trail_price` sell all → `觸發移動停利:從高點 {peak} 回落 -12%({trail})`; the comparison is **inclusive** (id 105: `price_hint 440.0`, `trail 440.00`) | ids 89, 99, 105: 4725 ≤ 4725.60, 1785 ≤ 1834.80 | high |
| X3 | Both true on the same scan → one SELL with the two notes joined by `;` (stop first) | id 106 | high |
| X4 | Exits are evaluated on intraday quotes at every scan, incl. the 09:00 open scan (ids 103 09:00:21, 106 09:00:43) and the 13:29 scan | timestamps | high |
| X5 | Signal exit (`建議轉賣出 → 全數賣出`, i.e. `rec_code ∈ {SELL, STRONG_SELL}` on a held symbol) | autopilot text and the shadow's `reason: "訊號"`; never observed in the 60 orders (0050 turned `賣出` on 10-30 18:17 only after it had been swapped out; 2308 `強力賣出` while not held) | medium; note template unobserved — proposed `訊號出場({rec_text},評分 {s:+.1f})` |
| X6 | Exits take priority over buys and are not limited by the 3-orders cap being consumed by buys (`先出場`) | ordering of same-second pairs | medium |

Peak tracking evidence (`peak` vs the daily bars over the lot's life):

| Lot | `peak` in note/position | max daily high | max daily close | reading |
|---|---|---|---|---|
| 6789 2026-09-25→10-15 (id 105) | 500.00 | 505.0 (10-01) | 494.0 | below the high, above the close |
| 2308 2026-09-22→10-13 (id 99) | 2085.00 | 2115.0 (10-06) | 2050.0 | same |
| 3481 2026-10-01→10-20 (id 106) | 53.90 | 56.2 (10-05) | 52.8 | same |
| 2454 …→10-08 (id 89) | 5370.00 | 5480.0 (09-22) | 5285.0 | same |
| 2881 Aug position | 129.56 | 130.0 | 129.5 | = the first fill price (08-06 `filled_price 129.56`) |
| 2317 opened 2026-10-30 12:58 | 246.0 | 246.0 | 245.5 | an afternoon quote after the 245.62 fill |
| 2330 Oct | 2585.0 | 2590.0 | 2585.0 | |
| 2882 Oct | 118.0 | 118.0 | 116.5 | |

→ `peak = max(fill prices, quotes seen at scans since the position was opened)`; it is **not** the daily high and **not** the close; it resets when the position is closed (2317 re-entered on 10-30 starts at 245.62/246.0, not at the 273.0 of August). Implementation: `peak = max(peak, filled_price)` on every BUY and `peak = max(peak, price)` on every scan while `qty > 0`. (medium-high)

---

## 5. Sizing

### 5.1 `rows[].suggest_qty` (**high** — 18/18 snapshot rows)

```
atr_pct   = mean(TR[-14:]) / close[-1]          # TR_i = max(H_i−L_i, |H_i−C_{i−1}|, |L_i−C_{i−1}|) on the daily bars incl. the latest close
f         = min(0.30, 0.0075 / atr_pct)
suggest_qty = floor(f × cash / price)             # cash = account.cash, price = rows[].price
```

| Row | f actual (interval) | atr14 | f model | qty model | qty file |
|---|---|---|---|---|---|
| OCT 2330 | ≥0.2987 | 0.0161 | 0.300 (cap) | 34 | 34 |
| OCT 2317 | [0.2994, 0.3004) | 0.0247 | 0.300 (cap) | 329 | 329 |
| OCT 2454 | [0.1451, 0.1597) | 0.0470 | 0.149 | 10 | 10 |
| OCT 2308 | [0.1138, 0.1188) | 0.0540 | 0.116 | 23 | 23 |
| OCT 2882 | [0.2563, 0.2567) | 0.0298 | 0.256 | 596 | 596 |
| OCT 0050 | [0.3000, 0.3004) | 0.0190 | 0.300 (cap) | 771 | 771 |
| OCT 6789 | [0.1402, 0.1417) | 0.0495 | 0.140 | 92 | 92 |
| OCT 3481 | [0.1380, 0.1382) | 0.0490 | 0.138 | 875 | 875 |
| OCT 2881 | [0.2605, 0.2611) | 0.0292 | 0.261 | 435 | 435 |
| AUG 2330 | [0.2577, 0.3007) | 0.0286 | 0.268 | 6 | 6 |
| AUG 2317 | [0.1768, 0.1815) | 0.0429 | 0.180 | 38 | 38 |
| AUG 2454 | [0.0755, 0.1510) | 0.0688 | 0.124 | 1 | 1 |
| AUG 2308 | [0.1014, 0.1352) | 0.0718 | 0.119 | 3 | 3 |
| AUG 2882 | [0.2257, 0.2275) | 0.0339 | 0.227 | 124 | 124 |
| AUG 0050 | [0.2595, 0.2614) | 0.0301 | 0.264 | 138 | 136 (*) |
| AUG 6789 | [0.1190, 0.1270) | 0.0641 | 0.122 | 15 | 15 |
| AUG 3481 | [0.1087, 0.1096) | 0.0736 | 0.109 | 121 | 121 |
| AUG 2881 | [0.2485, 0.2508) | 0.0306 | 0.249 | 107 | 107 |

(*) the only miss: 0050's bars are dividend-adjusted in today's file and its 08-14 bar was flagged stale (`0050.TW 本次最新日期 2026-08-13 落後快取 2026-08-14(疑似劣化回應),保留舊快取`), so the ATR the engine saw differed slightly. Across the 17 exact rows the constant is pinned to `k ∈ [0.007497, 0.007505)` → **0.0075 = risk_frac 0.005 × strong_mult 1.5** (whether the engine literally multiplies the genes or stores 0.0075 is unknowable; both give identical output). Variants tested and rejected: σ of simple/log returns over 3–60 days, EWMA, Parkinson, mean/median |return|, Wilder/EMA ATR, the forecast `ci68` widths (ratios 0.90–1.18).

`suggest_qty` is a fraction of **cash** (not equity): with cash 55 760 in Aug every row is 0.4–1.4 % of equity; with cash 269 730 in Oct the capped rows are 7.98–8.01 % of equity only because 0.3 × cash happened to be ≈ 8 % of equity.

### 5.2 Order quantity (autopilot) — what is certain (**high**)

| Rule | Evidence |
|---|---|
| Budget base is the **current cash, updated order by order inside a scan**; candidates are processed in **descending score order** (ids 76→77→78 = 7.5, 6.9, 6.0; 79→80→81 = 5.5, 4.8, 4.3; 94→95→96 = 5.0, 4.5, 3.5; 84→85→86 = 6.8, 5.8, 4.9; every same-second group obeys this, none obeys watchlist order; tie 91/92 at 6.0 → watchlist order) | 50/50 BUYs have `qty × price_hint ≤ 0.3004 × cash_before`; same-second triples only fit sequential cash |
| Hard cap `f ≤ 0.30` of cash per order | 40 of the 50 BUY intervals `[qty×price/cash, (qty+1)×price/cash)` contain 0.30 and 15 of them are pinned to `[0.2974, 0.3004)`; none exceeds 0.3004; e.g. 100: `floor(0.3 × 44 461.87 / 50.2) = 265` ✓, 101: `floor(0.3 × 31 130.92 / 113) = 82` ✓ |
| `強力買進` orders: all 18 intervals contain the 0.30 cap and none exceeds it → `strong_mult 1.5` is applied **before** the cap (a multiplier after the cap would give 0.45) | 19, 59, 60, 61, 68, 72, 76–79, 84, 85, 91–94, 100, 101 |
| `caution_scale 0.5` is applied **after** the cap on a 晨會-caution day | order 108 (2026-10-30, `風險覆蓋 caution`): `floor(0.15 × 317 175.21 / 245.5) = 193` ✓ exact (0.3 × pre-sale cash would give 186, 0.2 → 258) |
| `qty = floor(budget / price_hint)` (price_hint, not the slipped fill) | 265/82/193 above |
| round-lot rounding when ≥ 1000 shares: order 18 bought exactly **2000** shares of 2882 where 0.3 × cash/price = 2463 | low (single observation; the shadow's three 1000-share fills support a 1000-share lot rule, §6) |

### 5.3 Order quantity — best-fitting formula and residuals

Model: `qty = max(1, floor(min(0.30, 0.0075 × (1.5 if 強力買進 else 1) / atr14_pct(prev close)) × (0.5 if caution) × cash_before / price_hint))`, i.e. the §5.1 rule with the two gene multipliers. It reproduces **24 of 50** BUY quantities exactly, including 15 of the 18 strong orders and the caution order (108); the 26 misses (23 `買進`, 3 `強力買進`):

| id | code | date | cash before | qty | f actual | f model | qty model |
|---|---|---|---|---|---|---|---|
| 17 | 2317 | 08-05 | 1 000 000 | 675 | 0.1745 | 0.169 | 653 |
| 18 | 2882 | 08-05 | 825 276 | 2000 | 0.2436 | 0.231 | 1896 |
| 19 | 2317 | 08-05 | 624 004 | 728 | 0.2998 (strong) | 1.5×0.169 = 0.253 | 614 |
| 20 | 2330 | 08-06 | 436 653 | 40 | 0.2185 | 0.210 | 38 |
| 21 | 2454 | 08-06 | 341 124 | 18 | 0.2127 | 0.101 | 8 |
| 22 | 2881 | 08-06 | 268 485 | 465 | 0.2243 | 0.232 | 481 |
| 23 | 0050 | 08-07 | 208 188 | 450 | 0.2243 | 0.228 | 457 |
| 24 | 2330 | 08-10 | 161 438 | 20 | ≥0.2961 | 0.237 | 16 |
| 25 | 2882 | 08-14 | 113 573 | 340 | 0.2994 | 0.228 | 259 |
| 26 | 2881 | 08-14 | 79 527 | 184 | 0.2985 | 0.243 | 149 |
| 63 | 2881 | 09-22 | 5 202 | 10 | 0.2989 | 0.250 | 8 |
| 64 | 2882 | 09-22 | 3 626 | 9 | 0.2792 | 0.228 | 7 |
| 66 | 3481 | 09-22 | 1 894 | 11 | 0.2996 | 0.187 | 6 |
| 67 | 3481 | 09-22 | 1 307 | 7 | 0.2775 | 0.187 | 4 |
| 70 | 3481 | 09-23 | 547 | 3 | 0.2776 | 0.184 | 1 |
| 74 | 6789 | 09-25 | 297 723 | 143 | 0.2236 | 0.196 | 125 |
| 75 | 2882 | 09-29 | 231 067 | 463 | 0.2244 | 0.244 | 503 |
| 78 | 2308 | 10-01 | 88 888 | 13 | 0.2823 (strong) | 1.5×0.160 = 0.240 | 11 |
| 100 | 3481 | 10-13 | 44 462 | 265 | 0.2992 (strong) | 1.5×0.161 = 0.241 | 213 |
| 81 | 2881 | 10-01 | 34 294 | 68 | 0.2974 | 0.269 | 61 |
| 82 | 3481 | 10-01 | 24 069 | 134 | 0.2990 | 0.194 | 86 |
| 83 | 3481 | 10-01 | 16 849 | 94 | 0.2974 | 0.194 | 61 |
| 86 | 3481 | 10-07 | 6 014 | 35 | 0.2974 | 0.165 | 19 |
| 87 | 6789 | 10-07 | 4 204 | 2 | 0.2329 | 0.204 | 1 |
| 95 | 3481 | 10-12 | 5 605 | 32 | 0.2952 | 0.164 | 17 |
| 102 | 2308 | 10-14 | 21 840 | 2 | 0.1648 | 0.147 | 1 |

Reading of the residuals (medium): 14 `買進` misses (24–26, 63, 64, 66, 67, 70, 81–83, 86, 87, 95) and the 3 strong misses (19, 78, 100) were filled at the full 0.30 cap although the ATR rule gives 0.16–0.27 (×1.5 = 0.24–0.25 for the strong ones) — all but 19 in low-cash situations (cash ≤ 161 k) — while the misses with large cash (17, 18, 20–23, 74, 75) sit a few percent off the ATR value and four of them (22, 23, 74, 75) share `f ≈ 0.2245 ± 0.0003` on different symbols and dates. So the autopilot's budget contains one more ingredient than `suggest_qty` (a different volatility window, an equity-based term, or a quantised regime scale). No tested variant (ATR 3–60 d, σ, Parkinson, |r|, forecast ci) fits more than 12 of the 31 non-strong orders. **Proposed implementation:** size autopilot orders with the §5.1/§5.3 formula (`按建議部位 %` is literally what the UI promises); accept that this under-sizes some low-cash adds relative to the lost engine.

### 5.4 Odd lots and minimums

Shares are plain integers (no 1 000-share lot constraint): 1-, 2-, 3-share orders occur whenever cash is tiny (`qty 1` at 4 860 with cash 18 671; `qty 1` at 112.65 with cash 680). Orders 62 (2308, cash 7 148, f model 0.156 → 0) and 98 (2454, cash 18 861, f model 0.157 → 0) were still filled with 1 share → `max(1, …)` when `cash ≥ price × 1.0005` (medium).

---

## 6. The two-arm shadow engine (`shadow.json`)

Semantics (high on fields, medium on mechanics): a frozen offline replay (`mode: "M3"`, `state_key` = hash of the frozen inputs, `chain_ok`/`freeze_ok` guards) that runs **two independent paper accounts of 1 000 000 each from `start_date 2026-08-07`**, arm **A** = `incumbent-v6` (the live genes) and arm **B** = `risk-exit-consensus` (a candidate genome), on end-of-day data: signals from the day's close, fills at the **next day's open** with ~10–12 bp slippage (`stats.slip_bp`; computed `price/open − 1` ≈ 10.1–12.7 bp on every fill, 40 bp for 2330 only because its bars were later dividend-adjusted). It writes `rows[]` (daily equity ledger, `ret_*_pct` vs the first row), `legs` (four pass/fail legs judged over the whole window at close-out: `operational prefix_breaks == 0`, `safety` max-drawdown, `return diff > 0`, `realization` slippage/reject vs `max(2×A, 5bp)`), `closeout {min_days 60, target_closed 10, hard_cap_days 120}` → `verdict` is sealed when `n_days ≥ 60` **and** B has ≥ 10 closed round trips, or at 120 days (`capped`). Sell `reason` strings: `停損`, `移動停利`, `訊號` (so the shadow does implement the signal exit), `ret` = fraction. Sizing differs from the live engine: B's fills are capped at **0.20 of remaining cash** (0.1995–0.2000 on the first four uncapped fills, 0.19–0.20 afterwards as floor effects grow) with a **1 000-share cap** (three 2882 fills of exactly 1000); A sits at 0.195–0.199 from 2026-08-31 and at 0.077–0.123 for its four August fills, i.e. `min(0.20, risk_frac_arm × m / vol)` with the same ATR-type scaling (A's August values are consistent with `caution_scale 0.5` being active for A). `holdings[]` (added in Oct) recompute `peak` as the highest **close** since entry (unlike the live engine), `stop_line = avg_entry × (1 − stop_pct_arm)`, `trail_line = peak × (1 − trail_pct_arm)`, `dist_*_pct = (last/line − 1) × 100`.

Genes (`genes[]`, fixed order; A = live v6 values; B unrounded floats):

| gene | A | B | meaning (inferred) |
|---|---|---|---|
| `w_ma_align` | 1.0 | 1.849 | weight of the `均線排列` signal in `tech_total` |
| `w_ma_cross` | 1.0 | 0.451 | weight of the MA-cross signal (never emitted in the snapshot, spec 04) |
| `w_rsi` | 1.0 | 0.784 | weight of `RSI` |
| `w_macd` | 1.0 | 1.252 | weight of `MACD` |
| `w_kd` | 0.5 | 0.244 | weight of `KD` |
| `w_bb` | 1.25 | 1.283 | weight of `布林通道` |
| `w_volume` | 1.5 | 1.453 | weight of `成交量` |
| `buy_th` | 3.0 | 3.0 | `BUY` threshold on `total` (also used by gate G4) |
| `strong_gap` | 2.0 | 2.0 | `STRONG_BUY` at `buy_th + strong_gap` (= `strong_th 5.0`); mirrored for `STRONG_SELL`; proposed also the swap gap |
| `sell_th` | −3.0 | −3.0 | `SELL` threshold |
| `stop_pct` | 0.08 | 0.0830 | stop-loss distance below the fee-inclusive average |
| `trail_pct` | 0.12 | 0.2061 | trailing-stop distance below `peak` |
| `risk_frac` | 0.005 | 0.0080 | sizing constant (`0.0075 = 1.5 × risk_frac` in §5.1) |
| `strong_mult` | 1.5 | 1.487 | budget multiplier for `強力買進` (before the cap) |
| `caution_scale` | 0.5 | 0.550 | budget multiplier under market caution (after the cap) |
| `persistence` | 2.0 | 2.0 | days the buy signal must persist (gate G4: today + previous close) |

Note the live `params_json` of v6–v9 keeps the technical weights under `weights{ma_align, ma_cross, rsi, macd, kd, bb, volume}` plus `buy_th/strong_th/sell_th/strong_sell_th`, `fund_cap 1.5`, `use_market`, `use_fundamentals`, `exit{stop_pct, trail_pct}`; `risk_frac/strong_mult/caution_scale/persistence` are not in `params_json` (they are `tuner SAFE_*` constants since v5: "安全參數自此移出調參搜索空間"). Arm A's `w_bb 1.25`/`w_rsi 1.0` are the v6 values, not the v9 ones (`bb 0.625, rsi 0.25`) — the shadow froze v6 as "incumbent".

---

## 7. Scan cadence and timing

| Item | Rule | Evidence | Confidence |
|---|---|---|---|
| Intraday loop | `scan_interval_min = 5`; the next scan is scheduled 5 min after the previous one **finishes** (not clock-aligned): `engine.next_scan = last_scan + 5 min` (both minute-truncated, `18:17:00 → 18:22:00`) | order seconds spread over the whole 5-min window (09:36:11, 09:41:12, 10:42:12, 11:18:41, 12:58:20, 13:29:04); 09:01:24 → 09:05:25 → 09:10:26 → 09:15:27 on 10-01 | medium |
| First scan of a trading day | at the 09:00 open: five days have orders at 09:00:21–09:00:55 (stops fire on the opening quote) | ids 20–23, 25–26, 103, 106 | high |
| Last intraday order | 13:29:04 (ten minutes before the 13:30 close) | id 101 | — |
| `收盤定盤掃描` | ≈13:33: `收盤定盤掃描完成:9 檔以收盤世界重新定價(其中 9 檔取得交易所定盤價);14:15 EOD 會再以完整日K做最終校正。` | 2026-08-14 13:33:13, 2026-10-30 13:33:06 | high |
| EOD | 14:15 on every calendar day incl. Saturdays: `EOD 完成:更新 9 檔資料,記錄 54 筆預測,兌現 54 筆。` (Saturday: `記錄 0 筆預測,兌現 6 筆`), then `行事曆同步:TWSE 除權息 3 筆`, the heartbeat `心跳已送(FAIL:AI 日報 19 天未產生)`, the AI daily report (`generated_at 14:16:54`), and `data.json`/`orders.json` bake (`generated_at 14:15:22`) | events 14:15:21–14:15:45 on 08-13/14/15, 10-29/30/31 | high |
| 晨會 (morning brief) | normally 08:30 (`2026-08-14T08:30:26`); 11:22 on 2026-10-30 (engine restarted late — `last_scan_kind 啟動` at 18:17 the same evening); message `晨會:夜盤 {±x}%、TSM {±x}%、費半 {±x}%;近 3 日事件 {n} 筆、宏觀新聞 {n} 則;無覆蓋` or `…;風險覆蓋 caution` | 3 events | high (template) |
| Tuner | Saturday 10:00 `開始調參:walk-forward champion/challenger…` → `調參採用新參數 v8:樣本外 reward_points 912.005 勝過現任 823.049(門檻 +2%,嘗試 59 組)` / `調參維持現任參數 v9:…未勝過現任…`; also auto-triggered at EOD by `偵測到預測品質下降(命中率 33%,MAE 惡化 155%),自動觸發調參` | 08-15, 10-30, 10-31 | high |
| Weekly review | Saturday 09:30 (`ai_report.weekly_review.generated_at 2026-08-01T09:30:20`) | | high |
| Shadow bake | after EOD on trading days only (`generated_at 14:50:28` Fri 10-30, `20:44:48` Fri 08-14); untouched on Saturday | | medium |
| `engine.last_scan_kind` | only `啟動` observed (the scan run when the engine process starts, 18:17 Fri / 20:50 Fri); proposed vocabulary `啟動`, `盤中`, `收盤定盤`, `EOD` | | low |
| Non-trading days | no orders; EOD still runs; `market.is_open false`, `label 收盤` | 10-31 (Sat) | high |

Scan timestamps that produced orders (all 36): 08-05 09:15:43 / 09:20:52 / 09:25:53; 08-06 09:00:50; 08-07 09:00:55; 08-10 09:01:04; 08-14 09:00:45; 09-21 09:02:26 / 09:05:29; 09-22 10:42:12 / 10:45:42 / 11:11:24 / 11:16:36; 09-23 09:02:05 / 11:18:41; 09-25 09:02:37; 09-29 09:31:51; 10-01 09:01:24 / 09:05:25 / 09:10:26 / 09:15:27; 10-07 09:02:20 / 09:05:51; 10-08 11:39:09; 10-12 09:30:52 / 09:36:11 / 09:41:12 / 10:01:27; 10-13 11:27:45 / 13:29:04; 10-14 11:46:55; 10-15 09:00:21 / 09:07:30 / 11:29:05; 10-20 09:00:43; 10-30 12:58:20.

---

## 8. Decision table (implementable)

Run once per scan after scores/quotes are refreshed; `orders_left = 3`.

| Step | Condition | Action | Confidence |
|---|---|---|---|
| 0 | `engine.kill` or `autopilot == false` | do nothing (still update `peak`, `stop_price`, `trail_price`, `verdict/reasons`) | high |
| 1 | for each held symbol: `peak = max(peak, price)`; `stop = round(avg×0.92, 2)`; `trail = round(peak×0.88, 2)` | | high |
| 2 | `price ≤ stop` and/or `price ≤ trail` | SELL all @ `round(price×0.9995, 2)`; fee/tax/pnl per §2.1; note per §2.3 (both → joined by `;`); `realized += pnl`; `orders_left −= 1` | high |
| 3 | held and `rec_code ∈ {SELL, STRONG_SELL}` | SELL all, note `訊號出場({rec_text},評分 {s})` (proposed) | medium (text unobserved) |
| 4 | market `halt` or quote stale (G1) | skip all buys | medium / low |
| 5 | candidate buys = symbols with `rec_code ∈ {BUY, STRONG_BUY}` and `prev_close_score ≥ buy_th` (else log `閘門攔截 {code} 買進:G4:{date} 收盤評分 {s:+.1f} 未達 buy_th {buy_th:+.1f},訊號未跨日持續`), processed in **descending `total` order** (tie → watchlist order); the queue drains over successive scans because of the 3-orders cap (10-01: 09:01 took 7.5/6.9/6.0, 09:05 took 5.5/4.8/4.3, 09:10 and 09:15 the two 3.9s) | | high |
| 6 | candidate is **not held**, and `min(score of held) ≤ score − 2.0` | SELL that holding (note `換股:讓位給 {code} {name}(評分差 {d:+.1f})`, event `自動換股:…`), then continue to 8 for the candidate | medium |
| 7 | candidate is held and (caution → log `閘門攔截 {code} 買進:G3:市場 caution(晨會覆蓋:隔夜情勢(caution)),禁加碼`; or already added today) | skip | high |
| 8 | sizing: `f = min(0.30, 0.0075 × (1.5 if STRONG_BUY) / atr14_pct)`; if caution `f ×= 0.5`; `qty = floor(f × cash / price)`; `qty = max(1, qty)` if `cash ≥ price×1.0005`; cap so that `(pos_value + qty×price) ≤ 0.40 × equity`; if `qty ≥ 1000` round down to 1000s (low) | BUY @ `round(price×1.0005, 2)`, fee per §2.1, note `訊號進場(…)` / `訊號加碼(…)`; update `avg` (fee-inclusive), `peak = max(peak, filled_price)`; `orders_left −= 1`; stop when `orders_left == 0` | high / medium (see §5.3) |
| 9 | bake: `positions[]`, `account` (§1), `orders.json` (last 50, newest first), broker events (§2.2) | | high |

---

## 9. Open questions (with proposed defaults)

1. **Autopilot order budget vs `suggest_qty`** (§5.3): 26/50 orders deviate from the ATR rule — 17 of them (14 `買進`, 3 `強力買進`) filled at the full 30 % cap, almost all in low-cash states, and four large-cash entries at `f ≈ 0.2245`. Proposed: use the `suggest_qty` formula (exactly what the UI advertises) and keep `0.30`/`1.5`/`0.5` as the only multipliers; revisit if replay equity drifts.
2. **Swap trigger** — gap threshold and whether it also requires cash starvation. Proposed: gap ≥ `strong_gap 2.0`, unconditional, one swap per scan, sell the lowest-scored holding.
3. **Signal-exit note** (`建議轉賣出`). Proposed: `訊號出場({rec_text},評分 {s:+.1f})`, triggered by `rec_code ∈ {SELL, STRONG_SELL}` on a held symbol.
4. **G1 freshness gate text and threshold.** Proposed: block when the quote is older than `scan_interval_min` or `quote_fresh == false`; message `閘門攔截 {code} 買進:G1:報價過期({age} 分)`.
5. **G3 regime gate beyond caution** (the review says it blocked 365 buys). Proposed: no buys at all when `market.score ≤ −1.0` or state `halt`; adds blocked and entries ×0.5 when `caution`; `caution` set by the 晨會 when overnight 夜盤/TSM/費半 are all negative (observed −1.4/−1.8/−1.4).
6. **Halt thresholds.** Observed `市場狀態:halt(大盤單日 -2.5%、5日 -3.6%)`. Proposed: `halt` when day ≤ −2.5 % or 5-day ≤ −3.5 %; cleared at the next EOD that does not meet it.
7. **1000-share rounding** (order 18 = 2000, shadow B = 1000 ×3). Proposed: `if qty ≥ 1000: qty -= qty % 1000`.
8. **Minimum one share** when the formula yields 0 but one share is affordable (orders 62, 98). Proposed: implement.
9. **`verdict`/`reasons[]` non-hold values.** Proposed: `verdict: "exit"`, `reasons: ["跌破停損價 226.17", "回落至移停價 216.48", "建議轉賣出"]` (viewer shows `該賣`).
10. **`last_scan_kind` vocabulary.** Proposed: `啟動` (process start), `盤中`, `收盤定盤`, `EOD`.
11. **Same-day re-entry after an exit.** Proposed: allowed (no cooldown) — nothing in the data forbids it, and E8 shows next-day re-entry.
12. **Peak initialisation on an add after the price fell below the old peak** — `peak = max(peak, filled_price)` is assumed; the alternative (reset to the add's fill) is contradicted by 2330 Oct (adds at 2491/2496 while `peak` stayed 2585) → keep max.
13. **Shadow sizing cap 0.20 and 1000-share cap** are specific to the shadow replay; the live engine uses 0.30. Proposed: keep the shadow module separate with its own constants.
