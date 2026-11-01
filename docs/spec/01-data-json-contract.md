# 01 — `data.json` output contract (as consumed by the read-only viewer)

Status: reverse-engineered from the surviving viewer (`app.js` 2082 lines, `index.html`, `simple.html`) and the two surviving baked snapshots of `data.json` (git `8623d98` = 2026-10-31T14:15:22+08:00, the working-tree file; git `2e74138` = 2026-08-15T14:15:32+08:00). Nothing here comes from engine source; every rule that is not literally in `app.js` is marked **inferred** with its evidence and a confidence.

All line numbers below are `app.js` unless prefixed `index.html:` or `simple.html:`.

---

## 0. Serialization conventions (whole file)

| Aspect | Rule | Evidence |
|---|---|---|
| Encoding | UTF-8, Chinese emitted raw (no `\uXXXX`) | `grep -c '\\u' data.json` = 0 |
| Layout | one single line, no trailing newline, Python `json.dumps(obj, ensure_ascii=False)` with default separators `", "` / `": "` | round-trip `json.dumps(json.loads(raw), ensure_ascii=False) == raw` is `True` |
| Key order | insertion order exactly as listed in the tables below (viewer does not care, but keep it for diff-stability) | both snapshots identical order |
| Timestamps | ISO-8601 with explicit Taipei offset and **second** precision, no microseconds: `2026-10-31T14:15:22+08:00`. Quote timestamps on rows carry `:00` seconds (`2026-10-30T18:17:00+08:00`). | all 25 timestamp values in both snapshots |
| Dates | `YYYY-MM-DD` (`ai_report.date`), months `YYYY-MM` (`reward.*.month`), ISO week `YYYY-Www` (`weekly_review.week`) | |
| Booleans | JSON `true`/`false` (never 0/1 or strings) | viewer tests with `!!`, `=== false` (l.454, l.473) |
| Floats | money/index/market pct are emitted **unrounded** (`269729.55000000005`, `-2.4941593686153634`); per-row `pct`, `ret_pct`, prices, `avg_price`, `stop_price`, `trail_price` are 2-dp; score components ≤2-dp; `total` 1-dp. Some `price` values carry float32 noise from the data source (`104.94999694824219`, `42.54999923706055`); the viewer formats them so this is tolerated, but the rebuild should round prices to 2 dp. | see §6 / §7 |
| Nulls | the viewer treats `null` and absent identically everywhere (`== null`, `||` fallbacks); see per-field "missing" columns | |

Top-level shape:

```json
{"generated_at": "<iso>", "overview": {...}, "ai_report": {...}}
```

| Key | Type | Required | Consumer |
|---|---|---|---|
| `generated_at` | iso string | tolerated missing → "資料時間 — 台北" | `renderViewerGenerated` l.198–213, called from l.223 |
| `overview` | object | **required** (missing → `#conn-dot` red "連線中斷 — 無法取得 /api/overview", nothing renders) | `viewerApi('/api/overview')` l.221–225 → `refreshOverview` l.341–380 |
| `ai_report` | object | tolerated missing (card keeps "收盤後自動產生") | `viewerApi('/api/ai-report')` l.226–229 → `loadAiReport` l.1315–1321 |

Both snapshots: `overview.ts == generated_at` (same second).

---

## 1. How the viewer loads `data.json`

### 1.1 Viewer mode and the API shim

`index.html:299` sets `window.TWQ_VIEWER = true`; `app.js:172` `const VIEWER = !!window.TWQ_VIEWER`. `api()` (l.266–277) routes every call to `viewerApi()` (l.215–264) which maps the old FastAPI paths onto baked files:

| Dashboard path (as called in app.js) | Baked file | Returned `data` | Lines |
|---|---|---|---|
| `GET /api/overview` | `data.json` (memoized) | `data.json.overview`; side effect: renders `#viewer-generated` from `data.json.generated_at` | 221–225 |
| `GET /api/ai-report` | `data.json` (memoized) | `data.json.ai_report` | 226–229 |
| `GET /api/symbol/<SYM>?bars=250` | `symbol/<code>.json` where `<code>` = `<SYM>` with `/\.(TW\|TWO)$/i` stripped and the query string dropped (`2330.TW` → `symbol/2330.json`) | whole file | 230–236 |
| `GET /api/orders?limit=50` | `orders.json` | whole file | 237 |
| `GET /api/model-health` | `model-health.json` | whole file | 238 |
| `GET /api/shadow` | `shadow.json` | whole file | 239 |
| `GET /api/events?after_id=N&limit=100` | `events.json`; client filters `events[].id > N`, returns `{events, last_id}` (`last_id` falls back to `N`) | 240–255 |
| `GET /api/config` | no file; constant `{mode:'paper', confirm_phrase_required:false, caps:{}, thresholds:{}, watchlist:[]}` | 256–262 |
| anything else | `{ok:false, status:404, data:null}` | 263 |
| any non-GET | throws `'唯讀檢視不允許 ' + method + ' ' + path` (unreachable: the mutating UI is absent from index.html) | 216–219 |

Cross-file consequences for the engine:

* Every `overview.rows[].symbol` and `overview.positions[].symbol` must have a matching `symbol/<code>.json`, and that file's own `symbol` field must equal the row's `symbol` string exactly (`2330.TW`), otherwise `loadSymbol` discards it (l.809 `if (r.data.symbol !== S.selected) return;`).
* `events.json` must be `{events:[{id,...}], last_id}` with monotonically increasing integer `id` (l.247–251).

### 1.2 Cache-busting and the 10-second memo

* `viewerFetchJson(file)` (l.174–185) fetches `file + '?t=' + Date.now()` with `{cache:'no-store'}` — a unique query on every request to defeat the GitHub Pages CDN (~10 min cache). Returns `{ok, status, data}`; never throws; non-JSON body → `data:null`.
* `viewerData()` (l.190–196) memoizes the `data.json` fetch promise for **10 000 ms** so that `/api/overview` and `/api/ai-report` in the same poll cycle share one network request, while each 5-minute cycle gets a fresh copy.
* `index.html:7` / `index.html:300` version-stamp `app.css?v=20260906a` and `app.js?v=20260906a` (manual bump when the viewer code changes; irrelevant to data files).

### 1.3 Poll cycle (`init`, l.2046–2075)

| Step | Viewer behaviour | Lines |
|---|---|---|
| boot | `bindUI()` → `loadConfig()` (static stub) → `refreshOverview()` → `pollEvents()` (because `#event-feed` exists in index.html:288) | 2047–2052 |
| events | `setInterval(pollEvents, 300000)` | 2054 |
| overview | every **300 000 ms**: `refreshOverview()` and, if a symbol is selected, `loadSymbol(S.selected, {silent:true})` | 2061–2064 |
| countdown | `tickCountdown` every 1 000 ms (only `#last-scan` is updated in the viewer; `#next-scan` is absent → l.469–470 early return) | 2065 |
| health tab | while open, reload if older than 300 000 ms (checked every 10 s) | 2066–2068 |
| shadow tab | while open, reload if older than 300 000 ms (checked every 10 s) | 2069–2074 |
| AI report | inside every `refreshOverview` (viewer threshold is `0` ms, l.379) → reads the memoized `data.json` | 376–379 |

