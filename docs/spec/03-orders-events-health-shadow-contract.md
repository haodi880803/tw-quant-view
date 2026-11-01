# 03 — `orders.json`, `events.json`, `model-health.json`, `shadow.json` contracts and the `simple.html` template

Status: reverse-engineered from the surviving viewer (`app.js` 2082 lines, `index.html`, `app.css`) and the two surviving baked snapshots of each file (git `8623d98` = bake of 2026-10-31T14:15:22+08:00, the working-tree files; git `2e74138` = bake of 2026-08-15T14:15:32+08:00, referred to below as "Oct" and "Aug"). Nothing here comes from engine source. Every rule that is not literally in `app.js` is marked **inferred** with its evidence and a confidence (high/medium/low). Unresolved points are collected in §7 with a proposed default.

All line numbers are `app.js` unless prefixed `index.html:`, `app.css:` or `simple.html:`. Companion document: `01-data-json-contract.md` (`data.json`; its §1 describes the viewer shim that is reused here).

---

## 0. Serialization conventions (all four JSON files)

Verified on all 8 snapshot files (`json.dumps(json.loads(raw), ensure_ascii=False) == raw` is `True` for every one):

| Aspect | Rule |
|---|---|
| Encoding | UTF-8, Chinese emitted raw (no `\uXXXX`; `grep -c '\\u'` = 0 in all files) |
| Layout | one single line, **no trailing newline**, Python `json.dumps(obj, ensure_ascii=False)` with default separators `", "` / `": "` |
| Key order | insertion order exactly as listed in the field tables below (identical in Aug and Oct) |
| Timestamps | ISO-8601, explicit Taipei offset, second precision, no microseconds: `2026-10-30T12:58:20+08:00`. The viewer never converts them: `events` shows `ts.slice(11,19)` (l.1803), orders/params show `fmtDateTime` = `iso.replace('T',' ').slice(0,16)` (l.135–138). So the string **must already be Taipei-local**. |
| Dates | `YYYY-MM-DD` (`model-health.series[].date`, every `shadow` date) |
| Booleans | JSON `true`/`false`, **except** `params_history[].adopted` which is the SQLite integer `0`/`1` (viewer uses `!!h.adopted`, l.1539) |
| Nulls | emitted as `null` where a column is not applicable (`orders[].pnl` on BUY, `shadow.trades[].qty/score/reason/ret`, `params_history[].*_metric` on a manual adoption, `shadow.verdict`) |
| Floats | money/ratios unrounded unless stated (e.g. `pnl: -3664.7299999999586`, `stats.a.slip_bp: 10.662654225091016`); fields that are rounded are noted per table |

### 0.1 Where each file is loaded (viewer shim, l.237–255; tab logic l.1914–1927; timers l.2046–2075)

| File | Dashboard path emulated | When fetched | Renderer | Empty/failure text |
|---|---|---|---|---|
| `orders.json` | `GET /api/orders?limit=50` (query ignored) | each click on the `訂單紀錄` tab (`index.html:140`), no timer | `loadOrders` l.1376–1401 | `尚無訂單` (also on fetch failure, since `orders` defaults to `[]`) |
| `events.json` | `GET /api/events?after_id=N&limit=100` | at boot (l.2050–2051) and every 300 000 ms (l.2054) — **regardless of the open tab** | `pollEvents` l.1784–1812 | initial `等待事件…` (`index.html:288`), removed on first append |
| `model-health.json` | `GET /api/model-health` | each click on `模型健康` (`index.html:141`), plus a reload every 10 s while the tab is open **if** the last load is > 300 000 ms old (l.2066–2068) | `loadHealth` l.1404–1414 → `renderHealth` l.1416–1453 | fetch failure → `#health-empty` = `無法載入模型健康資料`, charts hidden |
| `shadow.json` | `GET /api/shadow` | each click on `影子對照` (`index.html:142`), plus the same 300 000 ms refresh while open (l.2069–2074; the 20 s "computing" fast-poll is disabled in the viewer) | `loadShadow` l.1553–1565 → `renderShadow` l.1599–1781 | fetch failure → `#shadow-empty` = `無法載入影子對照資料`, content hidden |

Every fetch goes through `viewerFetchJson` (l.174–185): `file + '?t=' + Date.now()`, `cache:'no-store'`, never throws; a non-JSON body yields `data:null`.

### 0.2 Formatting helpers used by these tabs

| Helper | Lines | Rule |
|---|---|---|
| `fmtPrice(v)` | 84–90 | `—` if null/NaN; `\|v\| ≥ 1000` → `toLocaleString('en-US',{maximumFractionDigits:0})` (`2,370`); `≥ 100` → 1 dp (`245.6`); else 2 dp (`46.93`) |
| `fmtMoney(v)` | 92–95 | `—` if null; `Math.round(v).toLocaleString('en-US')` (`47,446`) |
| `fmtSignedMoney(v)` | 97–101 | rounded, thousands, `+`/`-` prefix, `0` unsigned |
| `fmtPct(v, d=2)` | 103–106 | `—` if null; `(v>0?'+':'') + v.toFixed(d) + '%'` — **input already in percent units** |
| `fmtRet(r, d=1)` | 108–111 | `fmtPct(r*100, d)` — **input is a fraction** |
| `fmtPp(v, d=2)` | 1567–1570 | `(v>0?'+':'') + v.toFixed(d) + 'pp'` |
| `fmtDateTime(iso)` | 135–138 | `—` if falsy; `String(iso).replace('T',' ').slice(0,16)` → `2026-10-30 12:58` |
| `clsOf(v)` | 82 | `up` (>0) / `down` (<0) / `flat` |
| `clsAB(v)` | 1572–1574 | `b-ahead` (>0) / `a-ahead` (<0) / `flat` — arm palette for B−A columns |
| `fmtGene(key,v)` | 1593–1597 | `—` if null; keys ending `_pct` or `risk_frac` → `(v*100).toFixed(2)+'%'`; integers → `String(v)`; else `v.toFixed(3)` |
| `escapeHtml` | 75–79 | applied to every string field before it reaches the DOM |

---

## 1. `orders.json`

### 1.1 Shape, window, ordering

```json
{"orders": [ {order}, {order}, ... ]}
```

| Rule | Evidence | Confidence |
|---|---|---|
| Top level is `{"orders": [...]}`; nothing else | both snapshots; viewer reads `r.data.orders` (l.1379) | — |
| Window = the **50 most recent orders** (`limit=50` in the emulated path, l.1377) | Oct has exactly 50 rows (ids 108…59); Aug has 10 rows (ids 26…17) = the whole ledger at the time | high |
| Ordering = **newest first**, by `id` descending; ids contiguous (an autoincrement row id) | Oct `ids == sorted(ids, reverse=True)` and contiguous 59..108; Aug 17..26 likewise | high |
| The viewer renders in array order (no sort) into `#orders-body` (`index.html:196`) | l.1384 | — |
| Rows are *orders*, one per fill; `created_at == filled_at` on every row | 60/60 | high |

### 1.2 Fields (key order as emitted)

Columns in `index.html:192–194`: `時間 | 代碼 / 名稱 | 方向 | 股數 | 成交價 | 手續費 | 稅 | 損益 | 狀態 | 模式`.

