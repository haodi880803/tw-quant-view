# 08 — Shadow A/B test semantics, operational schedule, and the GitHub Actions design

Status: reverse-engineered from the surviving data — `shadow.json` (working tree = bake of `2026-10-30T14:50:28+08:00`; git `2e74138` = bake of `2026-08-14T20:44:48+08:00`, "Aug"), `events.json` (100 rows each, Oct ids 6663–6762 and Aug ids 995–1094), `data.json` → `overview.engine` (both), `orders.json`, `model-health.json`, `ai_report`, the viewer (`app.js` l.1552–1781 shadow tab, l.2046–2075 poll loop; `index.html` l.231–285) and the git metadata of the snapshot commits. Nothing here comes from engine source. Every rule that is not literally in `app.js` is marked **inferred** with its evidence and a confidence (**high** = reproduced exactly on every observation, **medium** = consistent with all observations but under-determined, **low** = plausible reading of sparse evidence). Section 3 is a proposal, not an observation. Open points are collected in §4 with a proposed default.

Related specs (this file does not repeat them): `03 §4` owns the field-by-field `shadow.json` contract and the viewer rendering of each field; `06 §6` owns the shadow arms' sizing/fill model; `06 §7` owns the intraday scan cadence table; `01 §4` owns `overview.engine` (`last_scan`, `health`, …); `03 §2` owns the `events.json` message templates.

Conventions: timestamps are Taipei ISO-8601 with explicit offset and second precision (`2026-10-31T14:15:22+08:00`), dates `YYYY-MM-DD`; money NTD; `round(x, n)` is Python's round; "T" is the Taipei calendar date of the run; "bar date" is a date for which the daily OHLCV bar exists in `symbol/<code>.json` (= a TWSE trading day).

---

## 1. Shadow A/B test (`shadow.json`, tab `影子對照`)

### 1.1 What the test is

Two **independent paper accounts** of `initial_cash 1000000.0` each replay the same end-of-day data from `start_date "2026-08-07"` with two genomes, and a frozen adjudicator decides at close-out whether the candidate (B) replaces the incumbent (A). The viewer's own description (`index.html:280–282`, verbatim):

> 影子對照與生產帳完全隔離:兩臂都是 worldsim 紙上模擬(M3 摩擦),讀的是凍結封存帳,任何人都改不了參數。四腿為凍結結案判準,達 ≥60 交易日且 B 平倉 ≥10(或 120 日硬上限)自動裁決;初期腿未過屬預期,以結案為準。非投資建議。

| Term in the file / viewer | Meaning | Evidence / confidence |
|---|---|---|
| `arms.a = "incumbent-v6"`, label `A 現任` | the live parameter set as frozen when the test started: params **v6** (adopted 2026-07-18) plus the `tuner SAFE_*` constants — `genes[]` column `a` = `w_* 1.0,1.0,1.0,1.0,0.5,1.25,1.5`, `buy_th 3.0`, `strong_gap 2.0`, `sell_th -3.0`, `stop_pct 0.08`, `trail_pct 0.12`, `risk_frac 0.005`, `strong_mult 1.5`, `caution_scale 0.5`, `persistence 2.0` | high on values; the live engine moved on to v7–v9 during the window (`params_history`), A did **not** follow (06 §6) |
| `arms.b = "risk-exit-consensus"`, label `B 候選` | the candidate genome; 12 of 16 genes differ, all unrounded floats (`stop_pct 0.08300581937609232`, `trail_pct 0.206062542287206`, `risk_frac 0.008025956907855073`, …), `buy_th/strong_gap/sell_th/persistence` identical to A | high on values; the name and the float pattern suggest a consensus (mean) of several tuner candidates focused on risk/exit genes — **low** |
| `mode "M3"`, footer `M3 摩擦` | the friction model of the replay ("worldsim"): fills at the next bar's **open** with adverse slippage ≈ 10 bp + a size-dependent impact (§1.5); `reject_rate`, `n_starved` are its other outputs | medium (06 §6 + §1.5 below) |
| `凍結封存帳` ("frozen archived ledger") | the append-only ledger of both arms; the panel is a read-only bake of it (`窗內交易(自封存帳決定性重算)`, `未平倉部位…(唯讀重算…)`) | high — Aug rows/trades are a byte-identical prefix of Oct (§1.3) |
| `四腿` ("four legs") | the four pass/fail criteria `operational / safety / return / realization` judged over the **whole window at close-out** (`四腿於結案時整窗判定;觀察期未過屬預期`) | high |
| `結案` / `裁決` | close-out and verdict (§1.7–1.8) | high |

Isolation rules implied by the text and the data (**high**): the shadow never touches the production account (`overview.account`, `orders.json`), the production engine never reads shadow results, and no parameter of either arm changes after `start_date` (`genes[]` identical in Aug and Oct; `freeze_ok`).

### 1.2 Lifecycle

| Phase | `active` | `rows` | `verdict` / `verdict_sealed` | `computing` | Viewer (03 §4.5) |
|---|---|---|---|---|---|
| not started | `false` (+ optional `reason`) | — | — | — | one line: `reason` or `shadow 尚未起錶` |
| armed, waiting for first row | `true` | `[]` | `null` / `false` | `false` | `影子帳等待首行(day i 決策、i+1 成交;窗內需 ≥2 交易日)` + `起始日 2026-08-07` |
| running (both snapshots) | `true` | ≥ 1 | `null` / `false` | `false` | chart, tables, chips; progress chip `第 55/60 交易日 ・ B 平倉 2/10` |
| panel stale (re-bake pending) | `true` | last bake | unchanged | `true` | chip `更新中…` (title `面板資料與影子帳最新狀態不一致,背景重烤中`); with `refresh_failed:true` the chip reads `更新失敗` (title `面板重烤失敗,已寫入運作日誌;每 10 分鐘自動重試`) |
| adjudicated / sealed | `true` | frozen | object / `true` | `false` | banner `裁決(…):通過|未通過 → …` above the (frozen) tables |

**Inferred** mechanics (medium): the ledger and the panel are two things. The ledger advances once per bar date; the panel (`shadow.json`) is re-baked asynchronously when its `state_key` no longer matches the ledger (`computing:true` meanwhile), and a failed bake is retried every 10 minutes (`refresh_failed`, the viewer title says so; the failure is also logged to the 運作日誌 = `events.json`). Observed bake times are 14:50:28 (Fri 10-30) and 20:44:48 (Fri 08-14), i.e. not at a fixed clock time, never on the Saturday run (the Oct panel is a day older than `data.json`). For the rebuild the synchronous design in §3.5 (advance + bake inside the EOD job) satisfies the viewer with `computing:false` always.

### 1.3 Frozen spec, seal, hash chain, `state_key`

What the viewer needs: `chain_ok === false` → warning `帳本雜湊鏈驗證失敗`; `freeze_ok === false` → warning `凍結封條驗證失敗` (both prefixed `⚠ `, joined by `；` with `warnings[]`); `state_key` is not read. The comment at `app.js:1620–1621` calls the sealed adjudicator "the authority" and the warnings "display-level".

Evidence across the two bakes (**high**):