`refreshOverview` (l.341–380) render order: `renderTopbar` → `renderWatchlist` → `renderAccount` (→ `renderReward`) → `renderPositions` → `renderRecs` → `renderOrderCard` (no-op in viewer, l.648) → `renderSymbolHead` → disclaimer → default symbol selection (`sortedRows()[0].symbol`, i.e. highest `total`) → scan-change detection → `loadAiReport`. **A thrown exception anywhere in this chain aborts the rest of the cycle** (see `reward.provisional` below for the one place the viewer can throw on bad data).

Scan-change detection (l.368–374): when `overview.engine.last_scan` differs from the last value seen (and it is not the first load) the open symbol's JSON is re-fetched.

### 1.4 "資料時間" / `#viewer-generated`

`index.html:42` `<span id="viewer-generated" class="num">資料時間 — 台北</span>` inside the banner `唯讀檢視 — 資料為紙上模擬(虛擬資金),由主機自動發佈`. `renderViewerGenerated(iso)` (l.198–213) sets `textContent = '資料時間 ' + hm + ' 台北'` where `hm` is `generated_at` rendered with `toLocaleTimeString('zh-TW', {timeZone:'Asia/Taipei', hour12:false, hour:'2-digit', minute:'2-digit'})` → e.g. `資料時間 14:15 台北`; invalid/missing → `資料時間 — 台北`. Updated only on the `/api/overview` path (l.223).

### 1.5 Formatting helpers referenced below

| Helper | Lines | Behaviour |
|---|---|---|
| `clsOf(v)` | 82 | `'up'` if `v>0`, `'down'` if `v<0`, else `'flat'` (Taiwan convention: red = up, green = down; `app.css:48–50`) |
| `fmtPrice(v)` | 84–90 | null/non-finite → `—`; `|v|≥1000` → `toLocaleString('en-US')` with 0 dp (`2,370`); `|v|≥100` → 1 dp (`245.5`); else 2 dp (`42.55`) |
| `fmtMoney(v)` | 92–95 | null → `—`; `Math.round(v).toLocaleString('en-US')` (`269,730`) |
| `fmtSignedMoney(v)` | 97–101 | as `fmtMoney` with explicit `+`/`-` (`+33,315`, `-23,214`, `0`) |
| `fmtPct(v, d=2)` | 103–106 | **input already in percent units**; `(v>0?'+':'') + v.toFixed(d) + '%'` (`-2.49%`, `+18.12%`, `0.00%`) |
| `fmtRet(r, d=1)` | 108–111 | **input is a fraction**; `fmtPct(r*100, d)` (`0.0274` → `+2.7%`) |
| `fmtTilt(v)` | 145–148 | null/NaN → `+0.0`; `(x>=0?'+':'') + x.toFixed(1)` |
| `fmtClock(iso)` | 120–133 | `HH:MM:SS` in `Asia/Taipei`; missing/invalid → `—` |
| `fmtHM(iso)` | 140–143 | `HH:MM` in `Asia/Taipei`; missing → `—` |
| `fmtDateTime(iso)` | 135–138 | pure string op: `replace('T',' ').slice(0,16)` → `2026-10-12 14:16` (**no** tz conversion; relies on the engine emitting Taipei time) |
| `escapeHtml` | 75–79 | all strings from JSON are HTML-escaped before insertion |

---

## 2. `overview.ts`

| Field | Type | Example | Rendered by | Missing | Notes |
|---|---|---|---|---|---|
| `ts` | iso string | `"2026-10-31T14:15:22+08:00"` | **not read by app.js** (grep `overview.ts` → none) | tolerated | equals `generated_at` in both snapshots; keep emitting the export time |

---

## 3. `overview.market`

Rendered by `renderTopbar` l.393–411 into `index.html:17–23` (`#market-badge` > `#market-label`, `#market-index`, `#market-pct`, `#market-regime`). Whole object missing → `m = {}` (l.395): label `收盤`, index `—`, pct `—`/flat, regime chip hidden.

| Field | Type | Example | Rendering | Missing/null |
|---|---|---|---|---|
| `is_open` | bool | `false` | `#market-badge.className = 'badge ' + (is_open ? 'blue' : 'gray')` (l.399); fallback label source (l.398) | falsy → gray / `收盤` |
| `label` | string | `"收盤"` | `#market-label.textContent = label \|\| (is_open ? '盤中' : '收盤')` (l.398) | tolerated |
| `index` | number (unrounded) | `45211.828125` | `fmtPrice` → `45,212` (l.400) | null → `—` |
| `pct` | number, **percent units**, unrounded | `-2.4941593686153634` | `fmtPct` → `-2.49%`; class `num up/down/flat` by sign (l.401–403) | null → `—`, class `flat` |
| `regime_label` | string | `"偏空震盪"` | `#market-regime.textContent = regime_label + (score != null ? ' ' + (score>0?'+':'') + score : '')` → `偏空震盪 -0.5`; class `mini-chip up/down/''` by sign of `score`; chip hidden when `regime_label` falsy (l.404–411). **`score` is concatenated raw** (no `toFixed`), so emit a short literal such as `-0.5`. | missing → chip hidden |
| `score` | number | `-0.5` | see above | null → label only |

Enumerations observed:

| `label` | `is_open` | Seen | Note |
|---|---|---|---|
| `收盤` | `false` | both snapshots | app.js fallback for closed |
| `盤中` | `true` | not observed; app.js fallback string (l.398) | **inferred** as the open-market label (medium) |

| `regime_label` | `score` | Seen |
|---|---|---|
| `偏空震盪` | `-0.5` | 2026-10-31 |
| `偏多震盪` | `+0.5` | 2026-08-15 |

`market.score` is the same number as every `rows[].mkt_score` in the same snapshot (`-0.5` ×9 in Oct, `+0.5` ×9 in Aug) — **inferred** `rows[].mkt_score = market.score` (high). AI texts refer to a `多頭`/`空頭` market environment, so stronger labels/scores (e.g. `±1.0`) probably exist but are unobserved (see Open questions).

`simple.html:26` renders the same block as `加權指數 <span class='down'>45,212(-2.49%)</span>.大盤環境:偏空震盪` (index 0 dp with thousands; pct 2 dp signed; class by sign of pct; regime label only, no score).

---

## 4. `overview.engine`

Rendered by `renderTopbar` l.413–458 and `tickCountdown` l.463–481. Whole object missing → `e = {}` (l.396): mode `紙上交易`, no KILL badge, `參數 v—`, `AI 助理:未啟用`, `上次掃描 —`, no health chips.