| Field | Type | Example | Rendering (l.1384–1399) | Missing/null |
|---|---|---|---|---|
| `id` | int | `108` | not rendered; defines ordering | required for ordering |
| `created_at` | iso string (Taipei) | `"2026-10-30T12:58:20+08:00"` | `<td class="num dim">` + `fmtDateTime` → `2026-10-30 12:58` | `—` |
| `symbol` | string | `"2317.TW"` | not rendered | tolerated |
| `code` | string | `"2317"` | `<b>2317</b>` | `''` |
| `name` | string | `"鴻海"` | `<span class="dim">鴻海</span>` | `''` |
| `side` | `"BUY"` \| `"SELL"` | `"BUY"` | `BUY` → `<span class="up">買</span>`; **anything else** → `<span class="down">賣</span>` (l.1385, 1389) | treated as SELL |
| `qty` | int (shares; odd lots allowed, min observed `1`) | `193` | `qty.toLocaleString('en-US')` → `1,571` | `—` |
| `price_hint` | float, 2 dp | `245.5` | not rendered | tolerated |
| `status` | enum, see §1.3 | `"FILLED"` | `ORDER_STATUS[status]` → `成交`, unknown value → the raw string escaped | `''` |
| `filled_price` | float, 2 dp | `245.62` | `fmtPrice` → `245.6` / `2,370` / `46.93` | `—` |
| `filled_at` | iso string | `"2026-10-30T12:58:20+08:00"` | not rendered | tolerated |
| `fee` | float, integer-valued NTD | `41.0` | `fmtMoney` → `41` | `—` |
| `tax` | float, integer-valued NTD; `0.0` on BUY | `0.0` | `fmtMoney` → `0` | `—` |
| `pnl` | `null` on BUY; float (unrounded) on SELL | `-3664.7299999999586` | `pnl != null ? fmtSignedMoney(pnl) : '—'`, class `clsOf(pnl \|\| 0)` → `-3,665` in green | `—` |
| `mode` | `"paper"` \| `"real"` | `"paper"` | `mode === 'real' ? '實盤' : '紙上'` (l.1396) | `紙上` |
| `source` | string | `"autopilot"` | `source === 'autopilot'` → appends `<span class="mini-chip warn" title="autopilot 依訊號自動下的單">自動</span>`; any other value → nothing (l.1397) | nothing |
| `note` | string | `"訊號進場(買進,評分 +3.0)"` | **not rendered by app.js** (kept for the ledger and for the `events` broker lines) | tolerated |

### 1.3 Enumerations

| Field | Observed values (Oct / Aug counts) | Full vocabulary the viewer knows | Chinese label |
|---|---|---|---|
| `side` | `BUY` 40 / 10, `SELL` 10 / 0 | `BUY`, `SELL` | `買` (class `up`), `賣` (class `down`) |
| `status` | `FILLED` 50 / 10 | `ORDER_STATUS` l.36–38: `FILLED`, `REJECTED`, `PENDING`, `CANCELLED` | `成交`, `拒絕`, `等待`, `取消` |
| `mode` | `paper` 50 / 10 | `paper`, `real` | `紙上`, `實盤` (also `mode-badge` `紙上交易`/`實盤` from `data.json.engine.mode`) |
| `source` | `autopilot` 50 / 10 | only `autopilot` is special-cased | chip `自動` |

### 1.4 Economics (all **inferred**; every formula checked against all 60 rows)