| Field | Aug bake (5 rows) | Oct bake (55 rows) | Conclusion |
|---|---|---|---|
| `state_key` | `f3dc3f21…c11331` | `63f46022…1271c5` | 64 hex = SHA-256; it **changes as the ledger grows** → it keys the ledger state, not only the frozen spec |
| `rows[0..4]`, `trades.a[0]`, `trades.b[0..8]` | — | identical to Aug, byte for byte | the ledger is append-only; rows are **never recomputed from bars** (2330's bars were re-adjusted between the bakes — its fills show +39.7 bp "slippage" against today's bars while every other symbol shows 10–13 bp — yet the archived prices did not move) |
| `genes[]`, `arms`, `start_date`, `mode`, `initial_cash`, `closeout` | same | same | the frozen spec |
| `chain_ok`, `freeze_ok`, `warnings` | `true`, `true`, `[]` | same | — |
| `progress.n_days` | 5 = `len(rows)` | 55 = `len(rows)` | `n_days = len(rows)` |

**Proposed** definitions for the rebuild (the viewer never reads the values, so any deterministic scheme works; this one gives the two warnings a real meaning):

```
canon(x)      = json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
frozen_spec   = {schema, start_date, mode, initial_cash, arms, closeout, genes}        # genes as the 16 {gene,a,b} rows
freeze_seal   = sha256(canon(frozen_spec))                                             # written once to state/shadow/seal.json
row_hash[0]   = sha256(freeze_seal + "\n" + canon(rows[0]))
row_hash[i]   = sha256(row_hash[i-1] + "\n" + canon(rows[i]))                          # rows[i] = the 9 published keys of §1.4
chain_head    = row_hash[-1]   (= freeze_seal when rows is empty)
state_key     = sha256(canon({"freeze": freeze_seal, "head": chain_head, "n": len(rows), "sealed": verdict_sealed}))
chain_ok      = every stored row_hash recomputes                                        # detects edits/deletions inside the ledger
freeze_ok     = sha256(canon(current frozen_spec)) == stored freeze_seal                # detects any parameter change after start
computing     = panel.state_key != state_key(ledger)   (always false with the synchronous bake of §3.5)
```

`prefix_breaks` (leg `operational`, §1.6) is the counter that goes with this: each time the ledger is advanced, the engine re-derives the window from the archived fills and compares the derived prefix with the stored rows; a mismatch increments `prefix_breaks` and the stored rows win. Both bakes report `0`.

### 1.4 Daily ledger rows (`rows[]`, table `每日帳`)

Row shape (03 §4.2): `{date, eq_a, eq_b, ret_a_pct, ret_b_pct, diff_pp, day_pp, closed_a, closed_b}`.

Append rule (**inferred**):

| Rule | Evidence | Confidence |
|---|---|---|
| Exactly one row per **bar date** ≥ `start_date`; non-bar weekdays get no row and are not back-filled | 55 rows = 55 bar dates between 2026-08-07 and 2026-10-29 in all 9 symbol files; the five weekdays without a bar (`09-25`, `09-28`, `10-09`, `10-23`, `10-26`) have no row | high |
| The last row is **T−1** relative to the bake: the row for bar date D is appended by the first daily run after D's bar is final (the run on the next bar date), while `holdings[].last/last_date` are marked at T | bake 10-30 14:50 → last row 10-29, holdings `last_date 2026-10-30`; bake 08-14 20:44 → last row 08-13 (empty-state text `day i 決策、i+1 成交`) | high on the lag, medium on the reason (D's fills are the i+1 fills of decisions taken at D−1's close; marking at D's close needs D's complete bar, which the 14:15 EOD "corrects" — `14:15 EOD 會再以完整日K做最終校正`) |
| `eq_x` = cash + Σ qty × close(D), 2 dp | holdings `ret_pct` recompute to 2 dp from `last` | high |
| `ret_x_pct = round((eq_x[i] / eq_x[0] − 1) × 100, 4)` — base is **row 0**, not `initial_cash` (`基準=首行帳(與凍結報酬腿同口徑)`); note `eq_b[0] = 1000015.36` | 0/110 mismatches over both bakes | high |
| `diff_raw[i] = (eq_b[i]/eq_b[0] − eq_a[i]/eq_a[0]) × 100`; `diff_pp = round(diff_raw, 4)`; `day_pp = round(diff_raw[i] − diff_raw[i−1], 4)` (`0.0` on row 0; differencing the **unrounded** values — differencing the rounded `diff_pp` is off by 0.0001 on 28 rows) | 0 mismatches | high |
| `closed_x[i]` = cumulative number of `SELL` fills of arm x with `date ≤ rows[i].date` (a round-trip closes on a full SELL; the shadow never partially sells — every SELL row has `qty: null`) | a: 1,2,3,4,5,7 on 10-13/14/16/19/20/27 = the SELL dates; b: 1 on 10-19, 2 on 10-20 | high |
| `progress.n_days = len(rows)`, `progress.closed_b = rows[-1].closed_b` (0 when empty) | 55/2 and 5/0 | high |

Append procedure (what the daily job does for bar date D, run on the next bar date T):

1. Load the archived fills of both arms up to D−1 and the frozen genes; compute the decisions at D−1's close for each arm (same scoring as the live engine with that arm's genes; 06 §6 for sizing: 0.20 cash cap, 1000-share lot cap, `stop_pct/trail_pct/persistence` of the arm).
2. Fill them at D's open with M3 friction (§1.5); append fills to `trades.{a,b}` with `date = D`.
3. Apply exits at D (`停損`, `移動停利`, `訊號` — reasons verbatim) and mark everything at D's close → `eq_a`, `eq_b`.
4. Append the row, extend the hash chain, recompute `progress`, `legs`, `stats`, `turnover`, `holdings` (marked at the latest available close, T), evaluate the close-out (§1.7), bake the panel.

### 1.5 Fills, trades, holdings — what this spec adds to 06 §6

`trades.{a,b}[]` rows are `{type, symbol, date, price, qty, score, reason, ret}` (03 §4.4). `date` is the **fill** date (the bar whose open was used), `price` is the unrounded fill price. Measured against today's bars (8 symbols whose bars were not re-adjusted; 2330 excluded):

| Fill | `price / open − 1` | Observation |
|---|---|---|
| BUY, `qty ≤ 5` (29 fills) | +10.01 … +10.07 bp, mean +10.09 | base slippage ≈ 10 bp |
| BUY, `qty ≥ 500` (9 fills) | +11.95 … +12.74 bp, mean +12.25 | grows with participation: 12.74 bp at 1000 sh / 14.2 M vol (0.70 bp of volume), 12.17 bp at 772 / 17.3 M; the excess (2.17–2.74 bp) tracks `≈ 3.2 × sqrt(qty / volume × 1e4)` |
| SELL (9 fills) | −10.07 … −10.88 bp | adverse on the sell side too |

→ **M3 ≈ open × (1 ± (10 bp + k·√participation))** with k ≈ 3.2 bp per √(1e-4) — **low** (9 large fills); `stats.x.slip_bp` = mean absolute slippage over all fills of the arm (`10.66` / `11.65`), `turnover_notional` = Σ |qty × price| over BUY and SELL fills (larger than Σ BUY notional in both arms), `n_fills = len(trades.x)`, `reject_rate` / `n_starved` were `0.0` / `0` in both bakes (proposed meaning: fills refused by the friction model, e.g. limit-up/down or zero-volume bars, and buy decisions that could not be sized to ≥ 1 share — see §4).