| Field | Type | Example | Rendering (index.html element) | Missing/null | Viewer use |
|---|---|---|---|---|---|
| `running` | bool | `true` | not read | tolerated | none |
| `scanning` | bool | `false` | only `#scan-state` (absent) and `#next-scan` (absent) — l.438–439, 471 | tolerated | none in viewer |
| `tuning` | bool | `false` | only `#tune-state` (absent) l.440–441 | tolerated | none in viewer |
| `last_scan` | iso string | `"2026-10-30T18:17:00+08:00"` | `#last-scan` (`index.html:26`, label `上次掃描(台北)`) = `fmtClock(last_scan) + (last_scan && last_scan_kind ? '(' + last_scan_kind + ')' : '')` → `18:17:00(啟動)` (l.467–468). Also the scan-change trigger (l.369–374). | `—` | yes |
| `last_scan_kind` | string | `"啟動"` | suffix in parentheses after the clock, see above | no suffix | yes |
| `next_scan` | iso string | `"2026-10-30T18:22:00+08:00"` | only `#next-scan` countdown, element absent in viewer (l.469–470) | tolerated | none in viewer |
| `scan_interval_min` | int | `5` | not read | tolerated | none |
| `mode` | `"paper"` \| `"real"` | `"paper"` | `#mode-badge` = `實盤` (class `badge red`) if `real` else `紙上交易` (class `badge blue`); `#acct-mode` (`index.html:96`) = `實盤` / `紙上` (l.413–417) | → `paper` | yes |
| `kill` | bool | `false` | `#kill-badge` (`KILL 已啟動 — 下單全面封鎖`, `index.html:32`) shown when truthy (l.428); also disables (absent) order buttons l.652, 1165 | hidden | yes |
| `params_version` | int | `9` | `#params-badge` = `'參數 v' + params_version` → `參數 v9` (l.429) | `參數 v—` | yes |
| `autopilot` | bool | `true` | only `#btn-autopilot` (absent) l.419–426 | tolerated | none in viewer |
| `ai` | object | see §4.1 | `#ai-badge` l.431–437; `aiEnabled()` l.762–765 | `{}` → `AI 助理:未啟用` | yes |
| `health` | object \| absent | see §4.2 | `#health-chips` (`index.html:27`) l.446–458 | absent → no chips (Aug snapshot had no `health` key at all) | yes |

Evidence on timing: `last_scan`/`next_scan` differ by exactly `scan_interval_min` (5 min) in both snapshots; `next_scan` is in the past relative to `generated_at` because both snapshots are Saturday 14:15 EOD exports (2026-08-15 and 2026-10-31 are Saturdays) made after a Friday-evening restart (`啟動`). `rows[].ts == engine.last_scan` for all 18 rows across both snapshots.

Enumeration of `last_scan_kind`: only `啟動` observed (both snapshots). The app.js comment at l.465–466 (2026-07-29) says the suffix exists so that `14:15:21` alone does not read as "the closing session was never scanned", i.e. other kinds name the closing-session scan. Event messages name scan types `收盤定盤掃描` (events.json id 6729: `收盤定盤掃描完成:9 檔以收盤世界重新定價(其中 9 檔取得交易所定盤價);14:15 EOD 會再以完整日K做最終校正。`), `EOD` (id 6737 `EOD 完成:…`), and `晨會` (id 6695). Exact strings are unknown → Open questions.

### 4.1 `engine.ai`

| Field | Type | Example | Rendering | Missing |
|---|---|---|---|---|
| `enabled` | bool | `true` | `#ai-badge.textContent = 'AI 助理:' + (enabled ? '啟用' : '未啟用')`; class `badge blue` / `badge gray` (clears the initial `hidden`); gates the per-symbol "尚未產生" placeholder in `renderAiNote` (l.779) | falsy → `未啟用`, title `後端 AI 助理未啟用` |
| `model_fast` | string | `"sonnet"` | badge `title = '快速模型 ' + model_fast + ' ・ 深度模型 ' + model_deep` | `—` |
| `model_deep` | string | `"opus"` | see above | `—` |

Values observed: `model_fast` = `sonnet`, `model_deep` = `opus` (both snapshots; events log `AI 呼叫失敗(sonnet,rc=1)` / `(opus,rc=1)`). The same object is duplicated verbatim as `ai_report.ai`.

### 4.2 `engine.health` (added between the Aug and Oct snapshots; viewer support added in `app.css?v=20260906a`)

Only `red[]` and `configured` are read (l.450–455); the rest is informational.

| Field | Type | Example | Rendering | Missing |
|---|---|---|---|---|
| `configured` | bool | `true` | `=== false && !VIEWER` → chip `心跳未設定`; **never shown in the viewer** (l.454) | tolerated |
| `share_days` | int | `1` | not read | — |
| `ai_days` | int | `19` | not read | — |
| `share_enabled` | bool | `true` | not read | — |
| `ai_enabled` | bool | `true` | not read | — |
| `ai_last_success` | iso string | `"2026-10-12T14:18:21+08:00"` | not read | — |
| `ai_last_error` | object \| null | `{"ts": "2026-10-31T14:15:21+08:00", "model": "opus", "rc": 1, "error": "Failed to authenticate: OAuth session expired and could not be refreshed"}` | not read | — |
| `ai_hard_failure` | bool | `false` | not read | — |
| `red` | string[] | `["AI 日報 19 天未產生"]` | each string → `<span class="mini-chip red" title="監控紅燈:每日 EOD 會把它送到外部心跳的 /fail 端點">…</span>` in `#health-chips` (l.451–453) | `[]`/missing → no chips |
| `checked_at` | iso string | `"2026-10-31T14:15:22+08:00"` | not read | — |

**Inferred** semantics (medium): `ai_days` = calendar days from `ai_last_success` date to `checked_at` date (2026-10-12 → 2026-10-31 = 19 ✓); the red string pattern is `AI 日報 {ai_days} 天未產生` (events on 10-29/10-30/10-31 carry 17/18/19; heartbeat event text `心跳已送(FAIL:AI 日報 19 天未產生)` shows `red[]` is joined into the heartbeat `/fail` payload). `share_days` = days since the family page (`simple.html`/this repo) was last published (1 on a Saturday → last publish Friday). The red threshold and the share-page red string are unobserved → Open questions.

---

## 5. `overview.account`

Rendered by `renderAccount` l.555–567 into `index.html:95–102` (card title `帳戶`). Missing object → `{}` → every value `—`.

| Field | Type | Example | Element / label | Format | Missing |
|---|---|---|---|---|---|
| `cash` | number (unrounded) | `269729.55000000005` | `#acct-cash` `現金` | `fmtMoney` → `269,730` | `—` |
| `initial_cash` | number | `1000000.0` | not read by app.js; `simple.html` uses it (`虛擬 100 萬起步`, equity % = `(equity/initial_cash-1)*100` → `+1.01%`) | | tolerated |
| `positions_value` | number | `740368.5` | `#acct-value` `持倉市值` | `fmtMoney` | `—` |
| `equity` | number | `1010098.05` | `#acct-equity` `總權益` (also the denominator for 建議部位 % l.1179–1181) | `fmtMoney` | `—`; recs % → `—` |
| `realized_pnl` | number | `-23213.919999999875` | `#acct-realized` `已實現損益` | `fmtSignedMoney`, class `num up/down/flat` | `—`, flat |
| `unrealized_pnl` | number | `33314.96000000002` | `#acct-unrealized` `未實現損益` | `fmtSignedMoney`, class by sign | `—`, flat |