| Quantity | Formula | Evidence | Confidence |
|---|---|---|---|
| `filled_price` | `round(price_hint × (1 + 0.0005), 2)` for BUY; `round(price_hint × (1 − 0.0005), 2)` for SELL (5 bp deterministic slippage, matches `DEFAULT_FEES`/`estimate()` l.312–322 `slippage_bps: 5`) | 60/60 exact | high |
| `gross` | `qty × filled_price` | — | — |
| `fee` | `max(20, round(gross × 0.001425 × 0.6))` (broker rate 0.1425 % × 60 % discount, NT$20 minimum — the viewer's `DEFAULT_FEES` l.42) | 60/60 exact | high |
| `tax` | SELL: `round(gross × 0.003)`; BUY: `0` | 60/60 exact | high |
| cost basis | position average cost **includes buy fees**: `avg = (Σ qty×filled_price + Σ fee) / Σ qty` over the open lot, kept **unrounded** internally (`data.json.positions[].avg_price` is this value rounded to 2 dp; AI report shows `2308 … 17 … 1,928.96` = `(32731.29 + 61)/17`) | the 6 SELLs whose whole lot was bought inside the window (`71, 99, 103, 104, 105, 106`) reproduce `pnl` to the cent **only** with fee-inclusive, unrounded average; using the 2-dp average is off by up to 0.90 | high |
| `pnl` (SELL) | `qty × filled_price − fee − tax − qty × avg` (sell-side fee and tax deducted; buy fees already inside `avg`) | 6/6 exact (`-116.05`, `-2579.42`, `-437.40`, `-333.46`, `-8977.63`, `-2888.90`); the other 4 SELLs depend on pre-window lots and cannot be checked | high |
| rounding of `pnl` | **not rounded** (`-3664.7299999999586`) | all 10 SELLs | high |
| `qty` on exits | the **entire** position (`換股` sold all 1 571 shares of 0050 = the holding in the 10-12 AI report; stop/trail exits sell the full lot) | 10/10 | high |
| stop price in note | `round(avg × 0.92, 2)` (−8 %) | `1666.03 = 1810.90×0.92`, `4243.32 = 4612.30×0.92`, `47.76 = 51.9084×0.92` | high |
| trail price in note | `round(peak × 0.88, 2)` (−12 % from the position's peak) | `1834.80 = 2085×0.88`, `440.00 = 500×0.88`, `47.43 = 53.90×0.88`, `4725.60 = 5370×0.88` | high |

Timestamps: `created_at`/`filled_at` are the scan time at second precision; one scan can emit up to 3 orders sharing the same timestamp (Oct: 15 timestamps with 1 order, 7 with 2, 7 with 3 — consistent with the autopilot rule `每輪最多 3 筆` quoted at l.1937). Exits and the replacement buy of a `換股` share the same second (ids 107/108).

### 1.5 `note` templates (verbatim; `{s}` = signed score 1 dp, `{p}` = price 2 dp)

| Situation | Template | Count Oct / Aug | Example |
|---|---|---|---|
| BUY, opening a new position | `訊號進場({rec_text},評分 {s})` | 8 / 6 | `訊號進場(買進,評分 +3.0)` |
| BUY, adding to an existing position | `訊號加碼({rec_text},評分 {s})` | 32 / 4 | `訊號加碼(強力買進,評分 +5.1)` |
| SELL, stop-loss | `觸發停損:現價跌破進場價 -8%({stop_price})` | 3 / 0 | `觸發停損:現價跌破進場價 -8%(1666.03)` |
| SELL, trailing stop | `觸發移動停利:從高點 {peak} 回落 -12%({trail_price})` | 3 / 0 | `觸發移動停利:從高點 2085.00 回落 -12%(1834.80)` |
| SELL, both triggered | the two above joined with `;` | 1 / 0 | `觸發停損:現價跌破進場價 -8%(47.76);觸發移動停利:從高點 53.90 回落 -12%(47.43)` |
| SELL, rotation into a better-scored symbol | `換股:讓位給 {code} {name}(評分差 {s})` | 3 / 0 | `換股:讓位給 2317 鴻海(評分差 +5.0)` |

`{rec_text}` is one of `買進` / `強力買進` (only BUY-side recommendations open or add). `評分差` = new symbol's score − sold symbol's score (`+3.0 − (−2.0) = +5.0`, matching event `自動換股:賣出 0050 元大台灣50(評分 -2.0)讓位給 2317 鴻海(評分 +3.0)`). The `-8%` / `-12%` literals are the active `exit.stop_pct` / `exit.trail_pct` (see §3.5); peak/stop/trail prices are printed with 2 dp (`53.90`, `2085.00`).

### 1.6 Cross-file links

* Every fill also produces a `broker` INFO event at the same second (§2.4): `紙上買單成交:2317 鴻海 193 股 @ 245.62,手續費 41 元,總支出 47,446 元。` where `總支出 = round(gross + fee)`; `紙上賣單成交:0050 元大台灣50 1571 股 @ 105.15,手續費 141 元,證交稅 496 元,已實現損益 -3,665 元。` where `已實現損益 = round(pnl)` with thousands separators and sign.
* `data.json.account.realized_pnl` is the running Σ `pnl`; `positions[].avg_price` is the fee-inclusive average above.

---

## 2. `events.json` (`運作日誌` tab)

### 2.1 Shape, window, `last_id`

```json
{"events": [ {event}, ... ], "last_id": 6762}
```

| Rule | Evidence | Confidence |
|---|---|---|
| `events` = the **100 most recent** rows, **ascending** by `id` (oldest first) | Oct ids 6663…6762 ascending, contiguous; Aug 995…1094 likewise; `ts` ascending in both | high |
| `last_id` = `max(id)` = the id of the last element | both snapshots | high |
| `id` is a global autoincrement that **never resets** (6 762 events by 2026-10-31; 1 094 by 2026-08-15 ≈ 74/day) | ids are contiguous across days and across the engine's own restarts (`啟動` scans at 18:17 and 23:46 appear inside the window) | high |
| The window closes at the end of EOD: the last event (`6762`, `14:15:22`) is the AI-daily-report failure logged in the same second as `data.json.generated_at` (`14:15:22`); Aug identical (`1094` at `14:15:32` = `generated_at`) | both snapshots | high |

### 2.2 How the viewer consumes it (l.240–255, l.1784–1812)

1. `S.lastEventId` starts at `0`; each poll requests `after_id=S.lastEventId`. The shim filters `events.filter(e => (e.id||0) > after)` and returns `{events, last_id: file.last_id ?? after}`.
2. `S.lastEventId = r.data.last_id` (falls back to the last event's `id` only when `last_id` is null).
3. Only rows with `id > lastEventId` are appended, so the 5-minute re-fetch never duplicates. **Consequence for the rebuild:** ids must be strictly increasing across bakes; if a rebuild restarted numbering below the previous `last_id`, open viewers would show nothing new until a page reload. Persist the counter (SQLite autoincrement or a committed state file).
4. The feed keeps at most **400** rows (oldest removed), auto-scrolls when the user is within 60 px of the bottom.
5. Each row renders as `<div class="ev-row ev-{LEVEL}"><span class="ev-ts">{ts[11:19]}</span> <span class="ev-src">[{source}]</span> {message}</div>` (all three escaped). CSS `app.css:472–477`: `.ev-INFO` normal text, `.ev-WARN` amber, `.ev-ERROR` red bold.

### 2.3 Fields

| Field | Type | Example | Rendering | Missing/null |
|---|---|---|---|---|
| `id` | int | `6663` | dedup key (`e.id \|\| 0`) | treated as 0 → always re-appended — **required** |
| `ts` | iso string (Taipei) | `"2026-10-28T14:15:31+08:00"` | `String(ts).slice(11,19)` → `14:15:31` (no tz conversion) | `''` |
| `level` | `"INFO"` \| `"WARN"` \| `"ERROR"` | `"WARN"` | upper-cased; anything not in `['INFO','WARN','ERROR']` → class `ev-INFO` | `INFO` |
| `source` | string, see §2.4 | `"engine"` | `[engine]` | `[]` |
| `message` | string, single line (no newlines observed in 200 rows; `.ev-row` is `white-space: pre-wrap` so newlines would render) | see §2.4 | escaped text | `''` |

Observed counts: level `WARN` 59 / 79, `INFO` 41 / 21 (Oct / Aug); `ERROR` never observed. Sources Oct: `engine` 44, `news` 33, `ai` 15, `heartbeat` 3, `broker` 2, `tuner` 2, `data` 1; Aug: `news` 39, `ai` 30, `engine` 26, `broker` 2, `tuner` 2, `data` 1 (`heartbeat` did not exist yet — added with `engine.health`, see 01 §4.2).

### 2.4 Message templates (verbatim, grouped by `source`; `{…}` are placeholders)

**`engine` INFO**

| Template | Example |
|---|---|
| recommendation change, logged at each scan: `{code} {name}:{old}→{new}` where old/new ∈ `觀望`/`買進`/`強力買進`/`賣出`/`強力賣出` | `2317 鴻海:觀望→強力買進` |
| news tilt: `{code} {name} 消息面偏空 {score}({n} 則)` (`score` signed 1 dp; a bullish variant presumably `消息面偏多`, unobserved) | `2330 台積電 消息面偏空 -1.2(8 則)` |
| pre-market briefing: `晨會:夜盤 {pct}、TSM {pct}、費半 {pct};近 {n} 日事件 {k} 筆、宏觀新聞 {m} 則;{無覆蓋\|風險覆蓋 caution}` (`夜盤 無資料` when the night session is missing) | `晨會:夜盤 -1.4%、TSM -1.8%、費半 -1.4%;近 3 日事件 1 筆、宏觀新聞 15 則;風險覆蓋 caution` |
| gate block (market override): `閘門攔截 {code} 買進:G3:市場 caution(晨會覆蓋:隔夜情勢(caution)),禁加碼` | as shown |
| gate block (persistence, Aug): `閘門攔截 {code} 買進:G4:{date} 收盤評分 {s} 未達 buy_th {th},訊號未跨日持續` | `閘門攔截 6789 買進:G4:2026-08-13 收盤評分 -0.6 未達 buy_th +3.0,訊號未跨日持續` |
| rotation: `自動換股:賣出 {code} {name}(評分 {s})讓位給 {code} {name}(評分 {s})` | `自動換股:賣出 0050 元大台灣50(評分 -2.0)讓位給 2317 鴻海(評分 +3.0)` |
| closing-fix scan (13:33): `收盤定盤掃描完成:{n} 檔以收盤世界重新定價(其中 {k} 檔取得交易所定盤價);14:15 EOD 會再以完整日K做最終校正。` | as shown with 9/9 |
| market gate: `市場狀態:halt(大盤單日 {pct}、5日 {pct})` | `市場狀態:halt(大盤單日 -2.5%、5日 -3.6%)` |
| EOD: `EOD 完成:更新 {n} 檔資料,記錄 {p} 筆預測,兌現 {r} 筆。` (`p` = 54 = 9 symbols × 3 horizons × 2 models on a trading day; `0` on Saturday) | `EOD 完成:更新 9 檔資料,記錄 54 筆預測,兌現 54 筆。` |
| calendar sync: `行事曆同步:TWSE 除權息 {n} 筆` | `行事曆同步:TWSE 除權息 3 筆` |
| tuner start: `開始調參:walk-forward champion/challenger…` | as shown |

**`engine` WARN**

| Template | Example |
|---|---|
| `{code} 未來 30 天無任何行事曆事件記錄——法說會/除權息可能未收錄` (one per symbol after each calendar sync) | `0050 未來 30 天無任何行事曆事件記錄——法說會/除權息可能未收錄` |
| `偵測到預測品質下降(命中率 {pct}%,MAE 惡化 {pct}%),自動觸發調參` | `偵測到預測品質下降(命中率 33%,MAE 惡化 155%),自動觸發調參` |

**`broker` INFO** (one per fill, same second as the order)

| Template |
|---|
| `紙上買單成交:{code} {name} {qty} 股 @ {price:.2f},手續費 {fee} 元,總支出 {gross+fee:,} 元。` |
| `紙上賣單成交:{code} {name} {qty} 股 @ {price:.2f},手續費 {fee} 元,證交稅 {tax} 元,已實現損益 {pnl:+,} 元。` |

`qty` has no thousands separator (`1571 股`); money totals do (`47,446`, `-3,665`); fee/tax are plain integers.

**`tuner`** — `INFO`: `調參採用新參數 v{n}:{reason}` or `調參維持現任參數 v{n}:{reason}` where `{reason}` is the `params_history[].reason` string (§3.5). `WARN`: AI failure lines (below).

**`heartbeat` INFO** — `心跳已送(FAIL:{red joined})` e.g. `心跳已送(FAIL:AI 日報 19 天未產生)`; presumably `心跳已送(OK)` when `engine.health.red` is empty (unobserved).

**`data` WARN** — `{symbol} 本次最新日期 {date} 落後快取 {date}(疑似劣化回應),保留舊快取` e.g. `0050.TW 本次最新日期 2026-10-29 落後快取 2026-10-30(疑似劣化回應),保留舊快取`.

**`news` / `ai` / `tuner` WARN (AI CLI failures)**

| Template | Notes |
|---|---|
| `AI 呼叫失敗({model},rc={rc}):{stderr tail}` | `model` ∈ `sonnet` (source `news`) / `opus` (sources `ai`, `tuner`); Aug rows end with an empty tail (`AI 呼叫失敗(sonnet,rc=1):`) |
| `AI 連續失敗 {n} 次,暫停 AI 呼叫 {m} 分鐘(期間自動改用非 AI 路徑)` | always `3` / `15` observed; the cool-down pattern is 2 failures 1–2 s apart, then this line, then a retry ≈15 min later |

**Observed EOD sequence** (10-30, all `engine` unless noted): `市場狀態:halt(…)` 14:15:25 → `[heartbeat] 心跳已送(…)` 14:15:26 → `EOD 完成:…` 14:15:26 → `行事曆同步:…` 14:15:45 → per-symbol calendar WARNs → `偵測到預測品質下降…` → `開始調參:…` → (AI daily-report attempt → `[ai] AI 呼叫失敗…`) → bake. Recommendation-change lines are emitted by every scan, including the `啟動` scans at 18:17 and 23:46.

---

## 3. `model-health.json` (`模型健康` tab)

### 3.1 Shape

```json
{"metrics": {"by_model_horizon": [...], "champion": {...}, "series": [...]},
 "params_history": [...],
 "active_version": 9}
```

Viewer: `renderHealth` (l.1416–1453) reads `data.metrics || {}`, `metrics.series || []`, `metrics.champion || {}`, `data.active_version`, `data.params_history || []`. The brief line (`#health-brief`) does **not** come from this file but from `data.json.overview.model_health_brief` (l.1419–1425): `5日 MAE +4.4% ・ 命中率 54% ・ 已兌現 3408 筆`. **Inferred** link (high): `model_health_brief.n_resolved` = Σ `by_model_horizon[].n` (3408 = 639+639+603+603+462+462), `mae_5d`/`hit_rate_5d` = the champion's 5-day row (`0.044109`, `0.5439`), `champion` = `champion["5"]`.

### 3.2 `metrics.by_model_horizon[]` — not rendered by app.js

One row per (model, horizon); order `(horizon asc, model asc)`: baseline/1, ridge/1, baseline/5, ridge/5, baseline/20, ridge/20.

| Field | Type | Example | Notes |
|---|---|---|---|
| `model` | string | `"baseline"` / `"ridge"` | only these two models exist |
| `horizon` | int (trading days) | `1`, `5`, `20` | |
| `n` | int | `639` | resolved forecasts to date; the same `n` for both models at a horizon |
| `mae` | float, 6 dp, **fraction** | `0.020186` | mean absolute error of predicted vs realized return (2.02 %) |
| `hit_rate` | float, 4 dp, fraction | `0.4945` | direction hit rate |

### 3.3 `metrics.champion`

Object keyed by **string** horizon → model name: `{"1": "baseline", "5": "baseline", "20": "baseline"}` (Aug: `"5": "ridge"`). Rendered (l.1428–1431) as chips sorted numerically: `<span class="champ-chip" title="樣本數足夠時取 MAE 較低者">1日冠軍:baseline</span>`. **Inferred** rule (high, from the tooltip and both snapshots): champion = the model with the lower `mae` in `by_model_horizon` for that horizon, once `n` is "sufficient" (Aug 5-day: ridge 0.055381 < baseline 0.056801 → ridge; every Oct horizon → baseline). The sufficiency threshold is unobserved (§7). The chart drawer dashes the `baseline` line and draws any other model solid (l.1479), so keep the name `baseline` for the naive model.

### 3.4 `metrics.series[]` — the two weekly charts

| Field | Type | Example | Rendering (l.1455–1521) |
|---|---|---|---|
| `date` | `YYYY-MM-DD`, always a **Monday** | `"2026-07-06"` | x-axis category (union of dates, sorted) |
| `model` | string | `"baseline"` | series key `model + '\|' + horizon`; legend name `baseline 1日` |
| `horizon` | int | `1` | colour `HZ_COLOR` 1→`#3987e5`, 5→`#c98500`, 20→`#9085e9`, other→`#199e70` |
| `mae` | float 6 dp, fraction | `0.022037` | MAE chart: `+(mae*100).toFixed(3)`; y-axis `v + '%'` |
| `hit_rate` | float 4 dp, fraction | `0.5` | hit chart: `+(hit_rate*100).toFixed(1)`, y 0–100, dashed `50%` mark-line |
| `n` | int | `30` | not rendered |

Row order: sorted by `(date, model, horizon)` ascending (verified both snapshots). Missing `(model,horizon,date)` combinations simply do not exist as rows (the chart `connectNulls`).

**Inferred** semantics (medium-high): one row = all forecasts for `(model, horizon)` **created during the ISO week starting on `date`** that have since resolved; `n` = their count, `mae`/`hit_rate` = their averages. Evidence: (a) week `2026-07-06` has a 20-day row with `n=6` already in the Aug 15 bake — a 20-day forecast cannot *resolve* within the week it was issued, so `date` is the creation week; (b) `n` is 45 = 9 symbols × 5 trading days on full weeks, 30 = 6 symbols × 5 in week 07-13 (watchlist grew from 6 to 9 the following week), 17/19/9 on the holiday-shortened week 08-24; (c) the latest week in a bake is partial and grows between bakes (week 08-10 had `n=44` for 1-day on Aug 15). Each horizon's last row therefore lags by about `horizon` trading days. The engine must recompute the whole series from the forecast ledger at every bake (rows change retroactively as forecasts resolve). Rounding: `mae` 6 dp, `hit_rate` 4 dp (`0.5`, `1.0`, `0.0` print short).

Empty state: when `series` is empty the charts hide and `#health-empty` shows `資料累積中 — 預測需等到期兌現後才有誤差統計,第一天沒有資料是正常狀態。` (`index.html:208`); if ECharts is missing: `圖表引擎未載入`.

### 3.5 `params_history[]` — `調參歷史` table

Table caption `調參歷史(僅樣本外驗證更好才採用;高亮列 = 已採用)`; columns `時間 | 版本 | 採用 | 訓練指標 | 驗證指標 | 冠軍指標 | 原因 / 參數摘要` (`index.html:219–227`); empty state `尚無調參紀錄`. Rendered in **array order** = newest first (`id` descending, 25 rows Oct / 11 Aug — the whole history, no window observed).

| Field | Type | Example | Rendering (l.1523–1550) |
|---|---|---|---|
| `id` | int | `25` | not rendered; ordering key |
| `adopted_at` | iso string | `"2026-10-31T10:00:31+08:00"` | `fmtDateTime` → `2026-10-31 10:00` (it is the *evaluation* time even when not adopted) |
| `version` | int | `9` | `v9`, plus ` ●` when `version === active_version && adopted` |
| `params_json` | **string** containing JSON | see below | row `title` tooltip = raw string; summary `buy_th={buy_th} 停損{round(stop_pct*100)}% 移停{round(trail_pct*100)}%` appended as `<span class="dim">` after `reason` (e.g. `buy_th=3 停損8% 移停12%`; JS prints `3.0` as `3`) |
| `train_metric` | float or `null` | `322.613620264262` | `Number(v).toFixed(3)` / `—` |
| `valid_metric` | float or `null` | `852.5712743925799` | same |
| `champion_metric` | float or `null` | `852.5712743925799` | same |
| `adopted` | int `0`/`1` | `0` | `1` → `<span class="up">是</span>` and row class `adopted-row` (`app.css:400`, blue highlight); `0` → `<span class="dim">否</span>` |
| `reason` | string | see templates | escaped text |

`params_json` format: `json.dumps(params)` with **default** separators and default `ensure_ascii=True` (no non-ASCII inside, so byte-identical either way), key order fixed:

```
{"buy_th": 3.0, "strong_th": 5.0, "sell_th": -3.0, "strong_sell_th": -5.0, "weights": {"ma_align": 1.5, "ma_cross": 1.0, "rsi": 0.25, "macd": 1.0, "kd": 0.5, "bb": 0.625, "volume": 1.5}, "fund_cap": 1.5, "use_market": true, "use_fundamentals": true, "exit": {"stop_pct": 0.08, "trail_pct": 0.12}}
```

Verified: `json.dumps(json.loads(s)) == s` for all 25 strings. Keys always present: `buy_th, strong_th, sell_th, strong_sell_th, weights{ma_align, ma_cross, rsi, macd, kd, bb, volume}, fund_cap, use_market, use_fundamentals, exit{stop_pct, trail_pct}`. The active v9 params are:

`{"buy_th": 3.0, "strong_th": 5.0, "sell_th": -3.0, "strong_sell_th": -5.0, "weights": {"ma_align": 1.5, "ma_cross": 1.0, "rsi": 0.5, "macd": 1.0, "kd": 0.5, "bb": 0.625, "volume": 1.5}, "fund_cap": 1.5, "use_market": true, "use_fundamentals": true, "exit": {"stop_pct": 0.08, "trail_pct": 0.12}}`

**Inferred** version semantics (high, 25/25 rows): an adopted row carries the **new** version number (v2…v9 adopted at ids 1,2,4,5,6,10,11,12); a rejected row carries the **currently active** version (ids 3 → v3, 7–9 → v6, 13–25 → v9). `active_version` = version of the newest adopted row = `data.json.engine.params_version`. Metric meaning changed on 2026-07-25: `calmar` (ids 1–6) → `reward_points` (ids 7+); `train_metric` is in-sample, `valid_metric` the challenger's out-of-sample score, `champion_metric` the incumbent's out-of-sample score. A manual adoption (id 5) has all three metrics `null`.

`reason` templates (verbatim):

| Template | Count | Example |
|---|---|---|
| `樣本外 reward_points {valid:.3f} 未勝過現任 {champ:.3f}(門檻 +2%,嘗試 {k} 組)` | 16 | `樣本外 reward_points 852.571 未勝過現任 852.571(門檻 +2%,嘗試 59 組)` |
| `樣本外 reward_points {valid:.3f} 勝過現任 {champ:.3f}(門檻 +2%,嘗試 {k} 組)` | 3 | `樣本外 reward_points 912.005 勝過現任 823.049(門檻 +2%,嘗試 59 組)` |
| `樣本外 calmar {valid:.3f} 勝過現任 {champ:.3f}(門檻 +2%,嘗試 {k} 組)` / `…未勝過…` | 4 / 1 | `樣本外 calmar 5.419 勝過現任 4.555(門檻 +2%,嘗試 63 組)` |
| manual | 1 | `手動採用:恢復六月回測驗證的出場保護(停損 8%/移動停利 12%)。安全參數自此移出調參搜索空間(tuner SAFE_*),不再由任何回測決定——v4 於 7/17 崩盤日無停損的教訓。` |

Adoption rule implied by the text (high): adopt iff `valid_metric > champion_metric × 1.02`; `k` ≈ 59–64 candidate sets per run. Cadence (**inferred**, medium): a scheduled weekly run on Saturday ~10:00 (ids 9–11, 14, 15, 17, 19, 21, 22, 24, 25) plus extra runs at other times (07-29 14:18, 08-19 14:16, 08-22 14:15, 09-11 16:06, 09-14 17:56, 09-26 14:12, 10-17 15:30), consistent with the `偵測到預測品質下降(…),自動觸發調參` event; every run logs the matching `tuner` event (§2.4).

### 3.6 `active_version`

int; rendered as `目前參數 v9` in `#active-version` (l.1432; empty string when null) and used for the ` ●` marker.

---

## 4. `shadow.json` (`影子對照` tab)

### 4.1 Top-level fields (key order as emitted; `holdings` was added between Aug and Oct)

| Field | Type | Example | Viewer use (l.1599–1781) |
|---|---|---|---|
| `schema` | int | `1` | not read |
| `active` | bool | `true` | `false` → everything hidden, `#shadow-empty` = `reason \|\| 'shadow 尚未起錶'` (l.1613–1618) |
| `reason` | string (only read when `active` is false; absent in both snapshots) | — | the inactive message |
| `generated_at` | iso string | `"2026-10-30T14:50:28+08:00"` | not read. Bakes happen on trading days after EOD (~14:50; Aug `20:44:48`), **not** on the Saturday EOD — the Oct file is a day older than `data.json` |
| `state_key` | 64-hex sha256 | `"63f4…71c5"` | not read; identifies the frozen ledger state the panel was computed from |
| `start_date` | date | `"2026-08-07"` | `起始日 2026-08-07` only in the "no rows yet" state (l.1653) |
| `mode` | string | `"M3"` | not read (friction model; footer text `worldsim 紙上模擬(M3 摩擦)`) |
| `initial_cash` | float | `1000000.0` | not read |
| `arms` | `{a: string, b: string}` | `{"a": "incumbent-v6", "b": "risk-exit-consensus"}` | brief line `A 現任(incumbent-v6)…`; defaults `A`/`B` |
| `closeout` | `{min_days, target_closed, hard_cap_days}` | `{60, 10, 120}` | progress chip denominators (defaults 60/10) |
| `progress` | `{n_days, closed_b, ready, capped}` | `{55, 2, false, false}` | `第 55/60 交易日 ・ B 平倉 2/10` (l.1645–1647); `ready`/`capped` not read |
| `chain_ok` | bool | `true` | `=== false` → warning `帳本雜湊鏈驗證失敗` |
| `freeze_ok` | bool | `true` | `=== false` → warning `凍結封條驗證失敗` |
| `warnings` | string[] | `[]` | appended to the warning line; line = `⚠ ` + all joined by `；`, hidden when none |
| `rows` | array (§4.2) | 55 rows | ledger table, chart, brief |
| `legs` | object (§4.3) | | four leg chips |
| `stats` | `{a:{…}, b:{…}}` (§4.3) | | not read |
| `turnover` | `{a: float, b: float}` | `{1591820.0, 999284.0}` | not read |
| `trades` | `{a: [...], b: [...]}` (§4.4) | | window trades table |
| `holdings` | `{a: [...], b: [...]}` (§4.4) | | open-positions table (tolerates absence) |
| `genes` | array (§4.4) | 16 rows | genome table |
| `verdict` | `null` or object (§4.5) | `null` | banner `#shadow-verdict` |
| `verdict_sealed` | bool | `false` | not read |
| `computing` | bool | `false` | `true` → shows chip `#shadow-stale` `更新中…` (title `面板資料與影子帳最新狀態不一致,背景重烤中`) |
| `refresh_failed` | bool | `false` | with `computing:true` → chip text `更新失敗`, title `面板重烤失敗,已寫入運作日誌;每 10 分鐘自動重試` |

### 4.2 `rows[]` — daily ledger (`每日帳`)

Columns `日期 | A 權益 | B 權益 | A 累計% | B 累計% | 差距 B−A(pp) | 當日變化(pp) | B 平倉數` (`index.html:250–252`); the table is rendered **newest first** (`rows.slice().reverse()`, l.1708) while the chart (`A(現任)vs B(候選)權益曲線`, l.1671–1705, y-axis `(v/10000).toFixed(1)+'萬'`) uses array order. File order is ascending by date, unique dates, one row per trading day.

| Field | Type | Example | Rendering |
|---|---|---|---|
| `date` | date | `"2026-10-29"` | `num dim` |
| `eq_a`, `eq_b` | float 2 dp | `1032851.39`, `1132100.3` | `fmtMoney` |
| `ret_a_pct`, `ret_b_pct` | float 4 dp, percent | `3.2851`, `13.2083` | `fmtPct` with `clsOf` (red/green) |
| `diff_pp` | float 4 dp | `9.9232` | `fmtPp` with `clsAB` (`b-ahead` amber / `a-ahead` blue, `app.css:418–419`) |
| `day_pp` | float 4 dp | `-0.4529` | same |
| `closed_a`, `closed_b` | int (cumulative) | `7`, `2` | only `closed_b` shown (`—` if null) |

**Inferred** formulas (high; 0 mismatches over 60 rows): `ret_x_pct = round((eq_x / eq_x[first row] − 1) × 100, 4)` — base is the **first row** (`基準=首行帳`; note `eq_b[0] = 1000015.36 ≠ initial_cash`), `diff_pp = round(ret_b_pct − ret_a_pct, 4)`, `day_pp = round(diff_pp − diff_pp[prev], 4)` (0 on the first row), `closed_x` = cumulative count of SELL trades of arm x up to and including `date` (matches `trades[].type=='SELL'` dates exactly). `progress.n_days = len(rows)`; `progress.closed_b = rows[-1].closed_b`. The last row is **T−1** relative to the bake (bake 10-30 14:50 → last row 10-29; Aug bake 08-14 → last row 08-13; the day-i decision / i+1 fill rule quoted at l.1651), while `holdings[].last_date` is T (10-30).

Empty `rows` with `active:true` → `#shadow-empty` = `影子帳等待首行(day i 決策、i+1 成交;窗內需 ≥2 交易日)`, brief = `起始日 {start_date}`, content hidden (l.1649–1655).

Brief line (l.1662–1665): `A 現任(incumbent-v6)1,032,851(+3.29%) ・ B 候選(risk-exit-consensus)1,132,100(+13.21%) ・ 差 +9.92pp` from the last row.

### 4.3 `legs`, `stats`, `turnover`

`legs` chips (l.1576–1591), each `<span class="leg-chip ok|pending" title="四腿於結案時整窗判定;觀察期未過屬預期">{label} ✓|✗ <span class="dim">{detail}</span></span>`; a missing leg renders `{label}:—(等待資料)`:

| Key | Fields (type) | Chip label | Detail text | Example |
|---|---|---|---|---|
| `operational` | `prefix_breaks` int, `pass` bool | `操作腿` | `prefix_breaks={n}` | `操作腿 ✓ prefix_breaks=0` |
| `safety` | `doom` bool, `mdd_b`, `mdd_a` float 4 dp fraction, `pass` | `安全腿` | `MDD B {mdd_b*100:.1f}% / A {mdd_a*100:.1f}%` | `安全腿 ✓ MDD B 4.0% / A 5.9%` |
| `return` | `ret_b`, `ret_a`, `diff` float 6 dp fraction, `pass` | `報酬腿` | `B−A {fmtPp(diff*100)}` | `報酬腿 ✓ B−A +9.92pp` |
| `realization` | `slip_bp_b`, `slip_bp_a` float 2 dp, `reject_b`, `reject_a` float, `pass` | `實現腿` | `B 滑價 {slip_bp_b}bp(門檻 max(2×A, 5bp))` | `實現腿 ✓ B 滑價 11.65bp(門檻 max(2×A, 5bp))` |

**Inferred** (high, verified): `mdd_x` = max peak-to-trough drawdown of `rows[].eq_x` (0.0588 / 0.0399 exact); `ret_x = rows[-1].ret_x_pct / 100` (6 dp); `diff = ret_b − ret_a`; `slip_bp_x = round(stats.x.slip_bp, 2)`; `reject_x = stats.x.reject_rate`. Pass criteria are only partly visible (§7): realization passes when `slip_bp_b ≤ max(2 × slip_bp_a, 5)`; operational when `prefix_breaks == 0` (medium); safety/return thresholds unobserved (`pass` is `true` in both snapshots even at `n_days = 5`).

`stats.{a,b}`: `slip_bp` (float, unrounded mean fill slippage in bp vs. reference close — ≈10.7–12 bp under M3), `reject_rate` (float), `turnover_notional` (float, = `turnover.{a,b}`; **larger** than Σ BUY `qty×price`, so it counts buys and sells), `n_fills` (int = `len(trades.x)`), `n_starved` (int). None are rendered.

### 4.4 `trades`, `holdings`, `genes`

`trades.{a,b}[]` (ascending by date in the file; viewer merges both arms and sorts **newest first**, tie → arm `A` before `B`, l.1748–1772; columns `帳 | 日期 | 代碼 | 方向 | 價格 | 股數 | 備註`, empty `窗內尚無交易`):

| Field | Type | BUY row | SELL row | Rendering |
|---|---|---|---|---|
| `type` | `"BUY"` \| `"SELL"` | | | `type.toUpperCase().startsWith('BUY')` → `買` (up) else `賣` (down) |
| `symbol` | string | `"2882.TW"` | | suffix `.TW`/`.TWO` stripped → `2882` |
| `date` | date | `"2026-08-12"` | | |
| `price` | float **unrounded** | `100.12168886395538` | `4480.257197598188` | `fmtPrice` |
| `qty` | int | `772` | **`null`** | `toLocaleString` / `—` |
| `score` | float 2 dp | `3.0`, `3.83` | `null` | BUY note `評分 3.0` (`toFixed(1)`) |
| `reason` | string | `null` | `移動停利` / `停損` / `訊號` | SELL note = `reason` |
| `ret` | float fraction | `null` | `-0.01008787081497342` | SELL note += ` ・ 報酬 -1.0%` (`fmtRet`) |

`holdings.{a,b}[]` (columns `帳 | 代碼 | 股數 | 均價 | 現價 | 持倉齡(日) | 報酬% | 距停損% | 距移停%`, caption `未平倉部位與出場線距離(唯讀重算;距停損/距移停=現價高於該出場線的百分比,越小越接近出場)`, empty `兩臂目前無未平倉部位`; a distance `< 3` gets class `near-exit` (amber bold, `app.css:103`)):

| Field | Type | Example (A 2882) | Formula (**inferred**, 7/7 holdings exact to 2 dp except one 0.01 rounding) |
|---|---|---|---|
| `symbol` | string | `"2882.TW"` | suffix stripped on render |
| `qty` | int | `3413` | |
| `avg_entry` | float 2 dp | `102.2` | arm's average entry price |
| `first_buy` | date | `"2026-08-12"` | |
| `age_days` | int | `53` | number of **trading days** from `first_buy` to the bake date inclusive (= rows with `date ≥ first_buy` + the current day T) |
| `last` | float | `116.0` | close on `last_date` |
| `last_date` | date | `"2026-10-30"` | T (one day after `rows[-1].date`) |
| `peak` | float | `116.5` | highest close since entry |
| `ret_pct` | float 2 dp | `13.5` | `(last/avg_entry − 1)×100` |
| `stop_line` | float 2 dp | `94.02` | `avg_entry × (1 − stop_pct_of_arm)` (A 0.08; B `genes.stop_pct.b` 0.0830…) |
| `dist_stop_pct` | float 2 dp | `23.37` | `(last/stop_line − 1)×100` (unrounded line) |
| `trail_line` | float 2 dp | `102.52` | `peak × (1 − trail_pct_of_arm)` (A 0.12; B 0.2061…) |
| `dist_trail_pct` | float 2 dp | `13.15` | `(last/trail_line − 1)×100` |

`genes[]` (table `基因組對照(高亮列=兩臂不同)`, columns `基因 | A 現任 | B 候選`; rows with `differs:true` get class `gene-diff-row`): `{gene: string, a: number, b: number, differs: bool}`; 16 rows in this fixed order: `w_ma_align, w_ma_cross, w_rsi, w_macd, w_kd, w_bb, w_volume, buy_th, strong_gap, sell_th, stop_pct, trail_pct, risk_frac, strong_mult, caution_scale, persistence`. Arm A values are the v6 incumbent (`w_* = 1.0,1.0,1.0,1.0,0.5,1.25,1.5`, `buy_th 3.0`, `strong_gap 2.0`, `sell_th -3.0`, `stop_pct 0.08`, `trail_pct 0.12`, `risk_frac 0.005`, `strong_mult 1.5`, `caution_scale 0.5`, `persistence 2.0`); arm B is `risk-exit-consensus` with unrounded floats (`w_ma_align 1.8490543082236912`, `stop_pct 0.08300581937609232`, `trail_pct 0.206062542287206`, `risk_frac 0.008025956907855073`, …) and identical `buy_th/strong_gap/sell_th/persistence` (`differs:false`). `fmtGene` prints `stop_pct/trail_pct/risk_frac` as `8.00%`, integers (`2.0` is an integer in JS) as `2`, others with 3 dp.

### 4.5 `verdict` and what the viewer shows in each state

| State | `active` | `rows` | `verdict` | What renders |
|---|---|---|---|---|
| not started | `false` | any | any | only `#shadow-empty` = `reason` (or `shadow 尚未起錶`) and the stale chip (l.1602–1611); the `active` check at l.1613 returns **before** the warning line, verdict banner and progress chip (l.1620–1647), so those stay empty/hidden |
| waiting for first row | `true` | `[]` | `null` | warnings (if any), progress chip `第 0/60 交易日 ・ B 平倉 0/10`, brief `起始日 …`, empty text `影子帳等待首行(…)` |
| running | `true` | ≥1 | `null` | brief, progress chip, legs, chart, three tables, genes; verdict banner hidden |
| adjudicated | `true` | ≥1 | object | same as running **plus** banner `#shadow-verdict` (class `empty-state`, l.1631–1637): `裁決({adjudicated}):{通過\|未通過}{(120 日硬上限)?} → {next}` |

Banner fields read: `verdict.adjudicated` (string, printed inside `裁決(…)`), `verdict.pass` (bool → `通過`/`未通過`), `verdict.capped` (bool → appends `(120 日硬上限)`), `verdict.next` (string after ` → `). Any other key is ignored. `verdict_sealed` is **not** read by the viewer.

**Sealing the verdict as "B adopted (manual cutover)"** — to display cleanly, emit (keys beyond the four are free-form and preserved for the record):

```json
"verdict": {"adjudicated": "2026-11-01 手動切換", "pass": true, "capped": false,
            "next": "採用 B(risk-exit-consensus)為正式參數 v10;影子對照結案",
            "kind": "manual_cutover", "sealed_at": "2026-11-01T09:00:00+08:00",
            "n_days": 55, "closed_b": 2, "note": "B adopted (manual cutover)"},
"verdict_sealed": true, "computing": false, "refresh_failed": false
```

which renders `裁決(2026-11-01 手動切換):通過 → 採用 B(risk-exit-consensus)為正式參數 v10;影子對照結案`. Keep `active: true`, `chain_ok: true`, `freeze_ok: true`, `warnings: []`, and keep `rows/legs/trades/holdings/genes` frozen at their last computed values so the tables remain visible under the banner; set `progress.ready: true`. Do **not** set `active:false` (that would blank the whole tab to one line) and do not put the explanation into `warnings` (it would render with a `⚠`). Because `pass` is a boolean, "manual cutover" must be conveyed through `adjudicated`/`next` text; `capped` must be `false` or the banner claims a 120-day cap. After sealing, the file should stop changing (`computing:false` keeps the `更新中…` chip hidden).

---

## 5. `simple.html` — engine-rendered family page

Generated at every bake together with `data.json` (both snapshots' `產生時間` equal `data.json.generated_at` to the minute). It consumes only `data.json` fields (01 §12 lists the mapping); this section gives the full template so it can be regenerated byte-for-byte. The head/CSS block is **identical** in Aug and Oct.

### 5.1 File-level rules

* Single-quoted HTML attributes throughout; no indentation; **no trailing newline** (both snapshots end in `</html>`).
* Physical newlines occur only (a) inside the `<style>` block (as written below), (b) inside the raw AI-note texts, (c) between block elements of the converted AI report. Everything else is on line 1 / line 26 / the last line.
* All numbers use Python formatting (`format(v, ',.0f')` etc.). Evidence for Python (not JS) rounding: `市值` shows `47,382` for `193×245.5 = 47381.5` and `364,078` for `1403×259.5 = 364078.5` — round-half-even, i.e. Python `'{:,.0f}'`.
* Class helper `cls(v)` = `up` if `v > 0`, `down` if `v < 0`, else `flat` (Aug 2308 `+0.00%` has class `flat`).
* Recommendation class `reccls(rec_code)`: `HOLD → hold`, `BUY`/`STRONG_BUY → buy`, `SELL`/`STRONG_SELL → sell` (Oct `SELL`→`rec sell` `賣出`, `STRONG_SELL`→`rec sell` `強力賣出`; Aug `BUY`→`rec buy`); the badge text is `rows[].rec_text`.

### 5.2 Head (line 1 up to `<style>`, then CSS lines 2–25 verbatim)

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

(the last line above continues directly into §5.3 on the same physical line 26.)

### 5.3 Body sections, in order (templates; `{…}` = Python format of the named `data.json` field)

1. **Header**
   `<h1>tw-quant 台股監控 <span class='badge'>唯讀快照</span><span class='badge'>紙上交易(虛擬資金)</span></h1>`
2. **Generated line**
   `<div class='meta'>產生時間 {generated_at[:16] with 'T'→' '}(台北時間).本頁每次掃描後自動更新;瀏覽器每 5 分鐘自動重新整理。</div>`
   → `產生時間 2026-10-31 14:15(台北時間).…`
3. **Market line**
   `<div class='meta' style='margin-top:6px'>加權指數 <span class='{cls(market.pct)}'>{market.index:,.0f}({market.pct:+.2f}%)</span>.大盤環境:{market.regime_label}</div>`
   → `加權指數 <span class='down'>45,212(-2.49%)</span>.大盤環境:偏空震盪` (score not shown)
4. **Watchlist heading + table**
   `<h2>觀察清單與 AI 解讀</h2><table><tr><th>代碼/名稱</th><th>價格</th><th>漲跌%</th><th>評分</th><th>建議</th></tr>` then one row per `overview.rows[]`, **sorted by `total` descending** (stable; Aug tie `2308`/`2881` at +2.5 kept the data-array order, which is also code order — either rule reproduces both snapshots):
   `<tr><td>{code} {name}</td><td>{price:,.2f}</td><td class='{cls(pct)}'>{pct:+.2f}%</td><td>{total:+.1f}</td><td><span class='rec {reccls}'>{rec_text}</span></td></tr>`
   → `<tr><td>2330 台積電</td><td>2,370.00</td><td class='down'>-1.86%</td><td>+0.8</td><td><span class='rec hold'>觀望</span></td></tr>` then `</table>`.
   Price is **always 2 dp with thousands** (`2,370.00`, `104.95` from the float32-noisy `104.94999694824219`); the `延` delayed-quote marker, `changed` dot and forecast tooltip of the viewer are **not** reproduced.
5. **AI notes**, one block per row that has `ai_note`, in the same sorted order as the table (9/9 rows in both snapshots):
   `<div class='ai'><span class='t'>🤖 {code} {name} AI 解讀 {ai_note.ts[11:16]}</span>{ai_note.text}</div>`
   → `<div class='ai'><span class='t'>🤖 2881 富邦金 AI 解讀 14:18</span>富邦金在金融股…` — the text is inserted **verbatim with its newlines** (`\n\n` paragraph breaks are kept as raw newlines; CSS does not set `white-space`, so they collapse visually). Whether the text is HTML-escaped is indeterminate (none of the 18 observed notes contains `<`, `>` or `&`); escaping with `html.escape(text, quote=False)` reproduces both snapshots and is the safe default. The time stamp is the note's own `ts` (2026-10-12 notes show `14:18` on the 10-31 page), not the bake time.
6. **Account heading + line**
   `<h2>紙上帳戶(虛擬 100 萬起步)</h2><div>權益 <b>{equity:,.0f}</b> 元(<span class='{cls(eqpct)}'>{eqpct:+.2f}%</span>).現金 {cash:,.0f}.已實現 {realized_pnl:+,.0f}.未實現 {unrealized_pnl:+,.0f}</div>`
   with `eqpct = (equity / initial_cash − 1) × 100` → `權益 <b>1,010,098</b> 元(<span class='up'>+1.01%</span>).現金 269,730.已實現 -23,214.未實現 +33,315`; zero prints `+0` (Aug `已實現 +0`).
7. **Positions table**
   `<table><tr><th>持股</th><th>股數</th><th>均價</th><th>現價</th><th>報酬%</th><th>市值</th><th>停損價</th><th>移停價</th><th>狀態</th></tr>` then one row per `overview.positions[]` in array order (which is code-ascending in both snapshots):
   `<tr><td>{code} {name}</td><td>{qty:,}</td><td>{avg_price:,.2f}</td><td>{price:,.2f}</td><td class='{cls(ret_pct)}'>{ret_pct:+.2f}%</td><td>{value:,.0f}</td><td>{stop_price:,.2f}</td><td>{trail_price:,.2f}</td><td><span class='rec hold'>續抱</span></td></tr>`
   → `<tr><td>2881 富邦金</td><td>1,618</td><td>136.72</td><td>161.50</td><td class='up'>+18.12%</td><td>261,307</td><td>125.78</td><td>144.76</td><td><span class='rec hold'>續抱</span></td></tr>` then `</table>`. Only `verdict == "hold"` is observed; the non-hold rendering is unobserved (§7).
8. **Exit legend**
   `<div class='meta'>賣出主要由出場機制執行:跌破停損價(-8%)或從高點回落至移停價(-12%)時狀態轉「該賣」,自動交易開啟時會自動出場。</div>` (identical in both snapshots; the two percentages equal the active `exit.stop_pct`/`exit.trail_pct`).
9. **AI daily report**
   `<h2>AI 收盤日報</h2><div class='meta'>{ai_report.date} 產生於 {ai_report.generated_at[11:16]}</div><div class='report'>{md_to_html(ai_report.content)}</div>`
   → `<div class='meta'>2026-10-12 產生於 14:16</div>` (the report's own date/time, 19 days stale on the Oct page).
10. **Footer**
    `<div class='foot'>本頁為唯讀快照,由程式自動產生(含 AI 生成之解讀文字,可能有誤).所有交易皆為紙上模擬、非真實資金。<br>{overview.disclaimer}</div></div></body></html>`
    where `disclaimer` = `本工具僅為技術分析參考,非投資建議;所有訊號與預測由公式機械式計算,必有誤差且會失準,下單請自行判斷風險。資料來源 Yahoo Finance,可能延遲 15–20 分鐘。`

### 5.4 Markdown → HTML converter for the report (reproduces both snapshots byte-for-byte)

Line-based, **different** from the viewer's `mdToHtml` (l.1346–1373, which emits `<div class="ai-md-h2">`). Rules, applied to `content.split('\n')` with each line `strip()`ped:

| Line | Output |
|---|---|
| blank | dropped (closes an open list) |
| `## text` (only `##` observed; proposed general rule `#`×k → `<h{k+2}>`) | `<h4>text</h4>` |
| `- text` | `<li>text</li>`; a run of such lines is wrapped in `<ul>` … `</ul>` placed on their own lines |
| anything else (paragraphs, numbered `1. …` items, markdown table rows `\| … \|`) | `<p>text</p>` — each source line becomes its own `<p>` |
| inline `**x**` | `<strong>x</strong>` |

Output blocks are joined with `\n` (so `<h4>…</h4>\n<p>…</p>\n<h4>…</h4>\n<ul>\n<li>…</li>\n…\n</ul>\n<h4>…`). Escaping is again indeterminate (no `<>&` in either report); use `html.escape(line, quote=False)` before the `**` substitution.

### 5.5 Formatting summary

| Value | Python format | Example |
|---|---|---|
| timestamps | `iso[:16].replace('T',' ')` / `iso[11:16]` | `2026-10-31 14:15`, `14:18` |
| index | `'{:,.0f}'` | `45,212` |
| price / avg / stop / trail | `'{:,.2f}'` | `2,370.00`, `42.55` |
| pct / ret_pct | `'{:+.2f}%'` | `-0.31%`, `+0.00%` |
| total | `'{:+.1f}'` | `+2.9`, `-5.5` |
| qty | `'{:,}'` | `1,618` |
| equity / cash / value | `'{:,.0f}'` | `1,010,098`, `47,382` |
| realized / unrealized | `'{:+,.0f}'` | `-23,214`, `+0` |

---

## 6. Missing/null tolerance summary

| Must hold | Why |
|---|---|
| `orders.json` is `{"orders": [...]}`; `events.json` has `events[].id` ints and a `last_id` | shim/renderer contracts (l.1379, l.247–251) |
| `events[].id` strictly increasing forever | viewer dedup (`id > lastEventId`) |
| `model-health.json` has `metrics.series[]` with `date/model/horizon/mae/hit_rate` numbers | chart builder multiplies by 100 and `toFixed` (l.1475) — a string would produce `NaN` |
| `params_history[].params_json` is a JSON **string** (or absent) | `JSON.parse(h.params_json \|\| '{}')` inside try/catch — an object would throw, caught, summary left empty |
| `shadow.rows[]` numbers, `legs.safety.mdd_*` and `legs.return.diff` numbers | `(sf.mdd_b*100).toFixed(1)` / `fmtPp(rt.diff*100)` throw on non-numbers **inside `renderShadow`**, aborting the rest of the tab |
| `shadow.trades[].score` number or null on BUY | `t.score.toFixed(1)` guarded by `!= null` |
| `shadow.holdings`, `verdict`, `warnings`, `arms`, `closeout`, `progress` | all optional (`\|\|` fallbacks) |

---

## 7. Open questions (with proposed defaults for the rebuild)

1. **Non-FILLED orders.** Only `FILLED` observed. Proposed: write a row for `REJECTED` (risk-cap/KILL/gate rejections) with `filled_price:null, filled_at:null, fee:0.0, tax:0.0, pnl:null, note:<rejection reason>`; never write `PENDING`/`CANCELLED` (paper fills are immediate).
2. **`source` for non-autopilot orders.** Only `autopilot` observed; the live dashboard's manual order path existed. Proposed: `manual`.
3. **`note` for a signal-driven exit** (`建議轉賣出` at l.1934; shadow uses reason `訊號`). Unobserved in orders. Proposed: `訊號出場({rec_text},評分 {s})`.
4. **`events` `ERROR` level and the `heartbeat` OK text.** Never observed. Proposed: `ERROR` for unhandled exceptions in a scan/EOD step (`{step} 失敗:{exception}`); heartbeat `心跳已送(OK)` when `red` is empty.
5. **Bullish news tilt event wording.** Only `消息面偏空` seen. Proposed: `消息面偏多 +{s}({n} 則)` with a symmetric threshold (|score| ≥ 1.0, observed values −1.0/−1.2).
6. **`metrics.series` date semantics** (creation-week Monday, §3.4) is inferred, not stated. Proposed: adopt it; recompute the whole series each bake from the forecast ledger; `n ≥ 1` rows only.
7. **Champion sufficiency threshold** (`樣本數足夠時取 MAE 較低者`). Proposed: champion = lower MAE when `n ≥ 30`, else `baseline`.
8. **`params_history` metric name** — `reward_points` since 2026-07-25; its definition lives in the tuner spec. Proposed: keep the name and the `+2%` threshold text; `train_metric` = in-sample `reward_points`.
9. **`shadow` leg pass rules** for `safety` and `return`. Proposed: `safety.pass = not doom and mdd_b ≤ max(mdd_a × 1.5, 0.10)`; `return.pass = diff > 0`; `operational.pass = prefix_breaks == 0`; `realization.pass = slip_bp_b ≤ max(2×slip_bp_a, 5) and reject_b ≤ max(2×reject_a, 0.01)`; `doom` = B equity below 0.8 × initial.
10. **`shadow.reason` text when inactive.** Proposed: `shadow 尚未起錶` (the viewer default) before the first bake, `影子對照已結案({date})` only if we ever choose `active:false`.
11. **`shadow.trades[].qty` on SELL rows is `null`.** The viewer prints `—`. Proposed: keep `null` for byte-parity, or fill the real quantity (harmless to the viewer).
12. **`simple.html` unobserved branches**: rows without `ai_note` (proposed: omit the block), empty `positions` (proposed: emit the header row only), non-hold verdict (proposed: `<span class='rec sell'>該賣</span>`), missing `ai_report` (proposed: `<div class='meta'>尚未產生</div>` and no `.report` div), HTML escaping of note/report text (proposed: escape).
13. **`虛擬 100 萬起步` and the `-8%`/`-12%` legend** — static strings or derived from `initial_cash` / active `exit` params? Proposed: derive (`f"{initial_cash/10000:.0f} 萬"`, `round(stop_pct*100)`), which reproduces the observed text.
14. **Bake cadence of `shadow.json`.** Observed only on trading days after EOD (14:50 / 20:44), never on the Saturday run. Proposed: rebake after every trading-day EOD and leave it untouched otherwise; after the manual cutover, stop rebaking.
