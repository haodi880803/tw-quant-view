# 02 — `symbol/<code>.json` output contract

Status: reverse-engineered from the last baked snapshot (2026-10-31 14:15 Taipei) and from the viewer code. Everything the viewer *reads* is a hard requirement; everything else is documented so the rebuilt engine reproduces the same shapes and values.

Evidence base (all read-only):

| Source | What it told us |
|---|---|
| `app.js` (2082 lines, IIFE) | which keys the chart / chips / tabs read, how they are rendered, what happens when a key is missing |
| `index.html` | DOM ids / tab labels the renderer writes into |
| `symbol/{0050,2308,2317,2330,2454,2881,2882,3481,6789}.json` (9 files, 83–92 KB each) | exact shapes, value ranges, label strings; numeric formulas were re-derived with pandas and matched against all 9 files |
| `data.json` | cross-checks (`rows[].price`, `rows[].pct`, `rows[].forecast5`, `rows[].kd60`, `rows[].news_total`, `rows[].chips_total`, `rows[].ai_note`, `rows[].regime`) |
| `model-health.json`, `events.json` | ledger totals and generation hints (`EOD 完成:更新 9 檔資料,記錄 54 筆預測,兌現 54 筆。`) |

Confidence tags used below: **high** (exact numeric reproduction on all 9 files, or read directly from `app.js`), **medium** (consistent with all data but not uniquely determined), **low** (plausible guess).

---

## 1. File naming, symbol conventions, serialization