**Inferred** identities (high, exact in both snapshots): `equity = cash + positions_value`; `positions_value = Σ positions[].value`; `unrealized_pnl = Σ positions[].qty × (price − avg_price)` (matches to the cent using the 2-dp `avg_price`). `equity − initial_cash` is **not** equal to `realized_pnl + unrealized_pnl` (Oct: 10 098.05 vs 10 101.04; Aug: 8 754.09 vs 8 763.22) → the PnL fields follow the broker ledger's own fee/tax accounting (see Open questions).

`simple.html:68` renders: `權益 <b>1,010,098</b> 元(<span class='up'>+1.01%</span>).現金 269,730.已實現 -23,214.未實現 +33,315` (equity/cash rounded with thousands; realized/unrealized signed; the pct class by sign).

---

## 6. `overview.positions[]`

Rendered by `renderPositions` l.598–644 into `#positions-list` (`index.html:111–116`, card `持股`), count chip `#pos-count` = `N 檔` (empty string when none), empty state `目前無持股`. Rows are rendered **in array order** (no sort). Clicking a row selects the symbol (l.632–634). Also used by `positionOf()` (l.387–390) for chart mark-lines (l.894–907) and for SELL rows in the recs tab (l.1169–1170).

| Field | Type | Example | Rendering | Missing |
|---|---|---|---|---|
| `symbol` | string | `"2317.TW"` | `data-symbol` (click target, `positionOf` key, must match `rows[].symbol` / `symbol/<code>.json.symbol`) | **required** |
| `code` | string | `"2317"` | `<b>2317</b>` | `''` |
| `name` | string | `"鴻海"` | `<span class="dim">鴻海</span>` | `''` |
| `qty` | int (shares; odd lots allowed, e.g. `1`, `17`) | `193` | `(qty \|\| 0).toLocaleString('en-US') + '股'` → `193股` | `0股` |
| `avg_price` | number 2-dp | `245.83` | `均價 ` + `fmtPrice`; chart dashed mark-line `均價 245.83` (l.904) when truthy | `—`; no line |
| `price` | number | `245.5` | not shown in the list (used by order UI only); same value as the matching `rows[].price` | tolerated |
| `ret_pct` | number 2-dp, **percent units** | `-0.14` | `fmtPct` → `-0.14%`, class `num up/down/flat` | `—` |
| `value` | number | `47381.5` | not read by app.js | tolerated |
| `stop_price` | number 2-dp | `226.17` | `停損 ` + `fmtPrice`; chart mark-line `停損 226.17` colour `#e5a13a` when truthy (l.905) | `—`; no line |
| `trail_price` | number 2-dp | `216.48` | `移停 ` + `fmtPrice`; chart mark-line `移停 216.48` colour `#4ac6b7` when truthy (l.906) | `—`; no line |
| `peak` | number | `246.0` | not read by app.js | tolerated |
| `verdict` | string | `"hold"` | `isHold = !verdict \|\| verdict === 'hold'`; badge `<span class="verdict-badge verdict-hold">續抱</span>` else `<span class="verdict-badge verdict-exit">該賣</span>` (l.608–610, 618) | → `續抱` |
| `reasons` | string[] | `[]` | joined with `、` into the row's `title` tooltip (l.611–612) | `''` |

**Inferred** formulas (high; verified on all 10 positions across both snapshots):

| Rule | Evidence |
|---|---|
| `value = qty × price` (exact) | 10/10 exact |
| `stop_price = round(avg_price_unrounded × 0.92, 2)` (stop-loss −8 %) | 7/10 exact on the 2-dp `avg_price`; 3 off by 0.01 (`2317` Oct 226.16 vs 226.17, Aug 237.42 vs 237.43; `2454` Aug 3712.61 vs 3712.62) → computed from the unrounded average |
| `trail_price = round(peak × 0.88, 2)` (trailing stop −12 % from peak) | 10/10 exact |
| `ret_pct = round((price / avg_price_unrounded − 1) × 100, 2)` | 8/10 exact; 2 off by 0.01 for the same reason |
| `peak ≥ price` | 10/10 |
| `simple.html:68` legend text: `賣出主要由出場機制執行:跌破停損價(-8%)或從高點回落至移停價(-12%)時狀態轉「該賣」,自動交易開啟時會自動出場。` and `app.js:1934` `持股觸發停損/移動停利、或建議轉賣出 → 全數賣出` | confirms 8 %/12 % and that the non-hold verdict is "該賣" |

Only `verdict = "hold"` with `reasons = []` is observed. The non-hold value and the `reasons` strings are unobserved → Open questions (the CSS class is `verdict-exit`).

`simple.html` positions table (`simple.html:68`): columns `持股 | 股數 | 均價 | 現價 | 報酬% | 市值 | 停損價 | 移停價 | 狀態`; `code name`, qty with thousands, avg/price/stop/trail **always 2 dp with thousands** (`2,427.16`, `2,370.00`), ret signed 2 dp with class, value 0 dp, status `<span class='rec hold'>續抱</span>`.

---

## 7. `overview.rows[]` (watchlist)

Array order in both snapshots is the fixed watchlist order `2330, 2317, 2454, 2308, 2882, 0050, 6789, 3481, 2881` (not sorted by score). The viewer sorts itself (`sortedRows` l.484–493: default key `total` descending, `null` sorts as `-Infinity`, tie-break `symbol.localeCompare`; headers `價格`/`漲跌%`/`評分` toggle keys `price`/`pct`/`total`). The first load selects `sortedRows()[0].symbol` (highest `total`, l.363–366). `simple.html` lists rows sorted by `total` descending too (verified: `2881 +2.9, 2882 +2.7, 2317 +1.4, 2330 +0.8, 3481 +0.3, 6789 -2.2, 2454 -2.8, 0050 -3.1, 2308 -5.5`).

Rendered by `renderWatchlist` l.495–539 (`#watchlist-body`, `index.html:49–67`), `renderRecs` l.1151–1219 (`#recs-body`, `index.html:146–156`), `renderSymbolHead` l.686–759, `renderAiNote` l.767–785. Empty array → `觀察清單為空` / `目前沒有非觀望的建議`.