`holdings[].age_days` = number of bar dates from `first_buy` to `last_date` inclusive (7/8 exact; B-0050 is off by one: 37 vs 38 — a non-bar day may be excluded differently; **medium**). Formulas for `stop_line`, `trail_line`, `dist_*` are in 03 §4.4.

### 1.6 The four legs (`legs`, chips `操作腿 / 安全腿 / 報酬腿 / 實現腿`)

Each leg is an object with `pass` plus its numbers; the chip prints `{label} ✓|✗ {detail}` (`✗` with class `pending` — "not yet", not "failed"; the title is `四腿於結案時整窗判定;觀察期未過屬預期`). A missing leg renders `{label}:—(等待資料)`. The legs are recomputed at every bake over the whole window; only at close-out do they become the verdict.

| Leg | What it tests | Fields (verified formula) | Pass rule | Evidence |
|---|---|---|---|---|
| `operational` — `操作腿` | the experiment itself stayed deterministic and append-only: the re-derived ledger prefix never diverged from the archived one | `prefix_breaks` int (§1.3) | `prefix_breaks == 0` — **medium** (both bakes 0 / `pass:true`; chip detail `prefix_breaks=0`) | |
| `safety` — `安全腿` | B did not blow up and did not draw down out of proportion to A | `doom` bool; `mdd_a`, `mdd_b` = max peak-to-trough drawdown of `rows[].eq_x`, fraction, 4 dp (exact: 0.0588 / 0.0399; Aug 0.0005 / 0.0027) | `not doom and mdd_b ≤ max(1.5 × mdd_a, 0.10)` — **low** (proposal of 03 §7; the only hard evidence is that `pass` was `true` in Aug with `mdd_b = 5 × mdd_a`, so the rule has a floor/tolerance and is not `mdd_b ≤ mdd_a`). Proposed `doom = min(eq_b) ≤ 0.80 × eq_b[0]` | chip `MDD B 4.0% / A 5.9%` |
| `return` — `報酬腿` | B out-returned A over the window | `ret_x = round(eq_x[-1]/eq_x[0] − 1, 6)` (= `rows[-1].ret_x_pct / 100`), `diff = ret_b − ret_a` (0.132083 − 0.032851 = 0.099232 exact) | `diff > 0` — **medium** (true and passing in both bakes, incl. Aug with +0.43 pp; no margin observed) | chip `B−A +9.92pp` |
| `realization` — `實現腿` | B's edge is not an artefact of unrealistic fills: its slippage and rejects are within a multiple of A's | `slip_bp_x = round(stats.x.slip_bp, 2)`, `reject_x = stats.x.reject_rate` | `slip_bp_b ≤ max(2 × slip_bp_a, 5)` — **high** (the chip prints the rule: `B 滑價 11.65bp(門檻 max(2×A, 5bp))`); `reject_b ≤ max(2 × reject_a, 0.01)` — proposed | |

### 1.7 Close-out rule (`closeout`, `progress.ready`, `progress.capped`)

`closeout = {"min_days": 60, "target_closed": 10, "hard_cap_days": 120}` (both bakes; the progress chip uses them as denominators, defaults 60/10 if missing).

```
n_days   = len(rows)                     # bar dates since start_date (rows exist only for bar dates)
closed_b = rows[-1].closed_b if rows else 0
capped   = n_days >= hard_cap_days                       # 120
ready    = (n_days >= min_days and closed_b >= target_closed) or capped
if ready and not verdict_sealed:
    verdict = adjudicate()               # §1.8; sets verdict_sealed = True, keeps active = True
```

Both `ready` and `capped` are published but not read by the viewer. In the Oct bake `n_days 55`, `closed_b 2` → `ready false`, `capped false`. Projection (for planning the manual seal): day 60 is the 5th bar date after 2026-10-29 (≈ 2026-11-05); with only 2 B closes in 55 days the `closed_b ≥ 10` condition would almost certainly not be met before the 120-day cap (≈ 2027-02, 65 bar dates after 10-29), so without intervention the verdict would be sealed by the cap in February 2027 with `capped:true`.

### 1.8 Verdict content

The banner reads **only** `verdict.adjudicated` (string), `verdict.pass` (bool), `verdict.capped` (bool), `verdict.next` (string) and prints `裁決({adjudicated}):{通過|未通過}{(120 日硬上限)}? → {next}` (`app.js:1631–1637`). `verdict` must be an **object**; a string would render `裁決():未通過 → ` (its properties are `undefined`). `verdict_sealed` is not read. Extra keys are preserved and ignored.

**Automatic adjudication** (proposed, consistent with the banner):

```json
"verdict": {
  "adjudicated": "2027-02-03",
  "pass": false,
  "capped": true,
  "next": "維持 A 現任(incumbent-v6);影子對照結案",
  "kind": "auto",
  "sealed_at": "2027-02-03T14:15:40+08:00",
  "n_days": 120, "closed_b": 4,
  "legs_at_seal": {"operational": true, "safety": true, "return": true, "realization": true},
  "failed_legs": []
},
"verdict_sealed": true
```

with `pass = all four legs pass` at the sealing bake; on pass `next = "採用 B(risk-exit-consensus)為正式參數 v{n+1};影子對照結案"`; `adjudicated` = the bar date of the sealing run; `capped` = sealed by `hard_cap_days` rather than by the closed-trade condition.

**Manual seal in favour of B** (the operator decision this rebuild needs — write exactly this, adjusting the date/version; it renders as `裁決(2026-11-01 手動採用):通過 → B 組勝出,手動採用:risk-exit-consensus 升為正式參數 v10;影子對照結案`):

```json
"progress": {"n_days": 55, "closed_b": 2, "ready": true, "capped": false},
"verdict": {
  "adjudicated": "2026-11-01 手動採用",
  "pass": true,
  "capped": false,
  "next": "B 組勝出,手動採用:risk-exit-consensus 升為正式參數 v10;影子對照結案",
  "kind": "manual",
  "winner": "b",
  "sealed_at": "2026-11-01T12:00:00+08:00",
  "sealed_by": "operator",
  "n_days": 55, "closed_b": 2,
  "legs_at_seal": {"operational": true, "safety": true, "return": true, "realization": true},
  "reason": "主機損毀、引擎重建;影子窗 55/60 交易日四腿全過(B−A +9.92pp,MDD B 4.0% vs A 5.9%,滑價 11.65bp vs 10.66bp),人工提前結案採用 B"
},
"verdict_sealed": true,
"computing": false,
"refresh_failed": false
```

Rules for the sealed file (**high**, from the renderer): keep `active:true`, `chain_ok:true`, `freeze_ok:true`, `warnings:[]`; keep `rows/legs/stats/turnover/trades/holdings/genes` frozen at the last computed values (the tables stay visible under the banner); `capped` must be `false` or the banner claims a 120-day cap; do not put the explanation into `warnings` (it would render with `⚠`); after sealing the file stops changing (`generated_at` of the sealing bake stays). Companion records (owned by 03): one `events.json` line, source `engine`, level `INFO`: `影子對照裁決:B 組勝出,手動採用(第 55/60 交易日,B 平倉 2/10);risk-exit-consensus 升為正式參數 v10`, and one `params_history` row in the manual-adoption shape (`train_metric/valid_metric/champion_metric: null`, `adopted: 1`, `version: 10`, `reason: "手動採用:影子對照 B 組(risk-exit-consensus)勝出,…"`), with `engine.params_version` → `10` and `active_version` → `10`. B's genes become the live `params_json` (`weights{…}`, `exit{stop_pct, trail_pct}`) and the SAFE constants (`risk_frac`, `strong_mult`, `caution_scale`, `persistence`) — 06 §6 maps the names.