| Item | Rule | Evidence / confidence |
|---|---|---|
| File path | `symbol/<bare code>.json`, e.g. `symbol/2330.json`, `symbol/0050.json` (leading zeros kept). | `app.js:230-236`: `/api/symbol/2330.TW?bars=250` → `code = raw.replace(/\.(TW\|TWO)$/i, '')` → `symbol/<code>.json`. Query params are ignored; the file is baked once with `bars=250`. **high** |
| `symbol` field | Full yfinance-style ticker, `"<code>.TW"` for TWSE listings (all 9 files). `.TWO` (OTC) is also accepted by the viewer's regex. | **high** |
| `code` field | Bare code string `"2330"`, `"0050"`. | **high** |
| `name` field | Chinese short name: `"台積電"`, `"元大台灣50"`, `"富邦金"`, `"采鈺"` … | **high** |
| Must equal overview | `symbol` **must be byte-identical** to `data.json → overview.rows[].symbol` (e.g. `"2330.TW"`). `app.js:809`: `if (r.data.symbol !== S.selected) return;` — a mismatch silently discards the whole detail payload (no chart, no tabs). | **high** |
| Serialization | Python `json.dump(obj, f, ensure_ascii=False)` with default separators (`", "` and `": "`), no indent, no trailing newline, raw UTF-8 Chinese (no `\uXXXX`), no `NaN`/`Infinity` literals (none present in any file; the viewer's `res.json()` would throw on them). Key order as listed in §2. | observed bytes `{"symbol": "2330.TW", "code": "2330", "name": "台積電", "bars": [[...` **high** |
| Size | 83–92 KB per file with 250 bars + 11×250 indicator floats at full `repr` precision. | observed |
| Refresh cadence consumed | Viewer re-fetches the selected symbol file every 300 s (`app.js:2061-2064`) with a cache-busting `?t=` query (`app.js:178`). | **high** |

Floating-point note: prices are emitted at full float64 `repr` precision, including float32 artefacts inherited from the data source (`104.94999694824219` for 104.95, `42.54999923706055` for 42.55). The viewer formats with `fmtPrice` (`app.js:84-90`: ≥1000 → 0 dp with thousands separator, ≥100 → 1 dp, else 2 dp) so this is invisible to users. Do **not** round in the engine if byte-level fidelity with `data.json → rows[].price` matters (they are identical floats today, see §3.4).

---

## 2. Top-level schema (key order as emitted)

| Key | Type | Required by viewer? | Section |
|---|---|---|---|
| `symbol` | string `"2330.TW"` | **yes** (identity check, `app.js:809`) | §1 |
| `code` | string `"2330"` | yes (title, `app.js:692`) | §1 |
| `name` | string | yes (title, `app.js:693`) | §1 |
| `bars` | `[[date, open, high, low, close, volume], …]` × 250 | **yes** (chart) | §3 |
| `indicators` | `{ma5, ma20, ma60, bb_up, bb_low, rsi, macd, macd_sig, macd_hist, k, d}` each `float[250]` | optional, degrades | §4 |
| `signals` | `[{indicator, label, score, note}, …]` | optional | §5 |
| `fund_signals` | `[{indicator, label, score, note}, …]` | optional | §5 |
| `news` | `{score, items[]}` | optional | §6 |
| `chips` | `{score, signals[], recent[]}` | optional | §7 |
| `intraday_kd` | `{score, k, d, label, note}` | optional | §8 |
| `trend` | `{segments[], summary{}}` | optional | §9 |
| `forecast` | `{made_date, model, base_price, horizons[], fan{}}` | optional | §10 |
| `ledger` | `{by_horizon[]}` | **not read by the viewer** | §11 |
| `ai_note` | `{ts, rec_code, text}` | optional | §12 |

All 9 files contain all 14 keys. No key is ever `null` at top level in the snapshot.

---

## 3. `bars[]`

### 3.1 Row layout (**high**)

Each row is a 6-element JSON array (verified: every row in all 9 files has exactly 6 elements, types `[str, float, float, float, float, int]`, no `null`):

| Index | Meaning | Type / format | Viewer use |
|---|---|---|---|
| 0 | trading date | `"YYYY-MM-DD"` (ISO date, Taipei calendar day, no time) | category x-axis (`app.js:852`), tooltip header, regime shading bounds, fan alignment |
| 1 | open | float, adjusted price (§3.3) | candlestick `[open, close, low, high]` (`app.js:853`), volume bar colour (`b[4] >= b[1]` → red `UP_A`, else green `DOWN_A`, `app.js:856`), tooltip `開` |
| 2 | high | float | candlestick, tooltip `高` |
| 3 | low | float | candlestick, tooltip `低` |
| 4 | close | float | candlestick, `lastClose()` (`app.js:787-790`), `lastPct()` (`app.js:792-796`), tooltip `收` with day change `(fmtPct)`, |
| 5 | volume | **int, shares** (not 張) | volume bar (`app.js:854-857`), tooltip `量` via `fmtVol` (`≥1e8 → x.x億`, `≥1e4 → x萬`, else integer; `app.js:113-118`) |

Cross-check that index 1/4 are open/close (not close/open): `data.json → rows[].price` equals `bars[-1][4]` byte-for-byte in all 9 files (e.g. 2330 `2370.0`, 0050 `104.94999694824219`, 3481 `42.54999923706055`), and `rows[].pct` equals `round((bars[-1][4]/bars[-2][4] - 1)*100, 2)` (2330: −1.86, 0050: −2.14, 3481: −7.50). OHLC consistency (`high ≥ max(open,close)`, `low ≤ min(open,close)`) holds for all 2 250 rows.

### 3.2 Length, ordering, calendar (**high**)

* Exactly **250** rows in every file (`?bars=250`). Oldest first; strictly increasing dates; no weekend dates. Snapshot window: `2025-10-17` … `2026-10-30` (Friday; the bake ran Saturday 2026-10-31 14:15, so the last bar is the last *completed* session).
* The window is the last 250 bars of a longer cached history — the engine keeps more than 250 bars (needed for §4 warm-up and §9 `*_252`). `events.json` shows the data layer caches daily bars per symbol and refuses regressions: `[data] 0050.TW 本次最新日期 2026-10-29 落後快取 2026-10-30(疑似劣化回應),保留舊快取`.

### 3.3 Price adjustment (**high** that prices are back-adjusted; **medium** that the mechanism is yfinance `auto_adjust=True`)

Older bars are not tick-aligned: 2330 `2025-10-17` open `1437.3731424265895`; 2881 `86.56273651123047`. For each symbol there is a cut-over date after which all OHLC values are clean ticks (float32-noise only):

| code | last non-tick bar | plausible cause |
|---|---|---|
| 2330 | 2026-09-15 | quarterly cash dividend ex-date (mid-Sep) |
| 0050 | 2026-07-20 | semi-annual ETF distribution |
| 2308 | 2026-06-16 | annual dividend |
| 2317 | 2026-07-01 | annual dividend |
| 2454 | 2026-07-06 | dividend |
| 2881 / 2882 | 2026-06-30 / 2026-06-29 | dividend |
| 3481 / 6789 | 2026-06-10 / 2026-06-25 | dividend |

i.e. the series is **dividend/split back-adjusted** (everything before an ex-date is rescaled). Consequence: after every ex-dividend date the whole `bars[]` history shifts, and `indicators`, `trend`, `forecast.horizons.ci*` are computed on adjusted closes. The last bar's close equals the unadjusted market close, which is why `rows[].price` matches exactly.

### 3.4 Precision per symbol — does 0050 differ? (**high**)

No. 0050 and 3481 simply trade on a 0.05 tick, and 0.05-multiples are not exactly representable in float32, so they show `…99694824219` noise after the data source's float32→float64 conversion; integer-tick symbols (2330, 2454, 2308) look clean. Volume is a plain integer for every symbol (0050 volumes 38 785 824 … 493 890 200 shares; the viewer prints `2.3億`).

---

## 4. `indicators{}`

### 4.1 Shape (**high**)

| Key | Length | Nulls | Alignment |
|---|---|---|---|
| `ma5`, `ma20`, `ma60`, `bb_up`, `bb_low`, `rsi`, `macd`, `macd_sig`, `macd_hist`, `k`, `d` | 250 each (== `len(bars)`) | **none** — `leadingNulls=0`, no `null`, no `NaN` in any of the 99 arrays | `indicators.X[i]` belongs to `bars[i]` (same index; the chart puts both on the same category axis, `app.js:924-1008`, tooltip `app.js:1120-1133`) |

Because `ma60[0]` and MACD(26) are already populated at index 0, the engine computes indicators over the longer cached history and slices the last 250 values. Warm-up `NaN`s must never reach the JSON: slice **after** computing. (The viewer would tolerate `null` — ECharts gaps, `connectNulls:false`, tooltip rows skipped via `iv()` — but `NaN` is not valid JSON.)

### 4.2 Formulas (re-derived; max abs error vs. the published arrays over all 9 symbols)

| Key | Formula (pandas) | Max abs error | Confidence |
|---|---|---|---|
| `ma5` / `ma20` / `ma60` | `close.rolling(n).mean()` | 0 | **high** |
| `bb_up` / `bb_low` | `ma20 ± 2 * close.rolling(20).std(ddof=1)` (pandas default ddof) | 2e-11 (ddof=0 is off by up to 21.5) | **high** |
| `rsi` | **Cutler/SMA RSI(14)**: `d=close.diff(); up=d.clip(lower=0); dn=-d.clip(upper=0); rsi = 100 - 100/(1 + up.rolling(14).mean()/dn.rolling(14).mean())` | 0.0 over the full 250-bar window (5 symbols re-checked) and over the last 60 bars (all 9) | **high** (Wilder EMA variants are off by 12–24 points) |
| `macd` | `close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()` | ≤4e-5 (residual = warm-up start difference; `adjust=True` is 10× worse) | **high** |
| `macd_sig` | `macd.ewm(span=9, adjust=False).mean()` | ≤6e-5 | **high** |
| `macd_hist` | `macd - macd_sig` (**not** ×2) | ≤2e-5 | **high** |
| `k` | Taiwan KD(9,3,3): `rsv = (close - low.rolling(9).min()) / (high.rolling(9).max() - low.rolling(9).min()) * 100`; `k = rsv.ewm(alpha=1/3, adjust=False).mean()` (equivalently `k = 2/3·k_prev + 1/3·rsv`) | 0 | **high** (SMA-stochastic variants off by 15–30) |
| `d` | `d = k.ewm(alpha=1/3, adjust=False).mean()` | 0 | **high** |

Edge cases observed: `rsi` hits exactly `50.0` when 14-day mean gain == mean loss (0050 `2025-12-17`, 2308 `2026-05-15/18`, …) — this is genuine, not a fill value; no `100.0`/`0.0` values occur in the window but the engine must guard `dn==0 → 100`. Values are emitted unrounded (`66.97674166008935`).

---

## 5. `signals[]` (technical) and `fund_signals[]` (fundamental)

### 5.1 Item schema (**high**)

```
{"indicator": "<group label>", "label": "<state label>", "score": <float>, "note": "<explanation>"}
```

Rendering (`app.js:728-757`): one `<span class="sig-chip {up|down|flat}">` per item, text = `indicator + ' ' + label`, hover title = `note + '(分數 ' + score + ')'`; `fund_signals` get the extra class `fund` (dashed border). Colour class from `clsOf(score)` (`>0` red/up, `<0` green/down, `0` flat). Missing array → treated as `[]`. Order of chips = array order. The viewer never computes totals from these — `tech_total`/`fund_total` live in `data.json → rows[]`.

### 5.2 Technical `signals[]` — observed vocabulary (verbatim)

Emission order in every file: `均線排列`, `RSI`, `MACD`, then optionally `KD`, `布林通道`, `成交量`.

| `indicator` | `label` | `score` | `note` (verbatim) | Trigger (inferred from §4 values, **high** unless noted) |
|---|---|---|---|---|
| `均線排列` | `多頭排列` | `3.0` | `MA5>MA20>MA60,趨勢偏多` | `ma5[-1] > ma20[-1] > ma60[-1]` (2881, 2882) |
| `均線排列` | `空頭排列` | `-3.0` | `MA5<MA20<MA60,趨勢偏空` | `ma5 < ma20 < ma60` (2308) |
| `均線排列` | `糾結` | `0.0` | `均線糾結,方向不明` | otherwise (always emitted) |
| `RSI` | `超賣` | `0.75` | `RSI=20<30,跌深可能反彈` (`RSI=` + `round(rsi)` + `<30,…`) | `rsi[-1] < 30` |
| `RSI` | `中性` | `0.0` | `RSI=44` (`'RSI=%d' % round(rsi)`) | `30 ≤ rsi ≤ 70` (always emitted) |
| `RSI` | `超買` | `-0.75`? | `RSI=xx>70,…`? | `rsi > 70` — **not observed**, label/note text unknown (**low**) |
| `MACD` | `紅柱` | `0.5` | `柱狀體在零軸上,動能偏多` | `macd_hist[-1] >= 0` (2317 at +0.41, 2882 at +0.09) |
| `MACD` | `綠柱` | `-0.5` | `柱狀體在零軸下,動能偏空` | `macd_hist[-1] < 0` (2881 at −0.09) |
| `KD` | `死亡交叉` | `-0.75` | `K=9 下穿 D=10` (`'K=%d 下穿 D=%d' % (round(k), round(d))`) | `k_prev ≥ d_prev and k < d` (2308: 12.84/11.08 → 8.56/10.24; 6789: 39.73/36.63 → 27.50/33.59). Takes precedence over the zone rule (2308 has k=8.6<20 but shows the cross) |
| `KD` | `黃金交叉` | `+0.75`? | `K=.. 上穿 D=..`? | `k_prev ≤ d_prev and k > d` — **not observed** (**medium**, by symmetry) |
| `KD` | `低檔` | `0.5` | `K=18<20,低檔區` | `k[-1] < 20` and no cross (3481) |
| `KD` | `高檔` | `-0.5`? | `K=..>80,高檔區`? | `k > 80` — **not observed** (**low**) |
| (no `KD` chip) | | | | `20 ≤ k ≤ 80` and no cross (0050 k=21.9, 2330 k=22.6, 2454 k=21.8 emit nothing) |
| `布林通道` | `觸下軌` | `0.62` | `跌破下軌,偏弱但可能超跌反彈` | `close[-1] < bb_low[-1]` (3481: 42.55 < 43.40; 2308 at 1335 > 1326.55 emits nothing). `0.62` is `round(0.625, 2)` under Python banker's rounding — i.e. a base weight × 1.25 (**medium**) |
| `布林通道` | `觸上軌`? | `-0.62`? | ? | `close > bb_up` — **not observed** (**low**) |
| `成交量` | `帶量下跌` | `-1.5` | `量為均量 2.0 倍,量增價跌` (`'量為均量 %.1f 倍,量增價跌'`) | volume ratio ≥ threshold **and** close < prev close (0050 ratio 2.0, 2308 2.1, 2454 1.7; 2330 at 1.2 and 6789 at 1.1 emit nothing → threshold in (1.25, 1.7]). **The ratio does not reproduce from `bars[]`** — see Open questions |
| `成交量` | `帶量上漲`? | `+1.5`? | `量為均量 x.x 倍,量增價漲`? | **not observed** (**medium**) |

### 5.3 Fundamental `fund_signals[]` — observed vocabulary (verbatim)

Emission order: `ROE`, `營收成長`, `盈餘成長`, `毛利率`, `本益比` (only the ones that fire). If none fires (ETF 0050): a single placeholder item.

| `indicator` | `label` format | `score` | `note` (verbatim) | Observed values → inferred threshold |
|---|---|---|---|---|
| `ROE` | `"%d%%"` (`42%`) | `0.7` | `股東權益報酬率高,獲利能力強` | 24%, 25%, 26%, 29%, 42% |
| `ROE` | `13%` | `0.3` | `ROE 尚可` | 13% → threshold for 0.7 somewhere in (13%, 24%] (**medium**: 15% or 20%) |
| `營收成長` | `51%` | `0.7` | `營收年增率高,成長強` | 31%, 41%, 51% |
| `營收成長` | `10%` | `0.3` | `營收正成長` | 1%, 10%, 13% → 0.7 threshold in (13%, 31%] (**medium**: 20%) |
| `營收成長` | `-25%` | `-0.5` | `營收衰退` | −25%, −62% |
| `盈餘成長` | `69%` | `0.4` | `獲利成長` | 26%, 34%, 68%, 69% |
| `盈餘成長` | `-13%` | `-0.4` | `獲利衰退` | −13% |
| `毛利率` | `51%` | `0.3` | `高毛利,具競爭力` | 26%, 28%, 51%; 2317 (≈6%) and 2454 (≈46%?) absent → see open questions |
| `本益比` | `"%d"` (`65`, no `%`) | `-0.3` | `本益比偏高,評價偏貴` | 55, 65, 78; 2330/2881/2882 absent → threshold in (≈30, 55] (**medium**: 50) |
| `基本面` | `中性` | `0.0` | `基本面無明顯偏多或偏空訊號` | placeholder when nothing else fires (0050) |

Percent labels are `round()`ed integers of the ratio×100 (yfinance `returnOnEquity`, `revenueGrowth`, `earningsGrowth`, `grossMargins`, `trailingPE` are the obvious sources — **medium**).

---

## 6. `news{}`

### 6.1 Shape (**high**)

```
"news": {"score": -1.34, "items": [ {"title": "...", "link": "https://news.google.com/rss/articles/...?oc=5",
          "source": "工商時報", "published": "2026-10-30T10:04:00+08:00", "sentiment": "neg", "score": -2.0}, ... ]}
```

| Field | Type / format | Observed | Viewer (`app.js:1228-1269`) |
|---|---|---|---|
| `score` | float, 2 dp | 0.17, −1.34, 0.0, 0.5, −0.33, 0.42, −0.83, −1.07, −0.37 | header chip `消息面評分 ` + `fmtTilt` (`+0.5`, `-1.34`→`-1.3`: `fmtTilt` prints **one** decimal, `app.js:145-148`), class `up`/`down`; also the `消息 ±x.x` chip above the chart (`app.js:737-741`, but `rows[].news_total` wins when present). Non-number → 0 |
| `items` | array, ≤ 8 (6 for 6789) | 70 items total | rendered in array order (not re-sorted; array is **not** time-ordered in the snapshot) |
| `items[].title` | string | Chinese headline | HTML-escaped |
| `items[].link` | string | always a Google News RSS redirect URL | rendered as `<a target=_blank rel=noopener>` only if it matches `^https?://`; otherwise plain text |
| `items[].source` | string | `Yahoo股市`, `ETtoday財經雲`, `CMoney`, `工商時報`, `鉅亨網`, … (publisher name from the RSS `<source>`) | shown dim |
| `items[].published` | ISO 8601 with offset `+08:00`, seconds precision | `2026-10-30T12:37:47+08:00` | `fmtNewsTime` → browser-local `MM-DD HH:mm` (`app.js:150-156`); must carry an offset or the browser treats it as local |
| `items[].sentiment` | enum **`"pos" \| "neg" \| "neu"`** | neu 48, neg 14, pos 8 | badge `利多` (red) / `利空` (green) / `中性` (grey) via `NEWS_BADGE` (`app.js:1222-1226`); unknown value → fallback by sign of `items[].score` |
| `items[].score` | float | only integers −3, −2, −1, 0, 1, 2 observed; mapping is exact: score>0 ⇔ `pos`, <0 ⇔ `neg`, 0 ⇔ `neu` | row title `情緒分數 +1.0` when ≠ 0 |

Missing `news` key → header shows `消息面評分 +0.0` and `暫無相關新聞或尚未載入`.

### 6.2 Semantics (inferred)

* Items come from a Google News RSS search per symbol (all links are `news.google.com/rss/articles/…`), capped at 8 (**high** on source, **medium** on cap).
* Item scores are "標題級情緒計分(AI 語意為主,詞典備援)" (`app.js:741`). During this snapshot the AI path was down (`events.json`: `[news] AI 連續失敗 3 次,暫停 AI 呼叫 15 分鐘(期間自動改用非 AI 路徑)` repeated through 2026-10-30 18:17), so the integer scores are the **lexicon fallback** output.
* `news.score` is **not** the plain mean of item scores (0050: items sum 1 over 8 → 0.17; 6789: items sum +1 but score −0.37). A recency-weighted/decayed aggregate is implied; no simple exponential-decay/normalisation hypothesis fit all 9 files. See Open questions. The viewer does not care how it is computed.

---

## 7. `chips{}` (三大法人買賣超, TWSE T86)

### 7.1 Shape (**high**)

```
"chips": {"score": -1.5,
          "signals": [{"indicator": "外資動向", "label": "外資連賣16日", "score": -1.5, "note": "外資連續 16 個交易日賣超"}, ...],
          "recent":  [{"date": "2026-10-30", "foreign": -97979941, "invtrust": 2609000, "dealer": -67364227, "total": -162735168}, ...]}
```

| Field | Rule | Viewer (`app.js:1272-1312`) |
|---|---|---|
| `score` | float, 1 dp; **equals the sum of `signals[].score`** (0050: −1.5+0.5−0.5 = −1.5; 2330: −1.5+0.5 = −1.0; no signals → 0.0) | `籌碼面評分 ` + `fmtTilt(score)`; also the `籌碼 ±x.x` chip above the chart (`app.js:742-746`, `rows[].chips_total` wins) |
| `signals[]` | same item schema as §5.1 | chips with class `sig-chip chips` |
| `recent[]` | **10 rows, newest first**, one per trading day (`2026-10-30` … `2026-10-15`) | re-sorted descending by `date` string, so order is not load-bearing |
| `recent[].date` | `"YYYY-MM-DD"` (viewer also accepts `"YYYYMMDD"`, `app.js:158-162`) | first column |
| `recent[].foreign` / `invtrust` / `dealer` / `total` | **int, net shares** (buy − sell). `total == foreign + invtrust + dealer` holds for all 90 rows. | each cell `Math.round(v/1000)` → 張, signed with thousands separators (`+2,609`), red/green by sign; `null` → `—` |

Missing `chips` key, or empty `recent` → `暫無籌碼資料(上櫃股票或資料尚未回填)` (OTC `.TWO` symbols have no T86 data).

### 7.2 Observed `signals[]` vocabulary (verbatim)

| `indicator` | `label` | `score` | `note` | Inferred rule |
|---|---|---|---|---|
| `外資動向` | `外資連賣16日` | `-1.5` | `外資連續 16 個交易日賣超` | consecutive-day streak of `foreign < 0`; 16 > 10 rows ⇒ the engine keeps ≥ 60 days of T86 history. −1.5 is probably a cap (0050, 2330, 2454 all 16 days → −1.5). Streaks of 1–2 days (2317, 2881, 2882, 3481, 6789) emit nothing; `ai_note` texts mention `外資連買五日` and `外資連賣三日`, so the threshold is ≤ 3 days and the buy-side label is `外資連買N日` (**medium**) |
| `投信動向` | `投信買超` | `0.5` | `近 5 日投信買賣超同向(無反向日)` | `invtrust > 0` on all of the last 5 rows (0050, 2330, 2454 ✓; 2317 has one negative day → nothing). Sell-side presumably `投信賣超` / `-0.5` (**medium**) |
| `法人動能` | `法人賣壓動能` | `-0.5` | `近 3 日三大法人合計 z 分數 -1.08(相對近 60 日)` (`'%.2f'`) | z-score of the last-3-day `total` vs. the last 60 days, fires when z ≤ −1 (observed −1.02, −1.08, −2.06); 2317/2881/2882 (|z|<1) emit nothing. Buy-side label presumably `法人買盤動能` / `+0.5` at z ≥ +1 (**medium**) |

---

## 8. `intraday_kd{}` (60-minute KD)

```
"intraday_kd": {"score": 0.0, "k": 26.6, "d": 27.2, "label": "中性", "note": "60分K線 K=27 D=27"}
```

| Field | Rule | Evidence |
|---|---|---|
| `k`, `d` | floats rounded to **1 dp**, KD computed on 60-minute bars (same 9/3/3 recursion as §4 presumed, **medium**) | 20.5, 27.1, 4.3, 11.1 … |
| `note` | `'60分K線 K=%.0f D=%.0f'` on the raw values (26.6→27, 20.5→20 shows half-even/`%.0f` rounding of the unrounded value) | all 9 |
| `label` / `score` | `中性` / `0.0` (6 symbols); `低檔` / `0.3` (2308: k=4.3, d=11.1); `低檔黃金交叉` / `0.5` (3481: k=16.0 > d=15.3, both < 20) | high-side labels not observed; by symmetry `高檔` / `-0.3`, `高檔死亡交叉` / `-0.5` (**low**) |
| `data.json` twin | `rows[].kd60 = {k, d, label, note}` (**without** `score`) and `rows[].kd60_total = score` | identical values |

Viewer (`app.js:747-756`): chip `60分KD <label>` + ` ±x.x` only when the tilt ≠ 0; title = `note` + `;短線輔助(未回測,僅小幅 tilt)`. `rows[].kd60` (overview) takes precedence; if both are absent the chip is omitted. Missing `label` → `中性`, missing `note` → `60分K線 KD`.

---

## 9. `trend{}`

### 9.1 `segments[]` (**high** — algorithm below reproduces all 9 files exactly)

```
{"start": "2025-10-17", "end": "2025-11-10", "regime": "bull", "ret": 0.021}
```

| Field | Rule |
|---|---|
| `start`, `end` | `"YYYY-MM-DD"`, inclusive, both are `bars[]` dates. Segments tile the 250-bar window exactly: first `start` == `bars[0][0]`, last `end` == `bars[-1][0]`, `segments[i+1].start` is the **next trading day** after `segments[i].end`. |
| `regime` | enum **`"bull" \| "bear" \| "range"`** (viewer `REGIME` map `app.js:31-35`: `多頭` / `空頭` / `盤整`) |
| `ret` | `round(close[end] / close[start] - 1, 4)` (fraction, 4 dp). Verified on every segment of every file. |

Algorithm (daily label → run-length smoothing), reproduced exactly on 9/9 symbols (7–16 segments each):

1. Daily raw label for bar *i*: `bull` if `close[i] > ma20[i] > ma60[i]`; `bear` if `close[i] < ma20[i] < ma60[i]`; else `range`.
2. Single left-to-right pass: split into runs of equal raw label; a run **shorter than 5 bars** adopts the label of the bar immediately before it (which may itself have been relabelled); the first run is kept as is. Runs ≥ 5 bars always start a new segment. (Other variants — merge-shortest-first, merge-into-next, min length 4 or 6 — fail on at least one symbol.)
3. Emit consecutive equal labels as one segment with `ret` as above.

Computed on the same 250-bar window served (a segment can therefore be labelled `range` while showing −24.8 % — 2308's last segment — because the merge keeps the previous label; the engine must not "fix" this).

Viewer (`app.js:881-892`, `914`): `bull` segments → faint red `markArea` on the price grid, `bear` → faint green, `range` → nothing; segments ending before `bars[0]` are skipped, `start` is clamped to `bars[0]`.

### 9.2 `summary{}`

```
"summary": {"regime": "range", "slope20": -97.14, "slope60": 18.83, "slope120": 17.64,
            "dist_ma60": -0.0238, "high_252": 2585.0, "low_252": 1358.34, "pos_252": 0.8247}
```

| Field | Formula (verified on all 9) | Units / rounding | Confidence |
|---|---|---|---|
| `regime` | the **raw daily label of the last bar** (step 1 above), *not* the last segment's label (2308: last segment `range`, summary `bear` because 1335 < 1736 < 1757) | enum | **high** |
| `slope20` / `slope60` / `slope120` | OLS slope of `log(close)` over the last N bars (x = 0..N−1) × 252 × 100 | annualised log-return in **percent/yr**, 2 dp | **high** (matches to 2 dp on all 27 values) |
| `dist_ma60` | `close[-1] / ma60[-1] - 1` | fraction, 4 dp | **high** |
| `high_252` / `low_252` | max / min of **close** over the trailing window (not high/low: 0050 max close 116.5 vs max high 116.6) | price, 2 dp | **high** that it is close-based; whether the window is 252 or 250 bars is indistinguishable in this snapshot (name says 252) |
| `pos_252` | `(close[-1] - low_252) / (high_252 - low_252)` | 0..1, 4 dp | **high** |

Viewer reads only `summary.regime` (`app.js:703`) for the `多頭`/`空頭`/`盤整` chip next to the price, and only when `rows[].regime` from `data.json` is absent (`rows[].regime` equals `summary.regime` in all 9 cases). `slope*`, `dist_ma60`, `*_252` are **not read** by the viewer (they feed scoring/AI prompts elsewhere).

---

## 10. `forecast{}`

### 10.1 Shape

```
"forecast": {"made_date": "2026-10-30", "model": "baseline", "base_price": 2370.0,
  "horizons": [
    {"horizon_days": 1,  "pred_ret": 0.0, "ci68": [-0.01224..., 0.01224...], "ci95": [-0.02400..., 0.02400...], "prob_up": 0.5, "model": "baseline"},
    {"horizon_days": 5,  ...}, {"horizon_days": 20, ...}],
  "fan": {"dates": [21 × "YYYY-MM-DD"], "median": [21], "lo68": [21], "hi68": [21], "lo95": [21], "hi95": [21]}}
```

| Field | Rule | Confidence |
|---|---|---|
| `made_date` | `== bars[-1][0]` (date of the close the forecast is based on). Not read by the viewer. | **high** |
| `model` | champion model name, `"baseline"` in all 9 files (`model-health.json → metrics.champion = {"1":"baseline","5":"baseline","20":"baseline"}` — champion is **global**, not per symbol: ridge has lower MAE for 0050 h=5/20 yet `baseline` is used). Other known value: `"ridge"`. Rendered verbatim in a chip titled `預測模型(冠軍)` and in the tooltip header `預測(baseline)`. | **high** |
| `base_price` | `== bars[-1][4]` byte-identical | **high** |
| `horizons[]` | exactly three, ordered 1, 5, 20 | **high** |
| `horizons[].horizon_days` | int ∈ {1, 5, 20} — chip text `1日 +0.0%` (`app.js:721`) | **high** |
| `horizons[].pred_ret` | fraction; `0.0` for `baseline` (random-walk baseline) | **high** |
| `horizons[].ci68` / `ci95` | `[lo, hi]` fractions, symmetric: `ci68 = ±σ·√h`, `ci95 = ±1.96·σ·√h` where **σ = sample std (ddof=1) of simple daily returns `close.pct_change()` over the last 20 bars** (matches to 1e-17 on all 9 symbols; log returns and other windows do not). Unrounded. | **high** |
| `horizons[].prob_up` | probability in [0,1]; `0.5` for baseline. Chip shows `漲率50%` (`Math.round(prob_up*100)`). | **high** |
| `horizons[].model` | per-horizon model name (same as top-level `model` here) | **high** |
| `data.json` twin | `rows[].forecast5 = {pred_ret, prob_up, ci68_lo, ci68_hi, model}` is the h=5 entry flattened (values identical) | **high** |

Viewer (`app.js:714-726`): chips `<h>日 <fmtRet(pred_ret)> 漲率<p>%` (class up/down by sign of `pred_ret`, title `95%區間 lo ~ hi` using `fmtRet` = signed %, 1 dp) + model chip. `forecast` missing or `horizons` empty → single warn chip `預測:資料累積中`.

### 10.2 `fan{}` — 21 points (**high**, reproduced to 1e-13)

| Field | Rule |
|---|---|
| `dates[0]` | `== made_date == bars[-1][0]` (the anchor; all five value arrays equal `base_price` there) |
| `dates[1..20]` | the next **20 weekdays** after `made_date` (`2026-11-02` … `2026-11-27` for a Friday anchor; weekends skipped). Equivalent to `pd.bdate_range(made_date, periods=21)`. No Taiwan holiday falls in the sampled range, so a holiday-aware calendar cannot be excluded — see Open questions. |
| `median[i]` | `base_price · exp(interp(i))` where `interp` is `numpy.interp(i, [0,1,5,20], [0, log(1+pred_ret_1), log(1+pred_ret_5), log(1+pred_ret_20)])` → all `== base_price` for baseline |
| `lo68[i]` / `hi68[i]` | `base_price · exp(np.interp(i, [0,1,5,20], [0, log(1+ci68_h[0 or 1]) for h in 1,5,20]))` — i.e. **piece-wise linear interpolation in log-price space between the three horizon knots** (linear interpolation in price space is off by up to 11.5 for 2454) |
| `lo95[i]` / `hi95[i]` | same with `ci95` |

Viewer (`app.js:859-879`, `941-954`, `1134-1145`): fan dates are appended to the category axis after the bars (deduplicated against bar dates — `dates[0]` coincides with the last bar so it is not duplicated); values are padded with `null` on the history part; drawn as stacked-area bands `預測95%` (α 0.10), `預測68%` (α 0.16) and a dashed `預測中位` line, all in `ACCENT` blue; the tooltip over fan dates shows `中位 price (±x.x%)` relative to `base_price`, `68%區間`, `95%區間`, and `預測必有誤差,僅供參考`. Default zoom shows the last 130 of the 270 axis points (`app.js:1011-1015`) = the last ~110 bars + the 20 future fan points. Missing `fan` or empty `fan.dates` → no fan series and no extra axis points; everything else still renders.

---

## 11. `ledger{}` — **not consumed by the viewer**

```
"ledger": {"by_horizon": [{"model": "baseline", "horizon": 1, "n": 73, "mae": 0.013063025439497266, "hit_rate": 0.5753424657534246}, …]}
```

* 6 rows: models `baseline`, `ridge` × horizons 1, 5, 20, ordered horizon-major (`baseline 1, ridge 1, baseline 5, ridge 5, baseline 20, ridge 20`).
* `n` = number of *resolved* forecasts for this symbol/model/horizon; per-symbol `n` sums exactly to `model-health.json → metrics.by_model_horizon[].n` (639 / 603 / 462), so this is the per-symbol slice of the global forecast ledger. Six symbols have 73/69/53, three (2881, 3481, 6789) have 67/63/48 — added to the watchlist ~6 sessions later.
* `mae` = mean |pred_ret − realised_ret| (fraction), `hit_rate` = direction-hit fraction; both emitted **unrounded** here (vs. 6/4 dp in `model-health.json`). For the zero-prediction baseline the hit rate behaves like "share of windows with realised return ≥ 0" (2881 h=20 → 0.979 during its bull run), i.e. the comparison is `sign(pred_ret ≥ 0) == sign(actual ≥ 0)` (**medium**).
* `grep` confirms `app.js` never reads `ledger`/`by_horizon` (its only "ledger" hit, line 1707, is the shadow tab comment). Keep emitting it for parity/AI prompts.

---

## 12. `ai_note{}`

```
"ai_note": {"ts": "2026-10-12T14:16:22+08:00", "rec_code": "STRONG_BUY", "text": "技術面是這波評分的主要支撐——…"}
```

| Field | Rule | Viewer |
|---|---|---|
| `ts` | ISO 8601 with `+08:00`, second precision | `fmtHM` → `HH:MM` pinned to Asia/Taipei (`app.js:776`, `140-143`) |
| `rec_code` | enum `STRONG_BUY \| BUY \| HOLD \| SELL \| STRONG_SELL` — the recommendation **at the time the note was generated** (notes date from 2026-10-12 while current `rows[].rec_code` are HOLD/SELL; the note is reused until the AI succeeds again) | not read |
| `text` | 290–410 Chinese chars, one paragraph, plain text (no markdown) | `app.js:767-785`: `🤖 AI 解讀 HH:MM text`; escaped |
| `data.json` twin | `rows[].ai_note` is byte-identical (same object) | row's note used as fallback (`app.js:773`) |

Absent/empty `text`: if `overview.engine.ai.enabled` → `🤖 AI 解讀 尚未產生`, else the bar is hidden. The viewer only trusts `S.detail.ai_note` when `S.detail.symbol === S.selected` (`app.js:771`).

---

## 13. Rendering map: key → `app.js` → DOM → missing-key behaviour

| Key | Reader (`app.js`) | DOM target (`index.html`) | If missing / empty |
|---|---|---|---|
| `symbol` | 809 identity check | — | payload dropped silently |
| `code`, `name` | 692-694, 1237-1239, 1282-1284 | `#sym-title`, `#news-symbol`, `#chips-symbol` | falls back to `rows[]` values |
| `bars` | 787-796 (price/pct fallback), 824-828, 850-857, 1097-1119 | `#main-chart` candlestick + volume + tooltip | `尚無K線資料`, chart disposed |
| `indicators.ma5/ma20/ma60` | 924-926, 1121-1123 | lines `MA5`/`MA20`/`MA60` (colours `#e8b339`/`#3987e5`/`#b48ef0`), legend | series omitted individually |
| `indicators.bb_up` + `bb_low` | 929-939 | two faint edge lines + area `布林` (needs **both**) | omitted |
| `indicators.rsi` | 970-977, 1124 | sub-chart `RSI` tab (y 0–100, guides 70/30) | empty series |
| `indicators.macd/macd_sig/macd_hist` | 978-995, 1125-1129 | `MACD` tab: bars `MACD柱` (red ≥0 / green <0), lines `DIF`, `DEA` | empty series |
| `indicators.k/d` | 996-1008, 1130-1133 | `KD` tab: `K值`, `D值` (y 0–100, guides 80/20) | empty series |
| `signals`, `fund_signals` | 731-736 | `#signal-chips` | no chips |
| `news.score` | 738-741 (chip), 1233-1243 | `消息 ±x.x` chip, `#news-score` | 0 |
| `news.items` | 1234-1268 | `#news-list` | `暫無相關新聞或尚未載入` |
| `chips.score` | 743-746, 1277-1288 | `籌碼 ±x.x` chip, `#chips-score` | 0 |
| `chips.signals` | 1291-1293 | `#chips-signals` | none |
| `chips.recent` | 1295-1311 | `#chips-body` | `暫無籌碼資料(上櫃股票或資料尚未回填)` |
| `intraday_kd` | 748-756 | `60分KD …` chip | chip omitted (unless `rows[].kd60`) |
| `trend.summary.regime` | 703-712 | `#sym-regime` chip | hidden (unless `rows[].regime`) |
| `trend.segments` | 882-892, 914 | candlestick `markArea` | no shading |
| `forecast.horizons`, `forecast.model` | 716-726, 1137 | `#forecast-chips`, tooltip header | `預測:資料累積中` |
| `forecast.base_price` | 1099, 1139 | tooltip `中位 … (±%)` | no % suffix |
| `forecast.fan` | 860-879, 942-954, 1018, 1134-1145 | fan bands/median, legend entries | no fan |
| `ai_note` | 770-777 | `#ai-note` | `尚未產生` / hidden |
| `ledger`, `made_date`, `summary.slope*`, `summary.*_252`, `summary.dist_ma60`, `horizons[].ci68`, `horizons[].model` | — | — | never read |

Position overlay (`均價`/`停損`/`移停` dashed `markLine`s, `app.js:894-907`) comes from `data.json → overview.positions[]`, not from this file.

### 13.1 Chart composition (for the record)

Three stacked grids sharing one category axis (`app.js:1051-1079`): price grid (top 46 %, right-hand y-axis `scale:true`), volume grid (11 %, `fmtVol` labels), sub-indicator grid (16 %). ECharts `candlestick` takes `[open, close, low, high]` (`app.js:853`), colour red up / green down (Taiwan convention, `UP='#f04452'`, `DOWN='#12b76a'`). Zoom state is remembered across re-renders (`S.zoom`); tooltip is axis-triggered with a cross pointer; `animation:false`.

---

## 14. Consistency requirements with `data.json`

| `symbol/<code>.json` | must equal | `data.json → overview.rows[]` |
|---|---|---|
| `symbol`, `code`, `name` | == | `symbol`, `code`, `name` |
| `bars[-1][4]` | == (same float) | `price` (when `quote_fresh` is false, as in the snapshot) |
| `round((bars[-1][4]/bars[-2][4]-1)*100, 2)` | == | `pct` |
| `trend.summary.regime` | == | `regime` |
| `forecast.horizons[h=5]` | flattened | `forecast5 {pred_ret, prob_up, ci68_lo, ci68_hi, model}` |
| `intraday_kd` minus `score` / `intraday_kd.score` | == | `kd60` / `kd60_total` |
| `news.score`, `chips.score` | == | `news_total`, `chips_total` |
| `ai_note` | == | `ai_note` |

Bake all 9 symbol files and `data.json` from the same in-memory state in one EOD run (`events.json`: `EOD 完成:更新 9 檔資料,記錄 54 筆預測,兌現 54 筆。` = 9 symbols × 3 horizons × 2 models).

---

## 15. Open questions (with proposed defaults)

1. **`成交量` volume ratio source.** The notes say `量為均量 2.0 / 2.1 / 1.7 倍` for 0050 / 2308 / 2454, but no `today / mean(or median)(N)` of `bars[].volume` for N = 3…60, with or without today, lagged or not, reproduces all three (`bars` give 1.98 / 1.71 / 1.55 for N=20). The signal was probably computed in the 18:17 startup scan from the realtime quote's volume rather than from the cached daily bar. *Default:* `vol[-1] / mean(vol[-21:-1])`, fire `帶量下跌`/`帶量上漲` (±1.5) when ratio ≥ 1.5 and close moved against/with it; print the ratio with `%.1f`.
2. **`news.score` aggregation.** Not a plain mean (0050 → 0.17 from one +1 among 8; 6789 → −0.37 with items summing to +1). *Default:* recency-weighted mean of item scores with a 24 h half-life, rounded to 2 dp, clipped to ±3; label the exact formula as "to be confirmed" in the news spec.
3. **Unobserved label strings**: `RSI 超買`, `KD 黃金交叉` / `高檔`, `布林通道 觸上軌`, `成交量 帶量上漲`, `外資連買N日`, `投信賣超`, `法人買盤動能`, `intraday_kd` high-side labels, `盈餘成長`/`ROE`/`毛利率` low-side texts. *Default:* mirror the observed negative/positive counterpart with the symmetric score; keep the observed strings byte-exact.
4. **Fundamental thresholds** (ROE 0.7 cut in (13 %, 24 %], revenue 0.7 cut in (13 %, 31 %], PE cut in (≈30, 55], gross-margin cut below 26 %). Note the anomaly: 2454 has no `毛利率` chip although its own news item reads `毛利率46.3%`, while 2881/2882 (28 %/26 %) do have one — either the metric was missing from the data source for 2454 or the rule is not a plain threshold. *Default:* ROE ≥ 15 % → 0.7, > 0 → 0.3 (`ROE 尚可`); revenue ≥ 20 % → 0.7, > 0 → 0.3, < 0 → −0.5; earnings > 0 → 0.4, < 0 → −0.4; gross margin ≥ 25 % → 0.3; PE > 50 → −0.3.
5. **`布林通道` score 0.62** — likely `0.5 × 1.25` weight rounded half-even. *Default:* emit `round(0.625, 2)` = `0.62` so the chip title reads the same.
6. **Fan calendar**: weekday-only vs. Taiwan-holiday-aware. *Default:* `pd.bdate_range` (weekdays) — it reproduces the snapshot and avoids a holiday table; revisit if the viewer should skip 2027 holidays.
7. **`high_252`/`low_252` window** (252 vs 250 bars) — indistinguishable here. *Default:* trailing 252 closes (name), computed on the cached history before slicing.
8. **Trend segments on longer history?** The window-only algorithm reproduces all 9 files; whether the engine clips longer-history segments to the window cannot be excluded. *Default:* compute on the served 250-bar window.
9. **`ledger.hit_rate` definition for `pred_ret == 0`** — *Default:* `(pred_ret >= 0) == (actual >= 0)`.
10. **Item cap / query for Google News RSS** (8 items; query string unknown — `name` or `code name`). *Default:* query `"<name> <code>"`, keep the first 8 entries in feed order.