| Field | Type | Example | Rendering | Missing/null |
|---|---|---|---|---|
| `symbol` | string | `"2330.TW"` | row `data-symbol`; selection key; `symbol/<code>.json` lookup (§1.1) | **required** |
| `code` | string | `"2330"` | `<span class="code">2330</span>`; `#sym-title` = `code + ' ' + name` (l.694); recs `<b>2330</b>` | `''` |
| `name` | string | `"台積電"` | `<span class="name">台積電</span>` | `''` |
| `price` | number | `2370.0` | `fmtPrice` in watchlist (l.517), recs (l.1197), `#sym-price` (l.698, class `num big up/down/flat` by `pct`); denominator-free factor in 建議部位 % | `—`; recs % → `—` |
| `ts` | iso string | `"2026-10-30T18:17:00+08:00"` | only in the delayed-quote tooltip: `延遲價(非交易所即時報價),擷取 ` + `fmtHM(ts)` (l.520) | `擷取 —` |
| `quote_fresh` | bool | `false` | when **falsy** a `<span class="dim" title="延遲價(非交易所即時報價),擷取 HH:MM">延</span>` is appended after the price (l.518–521); truthy → nothing | → `延` shown |
| `pct` | number 2-dp, **percent units** | `-1.86` | `fmtPct` + class `num up/down/flat` (l.522); `#sym-pct` (l.700–701) | `—`, flat |
| `total` | number 1-dp | `0.8` | `total.toFixed(1)` with class by sign (l.523, l.1196); sort key; recs filter/sort by `Math.abs(total)` (l.1159); tooltip `scoreTitle` | `—`; sorts last |
| `tech_total` | number ≤2-dp | `0.25` | raw string concat in the 評分 cell tooltip: `'技術 ' + tech_total + ' ・ 大盤 ' + mkt_score + ' ・ 基本面 ' + fund_total + ' ・ 消息 ' + fmtTilt(news_total) + ' ・ 籌碼 ' + fmtTilt(chips_total) + (kd60 ? ' ・ 60分KD ' + kd60.label : '')` (l.505–507) → `技術 0.25 ・ 大盤 -0.5 ・ 基本面 1.5 ・ 消息 +0.5 ・ 籌碼 -1.0 ・ 60分KD 中性` | prints `undefined` (ugly, no crash) |
| `mkt_score` | number | `-0.5` | tooltip (raw) | `undefined` |
| `fund_total` | number 1-dp | `1.5` | tooltip (raw) | `undefined` |
| `news_total` | number 2-dp | `0.5` | tooltip via `fmtTilt`; signal chip `消息 +0.5` (`sig-chip news up/down/flat`, l.738–741) | `+0.0` |
| `chips_total` | number (multiples of 0.5) | `-1.0` | tooltip via `fmtTilt`; signal chip `籌碼 -1.0` (l.743–746) | `+0.0` |
| `kd60_total` | number | `0.0` | KD chip suffix `' ' + fmtTilt(kv)` only when non-zero (l.749–755) | falls back to `kd60.score`/0 |
| `kd60` | object \| null | see §7.1 | tooltip label; signal chip (l.748–756) | absent → no KD text; chip falls back to `symbol.json.intraday_kd` |
| `rec_code` | enum string | `"HOLD"` | `REC[rec_code] \|\| REC.HOLD` → badge (l.503, 524, 1167, 1195); recs tab keeps rows with `rec_code && rec_code !== 'HOLD'` (l.1158); BUY/STRONG_BUY vs others decides which qty is used (l.1168–1170) | → `觀望` |
| `rec_text` | string | `"觀望"` | **not read by app.js** (it uses the `REC` table); `simple.html` prints it | tolerated |
| `changed` | bool | `false` | truthy → `<span class="changed-dot" title="本次掃描建議有變化">●</span>` after the code (l.512) | no dot |
| `regime` | enum string | `"range"` | `REGIME[regime]` → `#sym-regime` chip text/class (l.703–712); falls back to `symbol.json.trend.summary.regime` | chip hidden |
| `forecast5` | object \| null | see §7.2 | watchlist row `title` (l.508–509); recs `5日預測` cell (l.1171–1174) | no title; recs cell `累積中` |
| `suggest_qty` | int (shares) | `34` | recs tab 建議部位 % for BUY/STRONG_BUY rows: `((qty × price / equity) × 100).toFixed(1) + '%'` when `equity>0 && qty>0 && price>0`, else `—` (l.1170, 1179–1184); for SELL rows `qty` = held `positions[].qty` | 0 → `—` |
| `ai_note` | object \| null | see §7.3 | 🤖 dot in watchlist (l.513–515); `#ai-note` block (l.767–785) | no dot; `#ai-note` shows `尚未產生` when `engine.ai.enabled` |

### 7.1 `rows[].kd60`

| Field | Type | Example | Rendering |
|---|---|---|---|
| `k` | number 1-dp | `20.5` | not rendered |
| `d` | number 1-dp | `27.1` | not rendered |
| `label` | string | `"中性"` | tooltip `60分KD 中性`; chip text `60分KD ` + label (default `中性`) |
| `note` | string | `"60分K線 K=20 D=27"` | chip `title` = note + `;短線輔助(未回測,僅小幅 tilt)` (default `60分K線 KD`) |

`symbol/<code>.json.intraday_kd` has the same keys plus `score` (= `kd60_total`); `rows[].kd60` omits `score`. `note` pattern: `60分K線 K={round(k)} D={round(d)}`.

Observed `label` / `kd60_total` pairs: `中性` → `0.0` (14×), `低檔` → `0.3` (3×: K/D = 12/14, 13/26, 4/11), `低檔黃金交叉` → `0.5` (1×: K=16.0 > D=15.3, both <20). **Inferred** (medium): "低檔" = K and D below 20; "黃金交叉" = K crossed above D; full label set and the symmetric high-side labels/scores are unobserved → Open questions.

### 7.2 `rows[].forecast5`

| Field | Type | Example | Rendering |
|---|---|---|---|
| `pred_ret` | number, **fraction** | `0.0` | `fmtRet` → `+0.0%`; recs cell class `clsOf(pred_ret)`; title `5日預測 +0.0%(漲率 50%,baseline)` (l.509) |
| `prob_up` | number 0–1 | `0.5` | `'漲率' + Math.round((prob_up \|\| 0) * 100) + '%'` |
| `ci68_lo` | number, fraction | `-0.027381500634110295` | not read by app.js (the chart uses `symbol.json.forecast`) |
| `ci68_hi` | number, fraction | `0.027381500634110295` | not read |
| `model` | string | `"baseline"` | in the title only (escaped) |

Observed models: `baseline` (Oct: `pred_ret=0.0`, `prob_up=0.5`, symmetric `ci68`) and `ridge` (Aug: non-zero `pred_ret`, asymmetric `ci68`, `prob_up` 0.26–0.77). `forecast5` equals the `horizon_days == 5` entry of `symbol/<code>.json.forecast.horizons` (`pred_ret`, `prob_up`, `ci68[0..1]`, `model`) — verified for 2330.

### 7.3 `rows[].ai_note`