### 1.9 `warnings[]`

Never observed non-empty. Proposed vocabulary (rendered after `⚠ `, joined by `；`): `封存帳缺 {date} 列(當日未執行)` when a bar date has no row (the rebuild's first run after an outage), `B 臂 {date} 無法成交:{reason}` when M3 rejects a fill, `面板重烤失敗:{exc}` with `refresh_failed`.

### 1.10 Bootstrapping the shadow state in the rebuild

The archived ledger was lost with the host; the surviving panel is the only copy. Seed `state/shadow/` from it: `rows[]` (55) become the ledger with a fresh hash chain, `trades.{a,b}` (50/43) become the archived fills, the 16 `genes` + `arms/start_date/mode/initial_cash/closeout` become the frozen spec and seal, `prefix_breaks` starts at 0, and the first rebuilt bake must reproduce the 55 rows byte for byte (this is the `operational` leg's meaning). Day 56 onwards is appended by the rebuilt engine only if B is **not** sealed manually first; if the manual seal of §1.8 is applied, the ledger is frozen at 55 rows and the daily job skips the shadow step.

---

## 2. Operational schedule (inferred from timestamps)

### 2.1 Evidence

All times Taipei (`+08:00`). The two snapshot windows cover two complete trading Fridays (2026-08-14, 2026-10-30), two Saturdays (08-15, 10-31), the tail of 08-13 and 10-28/29, and three engine restarts.

| When | Event / artefact (verbatim where quoted) | Reading |
|---|---|---|
| Fri 08-14 08:30:26 | `晨會:夜盤 +0.8%、TSM +0.3%、費半 +0.5%;近 3 日事件 1 筆、宏觀新聞 14 則;無覆蓋` | morning brief at 08:30 |
| 09:00:31–09:00:45 | news AI attempt, then `紙上買單成交:…` ×2 | first scan of the day at 09:00 (orders at 09:00:21–09:00:55 on five days) |
| 09:15:49, 09:30:52, 09:46:05, 10:01:08, … 13:18:00, 13:33:02 | AI attempts alternating `ai`(opus) / `news`(sonnet) every ~15 min, drifting +1–2 s per cycle | the 5-min loop (`scan_interval_min 5`) is "sleep 5 min after the scan ends" (06 §7); AI retries ride on it after the 15-min pause (§2.6) |
| 13:33:13 (Aug), 13:33:06 (Oct) | `收盤定盤掃描完成:9 檔以收盤世界重新定價(其中 9 檔取得交易所定盤價);14:15 EOD 會再以完整日K做最終校正。` | closing-fix scan ≈ 13:33 |
| 14:02:55 (10-30) | news attempt + `2317 鴻海:買進→觀望` | scans continue after the close |
| 14:15:19–14:15:45 (both Fridays, 10-28, 10-31) | `市場狀態:halt(…)` → `[heartbeat] 心跳已送(FAIL:AI 日報 18 天未產生)` → `EOD 完成:更新 9 檔資料,記錄 54 筆預測,兌現 54 筆。` → `行事曆同步:TWSE 除權息 3 筆` → per-symbol `… 未來 30 天無任何行事曆事件記錄——法說會/除權息可能未收錄` → (10-30 only) `偵測到預測品質下降(命中率 33%,MAE 惡化 155%),自動觸發調參` → `開始調參:walk-forward champion/challenger…` | EOD at 14:15 |
| 14:16:22 … 14:18:36 (10-12, the last AI success) | `ai_note.ts` per symbol ~15–20 s apart; `ai_report.generated_at 14:16:54` | AI notes + daily report right after EOD, sequential, opus |
| 14:15:22 (10-31), 14:15:32 (08-15) | `data.json.generated_at`; last event id in the same second; `simple.html` `產生時間 2026-10-31 14:15(台北時間)` | bake at the end of EOD |
| 14:15:24 (10-31), 14:15:34 (08-15) | git commit `snapshot 2026-10-31T14:15:24+08:00` | publish 2 s after the bake |
| 14:50:28 (10-30), 20:44:48 (08-14) | `shadow.json.generated_at` | asynchronous shadow panel bake (§1.2) |
| 17:20 & 23:45 (10-28), 18:17 (10-30), 20:50 (08-14) | news attempts + `X:買進→觀望` lines; `engine.last_scan 2026-10-30T18:17:00+08:00`, `last_scan_kind "啟動"`, `next_scan = last_scan + 5 min` | restart scans (`啟動`) at arbitrary hours; the loop keeps running after hours while the process is up |
| Thu 10-29 14:32:55–14:33:27 | `晨會:…` at 14:33:20 then `心跳已送` + `EOD 完成` at 14:33:23 | a restart at 14:32 ran the missed 晨會 **and** the missed EOD immediately (catch-up) |
| Fri 10-30 11:22:39–11:23:06 | `晨會:…;風險覆蓋 caution` at 11:23 | another late start; the 晨會 runs at startup if not yet done that day |
| Sat 09:30:15 (10-31), 09:30:25 (08-15) | `[data] 0050.TW 本次最新日期 2026-10-29 落後快取 2026-10-30(疑似劣化回應),保留舊快取` then `[ai] AI 呼叫失敗(opus,…)` | weekly review at Sat 09:30: refresh data, then an opus call (`weekly_review.generated_at 2026-08-01T09:30:20` is the last success) |
| Sat 10:00:14–10:00:31 (10-31), 10:00:24–10:00:43 (08-15) | `開始調參:walk-forward champion/challenger…` → `[tuner] 調參維持現任參數 v9:…(門檻 +2%,嘗試 59 組)` | tuner at Sat 10:00, ~17 s for 59 candidates; `params_history.adopted_at` 10:00–10:01 on 11 Saturdays, plus 7 off-schedule runs (14:12–17:56 on weekdays = auto-trigger / manual) |
| Sat 14:15:21 (10-31), 14:15:31 (08-15) | `心跳已送(…)`, `EOD 完成:更新 9 檔資料,記錄 0 筆預測,兌現 6 筆。`, AI daily-report attempt, bake, commit | EOD also runs on non-trading days (Sun 08-02 produced an AI report at 14:16:11) |
| Fri 09-25 09:02:37 | two `FILLED` autopilot orders | no symbol has a bar for 09-25: the live engine scanned and filled on a non-trading day using stale quotes — a defect the rebuild must not reproduce (§3.8) |

### 2.2 Canonical trading-day timeline (what the rebuild should do, in order)

| Taipei | Step | Produces | Confidence |
|---|---|---|---|
| 08:30 | 晨會 morning brief: overnight (`夜盤`, `TSM`, `費半`), 3-day calendar events, macro news count; sets the day's override (`無覆蓋` / `風險覆蓋 caution`) used by gate G3 | 1 `engine` INFO event | high |
| 09:00 → 13:30 | intraday scans every `scan_interval_min` (5): quotes, scoring, recommendation-change events (`{code} {name}:{old}→{new}`), autopilot orders & gate events, news refresh ≈ every 30 min per symbol with AI summaries, bake of `data.json`/`symbol/*.json`/`orders.json`/`events.json`/`simple.html` after each scan (`本頁每次掃描後自動更新`) | orders, events, bakes | high |
| ≈13:33 | 收盤定盤掃描: re-price with exchange closing prices | 1 INFO event | high |
| 14:15 | EOD: market state (`市場狀態:halt(…)` when triggered), heartbeat, final daily bars + prediction recording/resolution (`記錄 54 筆預測,兌現 n 筆` = 9 symbols × 3 horizons × 2 models), calendar sync (`行事曆同步:TWSE 除權息 n 筆` + 30-day warnings), model-health update, reward/month settlement, auto-tune trigger on quality drop, AI notes + daily report (opus), bake, git publish | events, all JSON, commit | high |
| after EOD | shadow ledger advance (row for T−1) + panel bake | `shadow.json` | medium (timing) |
| after hours | the loop keeps scanning while the process lives; off-hours scans only matter for news/recommendation changes | events | high (observed), low (intended) |

### 2.3 Saturday timeline

09:30 weekly review (data refresh → opus → `ai_report.weekly_review{week, generated_at, text}`), 10:00 tuner (`開始調參…` → `調參採用新參數 v{n}:…` / `調參維持現任參數 v{n}:…`, `params_history` row), 14:15 EOD without new bars (`記錄 0 筆預測`), heartbeat, AI daily-report attempt, bake + commit. No scans, no orders, no shadow bake.

### 2.4 Sunday and holidays

EOD ran on Sunday 2026-08-02 (AI report `generated_at 2026-08-02T14:16:11+08:00`); nothing else is observed for Sundays. The engine has no holiday awareness (09-25 orders). `market.is_open` is `false` and `label` `收盤` in every bake we have (both are Saturday 14:15 bakes).

### 2.5 Restarts

On process start the engine runs the 晨會 if none was logged today, then a scan with `last_scan_kind "啟動"`, then a catch-up EOD if 14:15 has passed and today's EOD has not run (10-29). This is the only `last_scan_kind` value observed; 01 §14.3 / 06 §7 propose the vocabulary `啟動 / 盤中 / 收盤定盤 / EOD`.

### 2.6 AI call policy (events `news` / `ai` / `tuner`)

| Caller (event `source`) | Model alias (`engine.ai.model_fast/model_deep`) | When | Output |
|---|---|---|---|
| `news` | `sonnet` | each news refresh (~every 30 min while scanning, and at EOD) | `symbol.news` summaries / scores |
| `ai` | `opus` | after EOD: 9 per-symbol `ai_note`s + `ai_report` (sequential); Sat 09:30 weekly review | notes, report, review |
| `tuner` | `opus` | right after the tuner result | commentary (never succeeded in our windows) |

Failure handling (**high**): each failure logs `AI 呼叫失敗({alias},rc={rc}):{stderr tail}` (`rc` was the CLI's exit code; the Aug rows have an empty tail); after **3 consecutive failures** the engine logs `AI 連續失敗 3 次,暫停 AI 呼叫 15 分鐘(期間自動改用非 AI 路徑)` and suspends **all** AI calls for 15 minutes, using the rule-based path meanwhile; the next caller that needs AI after the pause retries — which is why `news` and `ai` attempts alternate at 15-minute spacing all day. The health block tracks `ai_last_success`, `ai_last_error{ts, model, rc, error}`, `ai_days` and the red light `AI 日報 {ai_days} 天未產生` (01 §4.2).

### 2.7 Heartbeat

Sent once per EOD, before `EOD 完成` (14:15:26 / 14:33:23 / 14:15:21): `[heartbeat] INFO 心跳已送(FAIL:{red joined})` when `engine.health.red` is non-empty, presumably `心跳已送(OK)` otherwise (unobserved). The viewer titles say what it is: `監控紅燈:每日 EOD 會把它送到外部心跳的 /fail 端點` and `HEARTBEAT_URL 未設定:主機失聯時沒有人會收到通知` — a healthchecks.io-style URL: `GET $HEARTBEAT_URL` for OK, `GET $HEARTBEAT_URL/fail` with the red strings as body for FAIL; `health.configured = (HEARTBEAT_URL is set)`. The `heartbeat` source and `engine.health` did not exist in Aug (added with `app.css?v=20260906a`).

### 2.8 Snapshot publishing (git)

| Item | Observed | Confidence |
|---|---|---|
| Files in a snapshot commit | `data.json orders.json events.json model-health.json shadow.json simple.html symbol/{0050,2308,2317,2330,2454,2881,2882,3481,6789}.json` (+ viewer files when they changed); never a state directory — the engine state was never in the repo, which is why it is lost | high |
| Commit message | `snapshot {ISO}` where ISO is the **commit** time (`2026-10-31T14:15:24+08:00`, 2 s after `generated_at 14:15:22`) | high |
| Author / committer | `tw-quant <tw-quant@localhost>` for both | high |
| History shape | only two snapshot commits survive for ~11 weeks of daily publishing, and both have `author date ≠ committer date` (`8623d98`: author 2026-09-08T00:33:41+09:00, committer 2026-10-31T15:15:24+09:00; `2e74138`: author 07-16, committer 08-15) → the engine **amended** one rolling commit and force-pushed; a new commit was started only when the viewer files changed | medium |
| Host clock | committer offsets are `+09:00` while every engine timestamp is `+08:00` → the engine formatted times with an explicit `Asia/Taipei` zone, not the host's local zone | high |
| Pages | the repo root is the site (`.nojekyll`, `index.html`); the viewer re-reads the JSON every 5 min (`VIEWER ? 300000`), so publish latency ≤ 5 min is "live enough" | high |
| `engine.health.share_days` | days since the last successful publish, measured before the day's publish (`1` on both Saturday bakes) | medium |

### 2.9 Time and number formatting (summary)

`datetime.now(ZoneInfo("Asia/Taipei")).isoformat(timespec="seconds")` → `2026-10-31T14:15:22+08:00` (never microseconds, never `Z`); quote `ts` and `last_scan`/`next_scan` carry `:00` seconds in Oct but `:42` in Aug (`20:50:42`) — emit the real second, the viewer slices `[11:19]`. Dates `YYYY-MM-DD`, ISO week `2026-W31`, months `2026-10`. Event `id` is a global monotonically increasing integer (6762 at 10-31, 1094 at 08-15 ≈ 74/day); the bake keeps the last 100 and `last_id`.

---

## 3. GitHub Actions design (proposal for the rebuild)

### 3.1 Facts the design must respect

| Fact | Consequence |
|---|---|
| Cron is UTC; Taipei = UTC+8, no DST | `09:00` Taipei = `01:00` UTC; the engine still computes all stamps with `ZoneInfo("Asia/Taipei")` (§2.8 host-clock lesson) |
| Scheduled runs are delayed under load (minutes, occasionally much more) and can be skipped; minimum interval 5 min | the engine decides what to do from the **Taipei clock at run time**, not from the cron slot; every run is idempotent; no run depends on the previous one having happened |
| GitHub disables `schedule` triggers in a repository after 60 days without activity, and after the workflow file is on a non-default branch | keep the workflow on the default branch; the daily bot commit should count as activity but the heartbeat (dead-man switch) is the real guard — if the external monitor fires, re-enable the workflow manually |
| `concurrency.group` serialises runs; with `cancel-in-progress:false` one run waits in the queue and a further one replaces the waiting one | scans are safe to drop; EOD/tune never run concurrently with a scan |
| Pushes made with `GITHUB_TOKEN` do not trigger other `on: push` workflows, but GitHub Pages "deploy from a branch" still rebuilds | no CI loop; if Pages does **not** rebuild on bot pushes in practice, switch to the `actions/deploy-pages` artifact flow (needs `pages: write`, `id-token: write`) or a fine-grained PAT |
| Everything on the branch is public (`.nojekyll`, root site) | `state/` must contain no secrets; the paper account is public anyway |
| A job may run ≤ 6 h; the free quota is unlimited for public repos, 2 000 min/month for private | ≈ 10 scans × 2 min + EOD 5 min + Sat 10 min ≈ 600–700 min/month |
| Each run is a cold process | there is no in-process 5-minute loop; `scan_interval_min` becomes the cron spacing (30); `last_scan_kind` is `盤中`/`收盤定盤`/`EOD`/`晨會`, `啟動` is reserved for `workflow_dispatch` |
| TWSE holidays are unknown to cron | §3.8 |
| Outbound network is unrestricted on hosted runners | §3.9 |

### 3.2 Schedule mapping

| Original (Taipei) | Mode | UTC cron | Runs/week | Notes |
|---|---|---|---|---|
| 08:30 晨會 | `morning` | `30 0 * * 1-5` | 5 | optional; may be folded into the first scan (`morning` runs inside `scan` when no 晨會 event exists for today) |
| 09:00–13:30 every 5 min | `scan` | `*/30 1-5 * * 1-5` | 50 | 01:00, 01:30, …, 05:30 UTC = 09:00 … 13:30 Taipei (10/day); the 05:30 slot acts as `收盤定盤` when the Taipei clock is ≥ 13:30 |
| ≈13:33 收盤定盤 | (inside `scan`) | — | — | see above |
| 14:15 EOD | `eod` | `15 6 * * 1-5` | 5 | runs on holidays too (records 0 predictions, heartbeat, bake, commit) |
| Sat 09:30 weekly review + 10:00 tuner (+ Sat 14:15 EOD) | `tune` | `0 2 * * 6` | 1 | review → tuner → Saturday bake + commit (keeps `資料時間` and `share_days` fresh on Saturdays as observed) |
| Sunday EOD | — | — | — | dropped (§4) |
| any | `workflow_dispatch` | — | — | manual `mode`, `dry_run`, `as_of` |

### 3.3 Workflow file (`.github/workflows/engine.yml`)

```yaml
name: tw-quant engine

on:
  schedule:
    - cron: '30 0 * * 1-5'      # 08:30 Taipei  晨會
    - cron: '*/30 1-5 * * 1-5'  # 09:00–13:30 Taipei  盤中掃描 (10 slots)
    - cron: '15 6 * * 1-5'      # 14:15 Taipei  EOD
    - cron: '0 2 * * 6'         # Sat 10:00 Taipei  週檢討 + 調參 + 週六快照
  workflow_dispatch:
    inputs:
      mode:
        description: 'auto = derive from clock; or morning | scan | eod | tune | bake | replay'
        type: choice
        options: [auto, morning, scan, eod, tune, bake, replay]
        default: auto
      dry_run:
        description: 'run everything but do not commit/push; upload outputs as an artifact'
        type: boolean
        default: false
      as_of:
        description: 'Taipei date YYYY-MM-DD for replay/offline (uses fixtures/<date>/)'
        type: string
        default: ''

permissions:
  contents: write

concurrency:
  group: tw-quant-engine        # one engine run at a time, repository-wide
  cancel-in-progress: false

env:
  PYTHONUNBUFFERED: '1'
  TWQ_TZ: Asia/Taipei

jobs:
  engine:
    runs-on: ubuntu-latest
    timeout-minutes: 40
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 1          # enough for `pull --rebase` of one new commit

      - uses: actions/setup-python@v5
        with:
          python-version: '3.13'
          cache: pip
          cache-dependency-path: requirements.txt

      - run: pip install -r requirements.txt

      - name: Decide mode
        id: mode
        run: |
          python -m engine.schedule decide \
            --event "${{ github.event_name }}" \
            --cron "${{ github.event.schedule }}" \
            --mode "${{ inputs.mode || 'auto' }}" \
            --as-of "${{ inputs.as_of }}" >> "$GITHUB_OUTPUT"
          # prints: mode=<morning|scan|eod|tune|bake|replay|skip>  kind=<晨會|盤中|收盤定盤|EOD|啟動>  reason=<text>

      - name: Run engine
        if: steps.mode.outputs.mode != 'skip'
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}   # optional
          HEARTBEAT_URL: ${{ secrets.HEARTBEAT_URL }}           # optional
          TWQ_DRY_RUN: ${{ inputs.dry_run == true && '1' || '0' }}
          TWQ_AS_OF: ${{ inputs.as_of }}
        run: python -m engine run --mode "${{ steps.mode.outputs.mode }}" --kind "${{ steps.mode.outputs.kind }}"

      - name: Publish snapshot
        if: steps.mode.outputs.mode != 'skip' && inputs.dry_run != true
        run: |
          git config user.name  "tw-quant"
          git config user.email "tw-quant@localhost"
          git add -A -- state data.json orders.json events.json model-health.json shadow.json simple.html symbol
          if git diff --cached --quiet; then echo "no changes"; exit 0; fi
          ISO=$(python -c 'import datetime,zoneinfo;print(datetime.datetime.now(zoneinfo.ZoneInfo("Asia/Taipei")).isoformat(timespec="seconds"))')
          git commit -m "snapshot $ISO"
          for i in 1 2 3; do
            git pull --rebase origin "$GITHUB_REF_NAME" && git push origin "HEAD:$GITHUB_REF_NAME" && exit 0
            sleep 15
          done
          echo "push failed after 3 attempts" >&2; exit 1

      - name: Upload dry-run outputs
        if: inputs.dry_run == true
        uses: actions/upload-artifact@v4
        with:
          name: dry-run-${{ github.run_id }}
          path: |
            data.json
            orders.json
            events.json
            model-health.json
            shadow.json
            simple.html
            symbol/
            state/
          retention-days: 7
```

A second, trivial workflow `test.yml` (`on: [push, pull_request]`, `python -m pytest`) runs the offline replay tests of §3.10; it never needs secrets or network.

### 3.4 `engine.schedule decide`

```
now = TWQ_NOW (fixed clock in replay) or datetime.now(Asia/Taipei)
if event == workflow_dispatch and mode != auto: return mode, kind=啟動 (bake/replay: kind unchanged)
cron → mode:  '30 0 * * 1-5' → morning | '*/30 1-5 * * 1-5' → scan | '15 6 * * 1-5' → eod | '0 2 * * 6' → tune
scan: kind = 收盤定盤 if now.time() >= 13:30 else 盤中
morning/scan: if not trading_day(now.date()): return skip, reason="非交易日"     # §3.8
eod/tune: never skipped
```

### 3.5 What each mode does (mapping §2.2 onto cold runs)

| Mode | Steps (in order) | Events / files touched |
|---|---|---|
| `morning` | load state → overnight/macro fetch → write the day's override → bake `data.json` (engine block) → commit | `晨會:…` |
| `scan` | if no 晨會 today: run it first → quotes (Yahoo) for 9 symbols + `^TWII` → `quote_fresh` per §3.9 → indicators/scores (specs 04/05) → recommendation-change events → autopilot (06) → news refresh for symbols whose cache is older than 30 min (AI summary if a key is set and no pause is active) → bake all published files with `engine.last_scan = now`, `last_scan_kind = kind`, `next_scan = next cron slot`, `scan_interval_min = 30` → commit | `{code} {name}:{old}→{new}`, `閘門攔截 …`, `紙上買單成交:…`, `收盤定盤掃描完成:…` (for kind 收盤定盤) |
| `eod` | daily bars (final) → `市場狀態:…` → heartbeat → predictions record/resolve → `EOD 完成:…` → calendar sync + 30-day warnings → model-health → reward month settlement → quality check / auto-tune → AI notes + daily report (opus; `非 AI 路徑` otherwise) → shadow: append row for T−1 (if not sealed) + panel bake → bake everything → commit | all of §2.2 |
| `tune` | weekly review (Sat 09:30 semantics: refresh bars, opus review → `ai_report.weekly_review`) → `開始調參:…` → walk-forward champion/challenger → `調參採用新參數 v{n}:…` / `調參維持現任參數 v{n}:…` + `params_history` row → heartbeat → bake (`記錄 0 筆預測`) → commit | as observed on Saturdays |
| `bake` | re-render every published file from `state/` without fetching anything (repair tool) | — |
| `replay` | §3.10 | — |

The AI pause of §2.6 is kept but scoped to the run (`state/ai_pause_until` persists it across runs so a 15-minute pause started at the end of one scan still applies to the next). News AI calls are bounded to at most one summary per symbol per scan (≤ 90 sonnet calls/day) — §4 lists the cheaper alternative.

### 3.6 State persistence and the commit protocol

`state/` is committed next to the published files (the only durable storage a hosted runner has). Proposed layout — small JSON/JSONL files that diff well; no SQLite binary in git:

```
state/
  engine.json          counters & flags: next_event_id (6763), next_order_id (109), params_version (9→10),
                       last_scan, last_scan_kind, ai_pause_until, ai_last_success, ai_last_error, last_publish
  account.json         cash, positions[], realized_pnl, peak per position (06)
  orders.jsonl         every order (bake = last 50 → orders.json)
  events.jsonl         every event (bake = last 100 + last_id → events.json)
  predictions.jsonl    model-health predictions and resolutions
  params_history.json  ids 1–25 (seeded) + new rows
  calendar.json        TWSE dividend events, holiday list (§3.8)
  cache/bars/<code>.json  cache/news/<code>.json  cache/t86/<date>.json  cache/twii.json
  shadow/spec.json  shadow/seal.json  shadow/ledger.jsonl  shadow/fills_a.jsonl  shadow/fills_b.jsonl
  ai/report.md  ai/notes/<code>.json  ai/weekly.md
```

Commit protocol (the `Publish snapshot` step): stage `state/` and the published files only → skip when nothing is staged → one commit `snapshot {ISO}` by `tw-quant <tw-quant@localhost>` → `git pull --rebase` → push, 3 attempts. The original engine amended a rolling commit (§2.8); the rebuild uses ordinary commits as the task requires (≈ 12/day on trading days, ≈ 1 MB working set, text diffs). If history size becomes a problem, add a manual `squash` dispatch that rewrites the branch to a single commit — never automatically.

Counters must continue from the surviving snapshot: events from `6763`, orders from `109`, `params_history.id` from `26`, `version` from `10` (after the manual adoption), `reward.history` and `model-health.series` seeded from the published files (specs 01/03).

### 3.7 Secrets, variables, permissions

| Name | Kind | Required | Used for | Behaviour when absent |
|---|---|---|---|---|
| `ANTHROPIC_API_KEY` | secret | no | news summaries (`sonnet`), notes/report/review/tuner commentary (`opus`) via the Anthropic API (`api.anthropic.com`, Python SDK `anthropic`); aliases map `sonnet → claude-sonnet-5-5`, `opus → claude-opus-5-5` while `engine.ai.model_fast/model_deep` keep publishing the aliases | `engine.ai.enabled false`; rule-based path everywhere; no `AI 呼叫失敗` noise; `health.ai_enabled false` and no AI red light |
| `HEARTBEAT_URL` | secret | no | `GET` on EOD (`/fail` when `red` non-empty) | `health.configured false` (the live dashboard shows `心跳未設定`; the viewer hides it) |
| `GITHUB_TOKEN` | automatic | yes | checkout + push | — |
| `permissions: contents: write` | workflow | yes | push to the default branch | — |
| `TWQ_DRY_RUN`, `TWQ_AS_OF`, `TWQ_NOW`, `TWQ_OFFLINE` | env | no | §3.10 | — |

A failed heartbeat or AI call never fails the job; a failed push does (so the run shows red and the next run retries from the committed state).

### 3.8 Trading-day and holiday handling

Cron cannot know TWSE holidays (observed non-bar weekdays: 09-25, 09-28, 10-09, 10-23, 10-26). Proposed, in order:

1. `state/calendar.json.holidays[]` — a hand-maintained list, refreshed by the Saturday job from TWSE's holiday schedule endpoint when reachable (§3.9); a date in the list → `skip`.
2. **No new bar ⇒ holiday** (the rule the task asks for): the scan fetches `^TWII` (`range=5d&interval=1d` plus `meta.regularMarketTime`); if the latest bar / market time is **before today** and the Taipei clock is ≥ 09:05, the day is treated as closed → `skip` with reason `非交易日`, no commit, no event (a single job-log line). Before 09:05 the first slot may legitimately see no bar yet (the slot runs at 09:00 + jitter): retry once after 60 s, then skip.
3. A `skip` never writes state, so an unexpected closure (typhoon day) costs nothing; EOD still runs that day and records `記錄 0 筆預測` like a Saturday.
4. Orders are only ever filled on a day whose quote is fresh (`quote_fresh true`), which closes the 09-25 defect of §2.1.

### 3.9 Network hosts and fallback behaviour

| Host / endpoint | Used by | Cadence | On failure (timeout, non-200, malformed, or "degraded" = newer cache than response) |
|---|---|---|---|
| `query1.finance.yahoo.com` / `query2.finance.yahoo.com` `/v8/finance/chart/{symbol}` (`2330.TW`, …, `^TWII`; `TSM`, `^SOX` for the 晨會 lines `TSM` / `費半`) | bars, quotes, index | every run | keep `state/cache/bars/<code>.json`; event `[data] WARN` `{symbol} 本次最新日期 {resp_last} 落後快取 {cache_last}(疑似劣化回應),保留舊快取` (verbatim template) or `{symbol} 下載失敗({exc}),保留舊快取` (proposed); the symbol's `quote_fresh = false` and `price` = cached close; no buy orders for that symbol (gate G1); retries 3× with backoff and a browser `User-Agent` |
| `news.google.com` `/rss/search?q={name}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant` | news per symbol, 宏觀新聞 | ≤ every 30 min per symbol | keep cached items/score; `[news] WARN` `{code} 新聞更新失敗({exc}),沿用快取` (proposed); no AI call for that symbol |
| `www.twse.com.tw` `/rwd/zh/fund/T86?date={YYYYMMDD}&selectType=ALL&response=json` | chips (三大法人), EOD | daily | keep `cache/t86`; chips unchanged; `[data] WARN` |
| `www.twse.com.tw` dividend / ex-rights schedule and `holidaySchedule` (exact paths: §4) | `行事曆同步:TWSE 除權息 n 筆`, holiday list | EOD / Sat | keep `state/calendar.json`; `[engine] WARN 行事曆同步失敗({exc})` (proposed) |
| `api.anthropic.com` | AI (§2.6) | after EOD, Sat, news | `AI 呼叫失敗({alias},rc={code}):{message}` → 3 in a row → 15-minute pause → `非 AI 路徑`; notes/report keep their last successful values (`ai_note.ts` stays old, red light counts up) |
| `$HEARTBEAT_URL` host | heartbeat | EOD | `[heartbeat] WARN 心跳送出失敗({exc})` (proposed); never fatal |
| `github.com` | checkout / push | every run | push retried 3×, then the job fails |

### 3.10 Dry-run and replay/offline mode

* **Dry run** (`workflow_dispatch` with `dry_run: true`, or `TWQ_DRY_RUN=1` locally): the engine does everything including network and AI, writes the published files and `state/`, but the publish step is skipped and the outputs are uploaded as a workflow artifact; the runner is discarded, so nothing persists. Heartbeat is **not** sent in dry run.
* **Offline replay** (`python -m engine run --mode eod --offline --as-of 2026-10-30`, env `TWQ_OFFLINE=1 TWQ_NOW=2026-10-30T14:15:22+08:00`): every fetch is served from `fixtures/<as_of>/{bars,news,t86,calendar}/…` (recorded raw responses; `python -m engine record --as-of …` captures them from live runs), the clock is frozen at `TWQ_NOW`, AI and heartbeat are disabled, and `state/` is read from a fixture copy. `pytest` compares the produced files with golden copies (the surviving 2026-10-31 snapshot is the first golden set: the shadow bake must reproduce the 55 rows, `data.json` must match field-for-field per 01 §0). This is how the viewer-compatibility of every change is checked before it reaches the branch.

### 3.11 What changes relative to the original process (viewer-visible or not)

| Change | Viewer impact |
|---|---|
| 30-minute scans instead of 5-minute | none (`scan_interval_min`/`next_scan` unused in the viewer); stops/trails fire with up to 30 min delay; order timestamps land at :0x/:3x |
| cold start per run, no after-hours scans | `last_scan` stays at the 13:30-slot or 14:15 bake; `last_scan_kind` becomes meaningful (`盤中`/`收盤定盤`/`EOD`) |
| synchronous shadow bake inside EOD | `shadow.json.generated_at` = EOD time; `computing` always `false` |
| no Sunday EOD | `資料時間` Sunday unchanged (Saturday bake remains) |
| AI via API key instead of the CLI's OAuth | error text in `AI 呼叫失敗(…)` becomes the SDK's exception message |

### 3.12 First deployment checklist

1. Commit the engine, `requirements.txt`, `.github/workflows/engine.yml`, `fixtures/2026-10-31/`, and `state/` seeded from the surviving snapshot (§1.10, §3.6) on the default branch.
2. Apply the manual shadow seal (§1.8) and the v10 adoption before the first scheduled run, or decide to let the window run on (§4).
3. Add the optional secrets; run `workflow_dispatch` with `mode: bake, dry_run: true` and compare the artifact with the current files; then `mode: eod, dry_run: false` on a weekday after 14:15 Taipei.
4. Confirm Pages rebuilt after the bot commit (open `index.html`, `資料時間` updates); otherwise switch the publish step to `actions/deploy-pages`.
5. Create the heartbeat check with a 36-hour grace period so a silently disabled schedule is noticed.

---

## 4. Open questions (with proposed defaults)

1. **`state_key` / hash-chain inputs.** Only the hash length (SHA-256) and "changes with the ledger" are known. *Default:* §1.3 definitions.
2. **Leg pass rules for `safety` and `return`.** Observed only `pass:true`. *Default:* `safety`: `not doom and mdd_b ≤ max(1.5 × mdd_a, 0.10)`, `doom = min(eq_b) ≤ 0.8 × eq_b[0]`; `return`: `diff > 0`.
3. **`reject_rate`, `n_starved`, M3 formula.** Always 0 / 0; slippage ≈ 10 bp + √-impact (§1.5). *Default:* reject = fill impossible (limit-up/down bar or zero volume); starved = BUY decision sized to 0 shares; slippage `10 bp + 3.2 bp × sqrt(qty/volume × 1e4)` on the open, adverse sign.
4. **`eq_b[0] = 1000015.36`** (+15.36 before B's first fill on 08-10). Unexplained; the leg base is row 0 so it has no effect. *Default:* seed the ledger from the archived rows; new experiments start at exactly `initial_cash`.
5. **Why the Oct ledger lags one bar date (T−1).** *Default:* keep T−1 for replay parity; a new experiment may append T at EOD (viewer-neutral).
6. **Automatic verdict strings** (`adjudicated`, `next`). Unobserved. *Default:* §1.8 automatic block.
7. **Shadow bake timing** (14:50 vs 20:44 observed). *Default:* synchronous inside EOD (§3.5).
8. **`warnings[]` vocabulary.** Unobserved. *Default:* §1.9.
9. **Heartbeat OK text and endpoint shape.** `心跳已送(OK)` and healthchecks.io `/fail` are inferred from the viewer title. *Default:* as §2.7; configurable `HEARTBEAT_FAIL_SUFFIX` (`/fail`).
10. **Sunday EOD and Saturday EOD at 14:15.** The task scopes `eod` to Mon–Fri; the original ran every day. *Default:* Saturday bake inside the `tune` job; no Sunday run; `share_days` therefore reaches 2 on Sundays (would trip the proposed red light of 01 §14.4 → raise that threshold to 3 or exclude Sundays).
11. **Morning brief sources** (`夜盤` = TAIEX futures night session, `TSM`, `費半`). The night-session source is unknown. *Default:* `TSM` and `^SOX` from Yahoo; `夜盤` from Yahoo `WTX=F`-style symbol if available, else `無資料` (the string observed on 10-29: `晨會:夜盤 無資料、…`).
12. **Exact TWSE endpoints** for the dividend calendar and holiday schedule. *Default:* `https://www.twse.com.tw/rwd/zh/exRight/TWT49U?response=json` (ex-rights/dividend schedule) and `https://www.twse.com.tw/rwd/zh/holidaySchedule/holidaySchedule?response=json`; verify at implementation time, fall back to a hand-maintained `state/calendar.json`.
13. **News AI cost cap.** The original summarised news with `sonnet` roughly every 30 min. *Default:* at most one summary per symbol per scan when the item list changed; alternative: only at `morning` and `eod` (2×/day).
14. **Run-to-run AI pause.** The 15-minute pause was in-process. *Default:* persist `ai_pause_until` in `state/engine.json` (§3.5).
15. **Repository growth.** ~12 commits/day. *Default:* accept; optional manual `squash` dispatch.
16. **Pages rebuild on `GITHUB_TOKEN` pushes.** Expected to work for branch-sourced Pages. *Default:* verify on first deployment (§3.12 step 4); fallback `actions/deploy-pages`.
17. **`last_scan_kind` vocabulary.** Only `啟動` observed. *Default:* `啟動 / 晨會 / 盤中 / 收盤定盤 / EOD` (extends 01 §14.3 with `晨會`).