| Field | Type | Example | Rendering |
|---|---|---|---|
| `ts` | iso string | `"2026-10-12T14:16:22+08:00"` | `fmtHM` → `14:16` (date is **not** shown) in both the dot tooltip `AI 解讀 14:16:<text>` and `#ai-note` (`<span class="ai-note-time num dim" title="產生時間">14:16</span>`) |
| `rec_code` | enum string | `"STRONG_BUY"` | not read by app.js |
| `text` | string (multi-paragraph, `\n\n` separators) | `"技術面是這波評分的主要支撐——…以上為數據解讀,非投資建議。"` | escaped `textContent`-style insertion into `.ai-note-text` (newlines collapse in HTML) |

The note is only shown when `text` is non-empty (l.774). The same object (same shape) is duplicated in `symbol/<code>.json.ai_note`, which `renderAiNote` prefers when the detail belongs to the selected symbol (l.771–773).

**Inferred** (high): `ai_note.rec_code` is the recommendation at the time the note was generated, not the current one — all 9 Oct notes are dated 2026-10-12 and their `rec_code` matches the 2026-10-12 AI report's per-symbol verdicts exactly (`2330` `+5.4【強力買進】`↔`STRONG_BUY`, `2317` `【觀望】`↔`HOLD`, `2454`↔`BUY`, `2308`↔`STRONG_BUY`, `2882`↔`STRONG_BUY`, `0050`↔`BUY`, `6789`↔`STRONG_BUY`, `3481`↔`STRONG_BUY`, `2881`↔`BUY`), while the current `rec_code`s are `HOLD`/`SELL`/`STRONG_SELL`. Notes persist unchanged across days when the AI is failing (19 days old on 2026-10-31); they are generated one per symbol sequentially right after the 14:15 EOD (timestamps 14:16:22 → 14:18:36, ~15–20 s apart).

`simple.html:26–68` prints each note as `<div class='ai'><span class='t'>🤖 {code} {name} AI 解讀 {HH:MM}</span>{text}</div>` in watchlist (score-desc) order, with the raw text (newlines kept, **not** HTML-escaped).

### 7.4 Enumerations

`rec_code` → badge (`REC`, l.24–30; `rec_text` in data.json matches these strings exactly):

| `rec_code` | `rec_text` / badge text | CSS class (`app.css:201–205`) | `simple.html` class |
|---|---|---|---|
| `STRONG_BUY` | `強力買進` | `rec-badge rec-sbuy` | `rec buy` (inferred from `BUY`) |
| `BUY` | `買進` | `rec-badge rec-buy` | `rec buy` (observed Aug) |
| `HOLD` | `觀望` | `rec-badge rec-hold` | `rec hold` |
| `SELL` | `賣出` | `rec-badge rec-sell` | `rec sell` |
| `STRONG_SELL` | `強力賣出` | `rec-badge rec-ssell` | `rec sell` |

Any other/missing code renders as `觀望`.

`regime` → chip (`REGIME`, l.31–35): `bull` → `多頭` (class `mini-chip up`), `bear` → `空頭` (`mini-chip down`), `range` → `盤整` (`mini-chip`). Unknown → chip hidden. All three observed.

**Inferred** scoring relations (for cross-reference with the scoring spec; the viewer does not recompute anything):

| Rule | Evidence | Confidence |
|---|---|---|
| `total = round(tech_total + mkt_score + fund_total + news_total + chips_total + kd60_total, 1)` **at scan time** | Oct: 9/9 rows match; Aug: 6/9 match, 3 rows (`2317` sum 3.66 vs 3.0, `2454` 2.38 vs 2.2, `2308` 2.84 vs 2.5) differ only by amounts consistent with `news_total` having been refreshed after the scan (events show `消息面偏空 -1.2(8 則)` messages arriving between scans) | medium-high |
| `rec_code` thresholds: `BUY` at `total ≥ 3.0`, `HOLD` for `-3.0 < total < 3.0`, `SELL` at `≤ -3.0`, `STRONG_BUY`/`STRONG_SELL` at `≥ 5.0` / `≤ -5.0` (approx.) | Aug: 3.0 → `BUY`, 2.5/2.9 → `HOLD`; Oct: -2.8 → `HOLD`, -3.1 → `SELL`, -5.5 → `STRONG_SELL`; AI report text: 4.4 → `買進`, 5.4/5.7/5.8/6.0 → `強力買進`; weekly review names `buy_th=3.0` as a tuned parameter | medium (threshold is a tuned param, `params_version`) |
| `changed = (rec_code != previous scan's rec_code)` | Oct `changed:true` rows = exactly the 5 symbols with a `X:買進→觀望`-style engine event at the `last_scan` time 18:17 (`2454 賣出→觀望`, `2308 賣出→強力賣出`, `2882 買進→觀望`, `0050 觀望→賣出`, `2881 買進→觀望`); the 4 `false` rows have none | high |
| `suggest_qty` is volatility-scaled and capped at ~8 % of `equity` | Oct: `2330`/`2317`/`0050` sit at 7.98 %/8.00 %/8.01 % of equity, the other six at 3.0–7.0 %; Aug (cash 55 760) all rows 0.4–1.4 % | low (formula unknown → Open questions) |

---

## 8. `overview.reward`

Rendered by `renderReward` l.571–596 into `#reward-card` (`index.html:104–109`, title `Reward 記分板`, chip `顯示用`). **Whole object missing/null → card hidden** (`display:none`, l.575). Present → card shown.

| Field | Type | Example | Rendering | Missing |
|---|---|---|---|---|
| `total` | int | `60` | `#reward-total` (`累積分數`) = `String(total ?? 0) + ' 分'` → `60 分` | `0 分` |
| `provisional` | object \| null | `{"month": "2026-10", "ret_pct": -2.91, "points": -29, "settled": false}` | `#reward-month` (`本月暫計`) = `(points>=0?'+':'') + points + ' 分(' + (ret_pct>=0?'+':'') + ret_pct.toFixed(2) + '%)'` → `-29 分(-2.91%)`, class by sign of `points` | null → `—`. **If present, `points` and `ret_pct` must be numbers**: `ret_pct.toFixed` on `undefined` throws and aborts the rest of `refreshOverview` (positions/recs/symbol head not rendered). |
| `provisional.month` | `YYYY-MM` | `"2026-10"` | not read | |
| `provisional.settled` | bool | `false` | not read | |
| `history` | array | see below | `(history \|\| []).filter(h => !h.skipped).slice(0, 3)` → `#reward-history` text `h.month + ':' + (points>=0?'+':'') + points + '分' + (beat_market ? '(勝大盤)' : '')` joined by a space → `2026-09:+35分 2026-08:+25分 2026-07:+0分`; none → `尚無已結算月份` | `尚無已結算月份` |

`history[]` must be **newest-first** (the viewer slices the first three without sorting; observed order `2026-09, 2026-08, 2026-07, 2026-06`). Two item shapes:

Settled month:

| Field | Type | Example (2026-09) | Read by viewer |
|---|---|---|---|
| `month` | `YYYY-MM` | `"2026-09"` | yes |
| `equity_open` | number | `1015475.4` | no |
| `equity_close` | number | `1040392.13` | no |
| `partial` | bool | `false` (`true` for 2026-07) | no |
| `ret_pct` | number 2-dp, percent | `2.45` | no |
| `twii_ret_pct` | number 2-dp, percent | `3.93` | no |
| `base_points` | int | `25` | no |
| `beat_market` | bool | `false` | yes (`(勝大盤)` suffix) |
| `bonus_beat` | int | `0` | no |
| `new_high` | bool | `true` | no |
| `bonus_high` | int | `10` | no |
| `points` | int | `35` | yes |
| `total_after` | int | `60` | no |

Skipped month: `{"month": "2026-06", "skipped": true, "reason": "缺月初或月底權益基準(該月系統未完整運行)"}` — filtered out by the viewer.

**Inferred** scoring (medium-high; all 3 settled months + 2 provisional values fit):

| Rule | Evidence |
|---|---|
| `ret_pct = round((equity_close / equity_open − 1) × 100, 2)` | 2.45, 1.55, 0.0 exact |
| `base_points = round(unrounded_ret_pct × 10)` (1 point per 0.1 %) | 2.4537 % → 25, 1.5475 % → 15, 0 → 0; provisional −2.912 % → −29, 0.88 % → 9 |
| `bonus_high = 10` when `new_high` else 0 | 2 of 3 |
| `points = base_points + bonus_beat + bonus_high`; `total_after` is the running sum; `reward.total == history[0].total_after` | exact |
| `provisional.points = base_points` only (no bonuses); `provisional.ret_pct` measured from the previous month's `equity_close` | −2.91 % = 1 010 098.05 / 1 040 392.13 − 1 |
| `beat_market` is **not** simply `ret_pct > twii_ret_pct` (2026-07: 0.0 vs −6.52 but `false`, a `partial` month with no trades) | → Open questions |

`simple.html` does not render the reward block (the AI report text mentions `月度記分板` from its own data).

---

## 9. `overview.model_health_brief`

Rendered by `renderHealth` l.1419–1425 into `#health-brief` (`index.html:203`, 模型健康 tab) — only when that tab is opened. Missing → `{}`.

| Field | Type | Example | Rendering | Missing |
|---|---|---|---|---|
| `hit_rate_5d` | number, fraction | `0.5439` | `Math.round(x*100) + '%'` → `54%` | `—` |
| `mae_5d` | number, fraction | `0.044109` | `fmtRet` → `+4.4%` (note the `+` sign) | `—` |
| `n_resolved` | int | `3408` | `'已兌現 ' + (n_resolved \|\| 0) + ' 筆'` | `0` |
| `champion` | string | `"baseline"` | not read (health tab uses `model-health.json.metrics.champion`) | |

Full line: `5日 MAE +4.4% ・ 命中率 54% ・ 已兌現 3408 筆`. Observed `champion`: `baseline` (Oct), `ridge` (Aug) — same vocabulary as `forecast5.model`.

---

## 10. `overview.disclaimer`

| Field | Type | Value (verbatim, both snapshots) | Rendering |
|---|---|---|---|
| `disclaimer` | string | `本工具僅為技術分析參考,非投資建議;所有訊號與預測由公式機械式計算,必有誤差且會失準,下單請自行判斷風險。資料來源 Yahoo Finance,可能延遲 15–20 分鐘。` | `#disclaimer` footer (`index.html:293`) `textContent = disclaimer \|\| <existing text>` (l.360); missing/empty keeps the HTML default `本工具僅為技術分析參考,非投資建議。` |

`simple.html:107` footer repeats the same sentence after `本頁為唯讀快照,由程式自動產生(含 AI 生成之解讀文字,可能有誤).所有交易皆為紙上模擬、非真實資金。<br>`.

---

## 11. `ai_report`

Loaded by `loadAiReport` l.1315–1321 (keeps the previous report on failure), rendered by `renderAiReport` l.1323–1341 into the collapsible card `#ai-report-card` (`index.html:118–130`, title `🤖 AI 收盤日報`, tooltip `收盤後由 AI 產生的當日總結,僅供參考,非投資建議`).

| Field | Type | Example | Rendering | Missing |
|---|---|---|---|---|
| `ai` | object | `{"enabled": true, "model_fast": "sonnet", "model_deep": "opus"}` | not read (duplicate of `engine.ai`) | tolerated |
| `date` | `YYYY-MM-DD` | `"2026-10-12"` | `#ai-report-date` chip text, unhidden when truthy (l.1328–1333) | chip hidden |
| `generated_at` | iso string | `"2026-10-12T14:16:54+08:00"` | `#ai-report-meta` = `'產生於 ' + fmtDateTime(generated_at)` → `產生於 2026-10-12 14:16` | `產生於 —` |
| `content` | markdown string | `"## 大盤與市場氛圍\n\n加權指數收 49,301.96(-0.02%),…"` | `#ai-report-content.innerHTML = mdToHtml(content)` | falsy → meta cleared, body `收盤後自動產生` |
| `weekly_review` | object | `{"week": "2026-W31", "generated_at": "2026-08-01T09:30:20+08:00", "text": "# 台股紙上交易系統 — 週檢討(截至 2026-08-01)\n\n…"}` | **not read by app.js or simple.html** (grep: none) | tolerated |

Note the report is stale on purpose: `date` is the last **successful** report (2026-10-12) even though the snapshot is 2026-10-31; the viewer shows the date chip so the staleness is visible. `weekly_review` was identical (W31) in both snapshots.

`mdToHtml` (l.1346–1373) supports exactly: lines `#`–`####` + space → `<div class="ai-md-hN">`; lines starting `- ` → `<ul><li>`; `**bold**` → `<strong>`; blank line = paragraph break; consecutive other lines → one `<p>` joined with `<br>`. Everything is HTML-escaped first; markdown tables and `1.` numbered lists therefore render as plain text lines. The observed `content` uses `## ` headings (`大盤與市場氛圍`, `觀察清單重點`, `持倉與損益`, `模型健康`, `明日留意`), `- **code name** — …` bullets, a pipe table and a `1.`/`2.`/`3.` list.

`simple.html:68–107` renders the same `content` server-side with a different converter: `## ` → `<h4>`, `- ` → `<ul><li>`, `**` → `<strong>`, every other non-blank line → its own `<p>` (table rows and numbered items become `<p>` lines); meta line `2026-10-12 產生於 14:16` (= `date` + ` 產生於 ` + `HH:MM` of `generated_at`).

---

## 12. `simple.html` as a secondary consumer (engine-rendered)

`simple.html` is generated by the engine from the same data (it is static HTML; `<meta http-equiv='refresh' content='300'>`, title `tw-quant 家用唯讀快照`, linked from the banner as `精簡版`). Observed field → text mapping, for parity:

| Section | Text pattern | Source fields / format |
|---|---|---|
| header | `tw-quant 台股監控 <badge>唯讀快照</badge><badge>紙上交易(虛擬資金)</badge>` | static |
| meta | `產生時間 2026-10-31 14:15(台北時間).本頁每次掃描後自動更新;瀏覽器每 5 分鐘自動重新整理。` | `generated_at` → `YYYY-MM-DD HH:MM` |
| market | `加權指數 <span class='down'>45,212(-2.49%)</span>.大盤環境:偏空震盪` | `market.index` 0 dp thousands; `market.pct` signed 2 dp; class by sign; `market.regime_label` |
| `觀察清單與 AI 解讀` table | `代碼/名稱 \| 價格 \| 漲跌% \| 評分 \| 建議` rows `2881 富邦金 \| 161.50 \| -0.31% \| +2.9 \| 觀望` | rows sorted by `total` desc; price **always 2 dp with thousands** (`2,370.00`); pct signed 2 dp, class `up/down/flat` (`+0.00%` → `flat`); total signed 1 dp; `rec_text` in `<span class='rec hold|buy|sell'>` |
| AI notes | `🤖 2881 富邦金 AI 解讀 14:18` + raw text | one block per row with `ai_note`, same order as the table |
| `紙上帳戶(虛擬 100 萬起步)` | `權益 <b>1,010,098</b> 元(<span class='up'>+1.01%</span>).現金 269,730.已實現 -23,214.未實現 +33,315` | `account.*`; pct = `(equity/initial_cash−1)×100` |
| positions table | see §6 | `positions[]` in array order |
| exit legend | `賣出主要由出場機制執行:跌破停損價(-8%)或從高點回落至移停價(-12%)時狀態轉「該賣」,自動交易開啟時會自動出場。` | static |
| `AI 收盤日報` | `2026-10-12 產生於 14:16` + converted markdown | `ai_report.date`, `generated_at`, `content` |
| footer | `本頁為唯讀快照,由程式自動產生(含 AI 生成之解讀文字,可能有誤).所有交易皆為紙上模擬、非真實資金。<br>` + `overview.disclaimer` | |

---

## 13. Missing/null tolerance summary

| Must be present and well-typed | Why |
|---|---|
| `overview` object | otherwise the viewer shows a red dot and renders nothing |
| `rows[].symbol`, `positions[].symbol` (strings) | used as keys/selectors; `a.symbol.localeCompare` in the sort would throw on `undefined` when two rows tie |
| `reward.provisional.points` and `.ret_pct` numeric **whenever `provisional` is non-null** | `ret_pct.toFixed(2)` throws otherwise and aborts the render cycle |
| `reward.history[].month`, `.points` (when not `skipped`) | printed raw (`undefined` otherwise, no crash) |
| `rows[].tech_total`, `mkt_score`, `fund_total` | printed raw into a tooltip (`undefined` otherwise, no crash) |

Everything else degrades to `—`, `+0.0`, a hidden chip, or an empty-state string as listed in each table.

---

## 14. Open questions (with proposed defaults for the rebuild)

1. **`market.label` vocabulary.** Only `收盤` observed. Proposed: `盤中` when `is_open` (the app.js fallback), `收盤` otherwise; keep `label` and `is_open` consistent.
2. **`market.regime_label` / `score` vocabulary.** Observed `偏多震盪`/`+0.5`, `偏空震盪`/`-0.5`. AI texts mention a `多頭`/`空頭` market environment and the events log a `市場狀態:halt(大盤單日 -2.5%、5日 -3.6%)` gate. Proposed set: `多頭 +1.0`, `偏多震盪 +0.5`, `盤整 0.0`, `偏空震盪 -0.5`, `空頭 -1.0`; `rows[].mkt_score = market.score`.
3. **`engine.last_scan_kind` vocabulary.** Only `啟動` observed. Proposed: `啟動` (startup scan), `盤中` (periodic intraday), `收盤定盤` (post-close fixing scan ~13:33), `EOD` (14:15 end-of-day); keep strings short since they are shown in parentheses after the clock.
4. **`engine.health.red` thresholds and strings.** Observed `AI 日報 {n} 天未產生` with n = 19 red; `share_days = 1` not red. Proposed: red when `ai_days ≥ 2` → `AI 日報 {ai_days} 天未產生`; red when `share_days ≥ 2` → `分享頁 {share_days} 天未更新` (string is a guess); `configured` = heartbeat URL set; `ai_hard_failure` = last error was non-transient.
5. **`positions[].verdict` non-hold value and `reasons[]` strings.** Only `hold`/`[]` observed. Proposed: `exit` (CSS class is `verdict-exit`, badge `該賣`) with reasons such as `跌破停損價 226.17`, `回落至移停價 216.48`, `建議轉賣出` (the three triggers named at app.js:1934).
6. **`rows[].kd60.label` full set and score mapping.** Observed `中性`→0.0, `低檔`→+0.3, `低檔黃金交叉`→+0.5. Proposed symmetric: `高檔`→−0.3, `高檔死亡交叉`→−0.5, `黃金交叉`→+0.3, `死亡交叉`→−0.3 (low/high = both K and D < 20 / > 80).
7. **`rec_code` thresholds** are tuned parameters (`buy_th`); exact `STRONG_*` cut-offs unobserved between 4.6 and 5.4 (and −2.8/−5.5). Proposed defaults: `BUY ≥ 3.0`, `STRONG_BUY ≥ 5.0`, `SELL ≤ −3.0`, `STRONG_SELL ≤ −5.0`, else `HOLD`.
8. **`suggest_qty` formula.** Evidence only shows an ~8 %-of-equity cap and volatility scaling. Proposed: `min(floor(0.08 × equity / price), floor(risk_budget / (price × ci68_width)))` — to be settled by the sizing spec.
9. **`total` vs. components after asynchronous news refresh.** Aug shows `news_total` refreshed without recomputing `total`. Proposed: recompute `total`/`rec_code` only at scan time, but write `news_total`/`chips_total` whenever refreshed (reproduces the observed behaviour).
10. **`account.realized_pnl`/`unrealized_pnl` vs `equity − initial_cash`** differ by a few NTD (2.99 Oct, 9.13 Aug). Proposed: `unrealized = Σ qty×(price−avg_price)`, `realized` = Σ closed-trade PnL net of fees/tax per the broker ledger; do not force the identity.
11. **`reward.beat_market` rule** (false for 2026-07 despite 0.0 % > −6.52 %). Proposed: `beat_market = (not partial) and ret_pct > twii_ret_pct`; `bonus_beat = 10` when true (value unobserved).
12. **`quote_fresh` semantics.** Always `false` in the two Saturday snapshots; the event `收盤定盤掃描完成:…9 檔取得交易所定盤價` suggests `true` when the price is an exchange fixing/real-time quote rather than a delayed Yahoo quote. Proposed: `true` iff the quote came from the exchange source and is younger than the scan interval.
13. **`ai_report.weekly_review`** is never rendered. Proposed: keep emitting `{week, generated_at, text}` for forward compatibility; may be `null`.
14. **`overview.ts`** is unused; proposed: keep `= generated_at`.
