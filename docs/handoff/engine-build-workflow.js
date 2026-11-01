export const meta = {
  name: 'tw-quant-engine-build',
  description: 'Implement the rebuilt tw-quant engine modules in parallel against docs/engine-spec.md, then integrate and replay offline',
  phases: [
    { title: 'Implement', detail: 'one agent per module group, golden tests against fixtures/snapshot-2026-10-31' },
    { title: 'Tuner', detail: 'tuner after indicators+scoring exist' },
    { title: 'Integrate', detail: 'pipelines + CLI + offline replay + full pytest' },
  ],
}

const COMMON = `
You are one of several engineers rebuilding the lost "tw-quant" Taiwan-stock paper-trading engine in Python 3.13 inside the repository at /home/user/tw-quant-view (git branch claude/peaceful-volta-teh3h9 is already checked out; DO NOT run git commit/push/checkout/stash/reset — the orchestrator commits).

Authoritative specification: docs/engine-spec.md (read the sections cited for your module in full; the evidence appendices docs/spec/01..08-*.md hold the detailed tables — consult them when the main spec is ambiguous). The static viewer (index.html, app.js, simple.html, app.css) is FROZEN; every published shape, key order, enum string and rounding must match spec §7 byte-for-byte.

Scaffold already in place (read these first, they are the shared contract):
  engine/clock.py   — implemented: Taipei clock, iso(), decide(), is_trading_day(), iso_week(), monday_of()
  engine/state.py   — implemented: State.load()/save(), st.log(level, source, message, at), st.next_id(kind), st.orders/st.events/st.predictions ledgers, st.append_order(), read/write cache helpers, dumps()/write_published_json(), state/ file layout documented in the module docstring, flags offline()/dry_run()/as_of()/fixture_dir()
  engine/<module>.py — stubs with the exact public function signatures and docstrings you must implement (keep the names and signatures; you may add private helpers and extra public functions)
  tests/conftest.py — fixtures: data, orders, events, model_health, shadow, simple_html, symbols ({code: symbol file}), v9_params, tmp_state, frozen_now; CODES list
  fixtures/snapshot-2026-10-31/ — frozen copy of the last real bake (golden data). The repo-root data.json etc. will be overwritten later — always test against the fixture copy.

Environment facts: pandas 3.0.5, numpy 2.5.3, requests, feedparser, anthropic 2.3.0, pytest are installed. There is NO network access to Yahoo/Google/TWSE/anthropic from this sandbox — never rely on live fetches in tests; use fixtures or synthetic data. Python round() is half-even and is load-bearing (spec §1.4). Never emit NaN/Infinity. Chinese strings must be copied verbatim from the spec (watch full-width 、 。 ( ) vs ASCII — the spec marks what is ASCII).

Ownership rules (parallel agents work in the same tree): edit ONLY the files listed under "You own". Do not edit engine/clock.py or engine/state.py; if you need a helper that belongs there, add it as a private helper inside your own module and mention the gap in your report. Do not edit other agents' modules or tests. Run only your own tests: python -m pytest tests/<your test file> -q.

Deliverables: implementation + a pytest file with golden tests against the fixture snapshot proving the reproduction claims of the spec for your module (list exactly which spec claims you verified and which you could not). Keep functions pure where the stub says so. Code comments/docstrings in English; published strings in Chinese per spec. No model identifiers or session links anywhere in the files.

Finish by returning a structured report: files written, tests passing count, spec claims verified, deviations/defaults you chose, open issues the integrator must know (interfaces you assumed from other modules).`;

const REPORT = {
  type: 'object',
  properties: {
    files: { type: 'array', items: { type: 'string' } },
    tests_passed: { type: 'integer' },
    tests_failed: { type: 'integer' },
    verified_claims: { type: 'array', items: { type: 'string' } },
    deviations: { type: 'array', items: { type: 'string' } },
    integration_notes: { type: 'array', items: { type: 'string' } },
    confidence: { type: 'string', enum: ['high', 'medium', 'low'] },
  },
  required: ['files', 'tests_passed', 'tests_failed', 'verified_claims', 'deviations', 'integration_notes', 'confidence'],
}

const JOBS = [
  {
    key: 'indicators',
    prompt: `${COMMON}

You own: engine/indicators.py, tests/test_indicators.py.
Spec sections: §3.3, §4.1, §4.7 (60-min KD), §4.9 (trend segments/summary), §4.10 (sigma20), §4.11 (ATR14); appendix docs/spec/04-indicators-and-technical-signals.md §1–§2 and docs/spec/02-symbol-json-contract.md §9 (trend) for the exact derivations and the warm-up analysis.
Golden tests required: for each of the 9 fixture symbol files, compute(bars) on the 250 published bars and compare the tail where warm-up is complete: ma5/ma20/ma60/bb_up/bb_low exact ≤1e-9 on [59:], rsi ≤1e-9 on [14:], KD ≤1e-6 after ~70 bars (seeded from 50/50 the published values converge), MACD: the published arrays were computed on longer history — verify the recursion holds (macd_sig[i] = macd_sig[i-1]*8/10 + macd[i]*2/10 within 1e-9 and macd_hist == macd - macd_sig) and that EMA12/EMA26 recursions hold on the published macd given back-solved seeds, as the appendix describes. trend(bars, ind) must reproduce segments and summary of all 9 files exactly (segments byte-identical; summary floats to the published precision). atr14 and sigma20 are checked indirectly by other modules — still unit-test them on synthetic data. published() must guarantee finite floats (document what you do when history is shorter than needed: pad by back-filling the first finite value, never NaN).`,
  },
  {
    key: 'scoring',
    prompt: `${COMMON}

You own: engine/scoring.py, tests/test_scoring.py.
Spec sections: §4.2–§4.8, §4.11, §6.1 (base scores and weights), §6.8 (derived v10 numbers), §10.2 Q-A1…Q-A17; appendices docs/spec/04-indicators-and-technical-signals.md §3–§5 (signal inventory, thresholds, note templates) and docs/spec/05-market-fund-news-chips-kd60-scoring.md (market, fundamentals, news, chips, kd60, total/rec_code, suggest_qty).
Golden tests required (all 9 fixture symbols, using fixture indicators{} as input and v9_params): tech_signals reproduces signals[] (indicator/label/score/note byte-exact, order) and tech_total; fund_signals reproduces fund_signals[] and fund_total from a fundamentals dict you reconstruct per the appendix (document the thresholds); chips_block reproduces chips.score/signals/recent given the recent[] rows as history (recent is newest-first, 10 rows; the appendix explains streaks and 法人動能 — reproduce what is reproducible and state what is not); kd60_block reproduces intraday_kd for the published k/d (label/note/score); compose reproduces total/rec_code/rec_text for all 9 rows; suggest_qty reproduces rows[].suggest_qty for all 9 rows given account.cash, price and an ATR14 you compute from bars (implement a local SMA-14 true-range helper in the test; the row values pin the formula); market_block reproduces overview.market for the ^TWII values implied by the snapshot (index/pct given; regime label/score from the rule — document); news_block aggregation per Q-A12 reproduces news.score for the fixture items (use their stored per-item scores and the snapshot time 2026-10-31T14:15:22+08:00 — if the default formula does not reproduce all 9, report which ones and keep the default). Also unit-test lexicon_score on a few Chinese headlines. v10 expectations from §6.8 (e.g. 均線排列 ±3.7, RSI ±1.18, 布林 ±1.28) must hold when the v10 params object (tuner.V10_PARAMS_JSON string in engine/tuner.py — json.loads it) is used.`,
  },
  {
    key: 'forecast',
    prompt: `${COMMON}

You own: engine/forecast.py, tests/test_forecast.py.
Spec sections: §4.10, §7.2 (forecast/ledger shapes), §7.5 (model-health metrics), §10.2 Q-F1…Q-F7, Q-P13, K8; appendix docs/spec/07-forecast-model-health-tuner-reward-events.md §1–§2 and docs/spec/02-symbol-json-contract.md §10–§11 (fan/ledger).
Golden tests required: baseline(bars) reproduces every fixture symbol whose forecast model is baseline to 1e-12 (horizons + fan incl. dates); fan() reproduces the published fan for ridge symbols given the published horizons; ridge() has the right shape/invariants (ci68 = pred ± s, ci95 = pred ± 1.96 s, prob_up = Φ(pred/s)) and is deterministic; record/resolve on a tmp_state with synthetic bars (make bars advance, resolve, check hit/abs_err and idempotent upsert); metrics() merges predictions_seed.json aggregates with new rows exactly as the module docstring says — write a test that seeds a predictions_seed.json built from the fixture model-health.json + symbol ledgers and checks metrics() returns by_model_horizon/champion/series byte-identical to the fixture when there are no new rows, and sensible merged values after adding rows; brief() reproduces overview.model_health_brief; ledger_block reproduces each symbol's ledger with seed only. The seed file format is defined in engine/state.py docstring; a sibling agent writes scripts/seed_state.py that produces it — build your own copy in the test from the fixture files using the same format so both sides agree: {"source": str, "by_model_horizon": [...as published...], "series": [...as published...], "by_symbol": {code: [...symbol ledger.by_horizon rows...]}}. Note champion rule n ≥ 30 (Q-F2) and series keyed by the Monday of the ISO week of the target date (R1).`,
  },
  {
    key: 'broker',
    prompt: `${COMMON}

You own: engine/broker.py, engine/autopilot.py, tests/test_broker.py, tests/test_autopilot.py.
Spec sections: §5.1–§5.7, §7.1 (positions/account/reward shapes), §7.3 (orders shape), §8.2 (broker + gate events), §8.6 (reward), §6.5/§6.8 (v10 exit multipliers and note literals -8%/-21%), §10.2 Q-S1…Q-S10, Q-F8; appendix docs/spec/06-paper-trading-autopilot-rules.md (all) and docs/spec/03-orders-events-health-shadow-contract.md §1 (orders) and docs/spec/07-...md §4 (reward).
Golden tests required: fill_price/fee/tax/pnl reproduce all 50 fixture orders (fee, tax, filled_price exact; pnl of SELLs exact where the lot is reconstructible from in-window BUYs — replay the fixture orders oldest→newest through fill() on a tmp_state seeded with the cash implied before the first in-window order, or at minimum verify fee/tax/filled_price on 50/50 and pnl formula on reconstructible lots, and state which); positions_view reproduces the 4 published positions (avg_price, ret_pct, stop_price, trail_price, value) given quotes = published prices, peaks = published peaks and the v9 params, and the account_view reproduces account exactly (cash, realized_pnl, unrealized_pnl using 2-dp avg); reward_view reproduces data.json overview.reward (history seeded from the fixture; provisional for 2026-10 from equity now and the 2026-09 close); settle_month logic unit-tested on synthetic months (base_points from the unrounded return, new_high strict, beat_market, skipped month). Autopilot: unit tests on synthetic rows for every row of the §5.4 decision table (stop/trail inclusive exits with the §5.2 note strings, signal exit, G1/G3/G4 gates with the exact event strings, swap with the 換股 note and 自動換股 event, ≤3 orders/scan, one add per symbol per day, sizing per §5.6 incl. caution_scale after the cap, min-one-share, 40% cap, round lots, KILL ⇒ no orders but peaks still updated). Use the order-108 example (floor(0.15 × 317175.21 / 245.5) = 193) as a sizing golden case. Order notes under v10 print -8%/-21%.`,
  },
  {
    key: 'seed',
    prompt: `${COMMON}

You own: scripts/seed_state.py, engine/tuner.py ONLY the functions params_json(), sizing(), active_params(), adopt_manual() (leave reward_points/backtest/candidates/tune as NotImplementedError — another agent implements them later; do not restructure the file), engine/shadow.py (all three functions), tests/test_seed.py, tests/test_shadow.py, and the generated directory state/ (run your script to produce it).
Spec sections: §1.2 C3 (counters: next event id 6763, next order id 109, next params id 26, next version 10), §5.1 (account seed: cash 269729.55000000005, realized_pnl -23213.919999999875, 4 positions with unrounded averages re-derived from orders where the lot is in-window else the 2-dp value; peaks as published), §6.2–§6.8 (v10 adoption: exact params_json string = tuner.V10_PARAMS_JSON, params_history row id 26 version 10 adopted 1 with the exact reason string of §6.6, tuner event 調參採用新參數 v10:<reason>), §6.7 (sealing shadow.json: exact verdict object and progress, engine event string in shadow.SEAL_EVENT), §7.5/§7.6 shapes, §9.6 (state layout and seeding rules), Q-P13 (predictions_seed.json aggregates), §8.6 (reward history seed), §8.1 events seed. The state/ file layout is defined in engine/state.py's docstring — follow it exactly (engine.json keys, account.json keys incl. positions[].cost/avg/peak/first_fill/adds, eod_equity, reward; scan.json = last rows; eod.json history with 2026-10-30 totals from the fixture rows; calendar.json with the observed holidays 2026-09-25, 2026-09-28, 2026-10-09, 2026-10-23, 2026-10-26 plus known 2026 TWSE holidays you are confident of; caches: cache/bars/<code>.json from the fixture bars (250 bars — note the real engine had longer history; the datafeed will extend on first live run), cache/news/<code>.json from fixture news (+refreshed_at = generated_at), cache/t86 from fixture chips.recent (10 dates), cache/info left absent, cache/twii.json absent (document), cache/quotes.json from rows price/ts; shadow/panel.json = sealed panel; ai/report.json from ai_report, ai/notes/<code>.json from rows[].ai_note, ai/weekly.json from ai_report.weekly_review if present; predictions_seed.json {"source","by_model_horizon","series","by_symbol"} from model-health.json + symbol ledgers; params_history.json = fixture rows with the v10 row prepended; params.json = v10 object (json.loads(V10_PARAMS_JSON)); engine.json ai_models {"sonnet": "claude-sonnet-5-5", "opus": "claude-opus-5-5"}, last_scan/last_scan_kind from the fixture engine block, market_state "normal", override "無覆蓋", ai_* from health; events.jsonl = the 100 fixture events then the two new events (tuner adoption, shadow seal) with ids 6763/6764 and ts = cutover; orders.jsonl = 50 fixture orders oldest-first).
Cutover time: use 2026-11-01T12:00:00+08:00 (CLI default --cutover). After seeding, engine.json next_event_id must be 6765.
Tests: seed into a tmp dir and assert the counters, the v10 row string equality with V10_PARAMS_JSON, params_history[0] fields, the sealed shadow object (verdict/progress exact, every other key byte-identical to the fixture, key order preserved), account seed numbers, predictions_seed aggregates equal the fixture metrics, idempotency (second run no-op). shadow.seal_manual must be a pure function of (panel, at). Run the script for real at the end to create state/ in the repo (python scripts/seed_state.py) and list the files it wrote.`,
  },
  {
    key: 'publish',
    prompt: `${COMMON}

You own: engine/publish.py, tests/test_publish.py.
Spec sections: §1.5 (serialization), §7.1–§7.8 (every output contract), §7.7 (simple.html template — byte-exact), §8.4 (health), §8.5 (heartbeat), §9.6 (commit protocol), Q-P1…Q-P5; appendices docs/spec/01-data-json-contract.md and docs/spec/03-orders-events-health-shadow-contract.md §5 (simple.html template and md converter).
Golden tests required: render_simple(fixture data.json, v9 params) == fixture simple.html byte-for-byte (this is the hardest and most important test; the appendix proves the converter and formatting rules; also test the previous bake at git commit 2e74138 if you can read it with git show 2e74138:simple.html and 2e74138:data.json — read-only git commands are fine); md_to_html on the fixture report content; build_orders/build_events from a tmp_state seeded with the fixture orders/events reproduce orders.json/events.json byte-identical via state.dumps; build_model_health reproduces model-health.json given metrics + params_history from the fixture; build_data assembles overview/ai_report in the spec key order from a snapshot dict (construct the snapshot from the fixture: rows, symbols, positions, account, reward, brief, market, ai_report) and reproduces fixture data.json byte-identical when engine/health blocks are taken from the fixture (allow injecting the engine block for the test; in production engine_block() computes it); bake_all writes all files to a tmp out_dir, every JSON satisfies the round-trip property, key orders match, symbol files equal snapshot['symbols'][code] serialized, simple.html matches render_simple. health(): unit-test share_days/ai_days/red strings with frozen_now. heartbeat(): monkeypatch requests to assert URL/body and that it never raises and is skipped in dry run/unconfigured. commit_and_push: implement with subprocess (git add -A of the published set + state/, commit "snapshot {ISO}" as tw-quant <tw-quant@localhost>, pull --rebase, push up to 3 tries); test only the no-op paths (dry run, nothing staged) — never actually commit in tests (use a throwaway git repo in tmp_path if you want to test the commit path).`,
  },
  {
    key: 'datafeed',
    prompt: `${COMMON}

You own: engine/datafeed.py, tests/test_datafeed.py, fixtures/README.md (document the fixture layout), and you may create sample fixture files under fixtures/sample/ for tests.
Spec sections: §3.1–§3.5 (source table D1–D10, degraded guard, quotes/quote_fresh, holidays), §8.2 (the data/news WARN strings), §9.9 (offline replay + record), Q-A10, Q-P8, Q-P9, K1; appendix docs/spec/07-forecast-model-health-tuner-reward-events.md §7 (data freshness evidence) and docs/spec/05-...md §3 (news RSS details).
Implementation notes: use requests with the browser User-Agent, 3 attempts with 1/3/9 s backoff (make the sleeps injectable/patchable so tests are fast), per-source cache files exactly as the module docstring lists, Yahoo chart API JSON parsing (timestamps → Taipei dates; adjusted close scaling of OHLC via adjclose/close ratio; volume int; drop rows with null close), 60-minute bars, 1-minute quote aggregation into today's provisional bar, Google News RSS via feedparser (first 8 entries; pubDate RFC-822 → +08:00 iso; source text), TWSE T86 JSON (fields[] + data[][], thousands commas; column names per spec D6 — resolve by header text, not index; verify the header names you expect are documented in the appendix), TWSE ex-dividend TWT49U and holiday schedule (best-effort; degrade gracefully), ^TWII/TSM/^SOX. OFFLINE MODE is mandatory: when state.offline() is true, read fixtures/<as_of>/... (layout in docstring), never open a socket (assert this in a test by monkeypatching requests.get to raise). record_fixtures writes the same layout from live caches/responses. Every failure path logs exactly the WARN strings of §3.2/§8.2 via st.log. Tests: with monkeypatched requests returning canned Yahoo/RSS/T86 payloads (write realistic minimal payloads as test data), verify parsing, the degraded guard (older → keep cache + exact WARN string; equal → replace; newer → replace), quote freshness (fresh only when is_open and age ≤ 20 min), news caching window (30 min), t86 parsing with commas, offline routing to fixtures and fallback to state cache, record_fixtures round-trip (record then offline read gives the same bars).`,
  },
  {
    key: 'ai',
    prompt: `${COMMON}

You own: engine/ai.py, tests/test_ai.py.
Spec sections: §3.6, §3.2 D11, §8.3 (circuit breaker, outputs), §8.2 (AI WARN strings), §7.1 (ai_report shape, engine.ai block), Q-A11, Q-P10, Q-P12, K10; appendix docs/spec/07-forecast-model-health-tuner-reward-events.md §5 (AI evidence) and docs/spec/01-data-json-contract.md (ai_report / ai_note fields).
Use the official anthropic Python SDK (anthropic 2.3.0 is installed): client = anthropic.Anthropic() (reads ANTHROPIC_API_KEY), client.messages.create(model=..., max_tokens=..., system=..., messages=[{"role":"user","content":...}]) — do NOT use thinking parameters or betas, keep it to the plain Messages API so it works on any current model; read the SDK's installed source under site-packages if you need to confirm signatures or exception classes (anthropic.APIStatusError has .status_code; anthropic.APIConnectionError; anthropic.AuthenticationError; anthropic.RateLimitError). Model aliases: ALIASES in the stub are defaults; st.engine["ai_models"] overrides. Prompts (lost — write minimal Chinese prompts that produce the observed shapes): title sentiment → single integer −3..+3 (parse robustly; non-integer → None → caller falls back to the lexicon); per-symbol note → ≤5 short paragraphs separated by blank lines, plain text, must end with NOTE_SUFFIX (append it if the model forgot); daily report → markdown with exactly the five "## " headings in REPORT_HEADINGS order and "- **code name** — …" bullets; weekly review → short markdown. Breaker semantics exactly per §8.3 (global counter in st.engine ai_fail_count/ai_pause_until; third consecutive failure logs the pause line INSTEAD of a failure line and sets pause = now + 15 min; while paused calls return None silently; success resets; pause end resets; ai_last_success / ai_last_error {"ts","model","rc","error"} bookkeeping; rc = HTTP status for APIStatusError, "conn" for connection errors, "exc" otherwise; error tail = last 120 chars of the message). Event source = caller (news|ai|tuner); model name in the message = the alias. Tests: monkeypatch anthropic.Anthropic with a fake client to simulate success/401/429/connection error; assert the exact event strings, the 3-failure pause line, the pause skip, the reset on success, disabled() when no key or offline, note suffix enforcement, report heading enforcement, sentiment parsing.`,
  },
]

phase('Implement')
log(`fan-out: ${JOBS.length} module agents`)
const pending = {}
for (const j of JOBS) {
  pending[j.key] = agent(j.prompt, { label: `impl:${j.key}`, phase: 'Implement', schema: REPORT, agentType: 'general-purpose' })
}

// tuner needs indicators + scoring (it backtests through them); start as soon as both land
const tunerP = Promise.all([pending.indicators, pending.scoring, pending.seed]).then(([ind, sc, seed]) => {
  log('indicators+scoring+seed done → tuner')
  return agent(`${COMMON}

You own: engine/tuner.py functions reward_points(), backtest(), candidates(), tune() (params_json/sizing/active_params/adopt_manual are already implemented by a sibling — keep them), tests/test_tuner.py.
Spec sections: §6.9 (tuner defaults), §6.1–§6.2, §8.2 (tuner events), Q-F6, §4.2/§4.8 (signals and rec_code — reuse engine.scoring.tech_signals/compose and engine.indicators.compute, which are now implemented: read them first), appendix docs/spec/07-forecast-model-health-tuner-reward-events.md §3.
Backtest definition (default, document it): for one symbol, walk the bars day by day from the start of the window; at each day compute tech signals on the history up to that day (use engine.indicators.compute on the full history once and slice, call engine.scoring.tech_signals with a 250-bar window ending at that day), compose with mkt/fund/news/chips/kd60 = 0, go long 100% at next open when rec_code ∈ {BUY, STRONG_BUY} and flat when ∈ {SELL, STRONG_SELL}, fee/tax ignored, equity starts at 1.0; portfolio metric = mean of the per-symbol reward_points over the watchlist (document). Walk-forward windows: train = bars[-250:-60], valid = bars[-60:]. reward_points(curve) = Σ round(daily_ret×1000) + 10 per strict new equity high. candidates(): 64 seeded single-coordinate perturbations (one weight × {0.5,0.75,1.25,1.5} or the four thresholds shifted together by ±0.5 keeping strong = buy+2, sell = −buy), deterministic from the seed string (run date), de-duplicated, never touching fund_cap/use_*/exit/sizing. tune(): champion = incumbent; challenger = best candidate by train metric (include extra_candidate if given); adopt iff valid > champion_valid × 1.02; always writes a params_history row (shape §7.5, id via st.next_id('params'), adopted_at = at, metrics %.3f in the reason strings of §6.9) and logs the tuner event; on adoption updates st.params, engine.params_version, version = active+1. Tests: synthetic bars (deterministic random walk with trend) through backtest/reward_points; candidates determinism and invariants; tune() on a tmp_state seeded with the v10 params (json.loads(V10_PARAMS_JSON)) and 9 synthetic bar series: assert a row is always written, the reason string format, adoption/no-adoption branches by monkeypatching the metric, that exit/sizing/fund_cap/use_* are untouched in any candidate, and that params_json(st.params) stays byte-identical to V10_PARAMS_JSON when nothing is adopted. Keep runtime of tune() under ~60 s for 9 symbols × 64 candidates (vectorise or cache the indicator computation per symbol).

Sibling reports for context — indicators: ${JSON.stringify(ind?.integration_notes || [])}; scoring: ${JSON.stringify(sc?.integration_notes || [])}; seed: ${JSON.stringify(seed?.integration_notes || [])}.`,
    { label: 'impl:tuner', phase: 'Tuner', schema: REPORT, agentType: 'general-purpose' })
})

const results = {}
for (const j of JOBS) results[j.key] = await pending[j.key]
results.tuner = await tunerP
for (const [k, r] of Object.entries(results)) {
  log(`${k}: ${r ? `${r.tests_passed} passed / ${r.tests_failed} failed, confidence ${r.confidence}` : 'NO RESULT'}`)
}

phase('Integrate')
const notes = Object.entries(results).map(([k, r]) => `## ${k}\n` + (r ? [
  `files: ${r.files.join(', ')}`,
  `tests: ${r.tests_passed} passed, ${r.tests_failed} failed (confidence ${r.confidence})`,
  `deviations: ${r.deviations.join(' | ') || '-'}`,
  `integration notes: ${r.integration_notes.join(' | ') || '-'}`,
].join('\n') : 'agent returned nothing — inspect the module yourself')).join('\n\n')

const integ = await agent(`${COMMON}

You are the INTEGRATOR. All module agents have finished; their reports follow. You own: engine/pipelines.py, engine/__main__.py, tests/test_pipelines.py, tests/test_golden_bake.py, fixtures/2026-10-31/ (an offline replay fixture set you create from state/ caches), and you MAY make minimal glue fixes in any engine module when interfaces disagree (keep each fix small, keep the owning module's tests green, and list every cross-module edit in your report).

Goal: a working end-to-end engine. Implement engine/pipelines.py per spec §9.3–§9.4 and §9.9:
- build_snapshot(st, at, kind, refresh): for each watchlist symbol read cache bars (datafeed.daily_bars when refresh else the cache), compute indicators (full history → published 250), tech/fund/news/chips/kd60 blocks from caches, market block from cache/twii.json (if absent: keep st.engine["market"] from the seed and document), compose total/rec_code/changed (vs st.scan rows), trend, forecast (champion["5"] model for all horizons; the ridge model needs the indicators), ledger_block, ai_note from ai/notes; rows[] in watchlist order with the exact key order of §7.1; positions/account/reward via broker; model_health = forecast.metrics(st); brief; ai_report from ai/report.json + ai/weekly.json. quotes: in refresh mode datafeed.quote, otherwise cache/quotes.json; rows[].price must equal bars[-1][4] after the close (spec §7.2 consistency list — enforce it).
- run_morning / run_scan / run_eod / run_tune / run_bake exactly in the step order of §9.4 (EOD: bars refresh with degraded guard → ^TWII state (市場狀態 event on change) → fundamentals/T86/60-min → marks → health + heartbeat → forecasts record/resolve → "EOD 完成:更新 {n} 檔資料,記錄 {p} 筆預測,兌現 {r} 筆。" → calendar sync + 30-day WARNs → metrics → reward settlement → quality check (→ tuner.tune) → AI report + notes (skipped when ai disabled) → shadow step skipped when sealed → bake → commit). Scan: skip when not a trading day per clock + "no new ^TWII bar" rule (document how you detect it offline). Everything must degrade without network. run(mode, kind) loads State, dispatches, saves state, bakes via publish.bake_all, calls publish.commit_and_push unless dry run; wrap each step so an exception logs an ERROR event "{step} 失敗:{exception}" and the run continues to the bake (spec §8.1) — but let a failure in the bake itself propagate (exit 1).
- Offline replay: create fixtures/2026-10-31/ from the seeded state caches (bars, news, t86, quotes; twii absent → document) so that TWQ_OFFLINE=1 TWQ_AS_OF=2026-10-31 TWQ_NOW=2026-10-31T14:15:22+08:00 TWQ_DRY_RUN=1 python -m engine run --mode bake works, and so does --mode eod (records 0 predictions because the bars have no new date; heartbeat skipped).
Golden integration test (tests/test_golden_bake.py): copy state/ to a tmp dir, run run_bake with TWQ_NOW = the snapshot time, and compare the produced files with fixtures/snapshot-2026-10-31: every JSON round-trips; data.json rows[] match the fixture on every field EXCEPT the ones that legitimately change under v10 (tech_total, total, rec_code/rec_text/changed, signal scores, suggest_qty, stop/trail prices, params_version, engine.ai/health/next_scan/scan_interval_min, generated_at/ts) — assert those differ in the expected direction (e.g. 均線排列 score magnitude 3.7, params_version 10, stop multiplier 0.9169941806239077) and that everything else (bars, indicators, trend, forecast for baseline symbols, chips, news, kd60, ai_note, account cash/realized, positions qty/avg/peak, reward, model_health_brief, params_history[0] = v10 row, shadow.json sealed) is byte-identical or numerically identical; simple.html renders with -8%/-21%; events.json ends with the two cutover events. Then run the WHOLE test suite (python -m pytest -q) and fix failures (yours or interface mismatches; keep module tests' intent). Also run python -m engine schedule decide ... and the two offline runs above and paste their stdout and the resulting events in your report. Finally verify the viewer contract with Playwright (pre-installed; require('playwright') from node works; chromium.launch() no options): serve the repo root with python -m http.server on a free port, open index.html with ?viewer=1 or however app.js's viewer mode is enabled (read app.js lines 160–270 to find the switch; it maps /api/* to the baked files), wait for the watchlist table rows, capture console errors, click through the bottom tabs (recs/news/chips/orders/health/shadow) and a symbol row, and assert zero console errors and that '參數 v10' and the shadow verdict banner text appear; save screenshots to /tmp/claude-0/-home-user-tw-quant-view/f8621ae4-2ceb-5122-afe3-19497387358e/scratchpad/ (create it) and report their paths. Also render simple.html and screenshot it.

Module reports:
${notes}`, { label: 'integrate', phase: 'Integrate', agentType: 'general-purpose', schema: {
  type: 'object',
  properties: {
    files: { type: 'array', items: { type: 'string' } },
    cross_module_edits: { type: 'array', items: { type: 'string' } },
    pytest_summary: { type: 'string' },
    replay_stdout: { type: 'string' },
    new_events: { type: 'array', items: { type: 'string' } },
    playwright: { type: 'string' },
    screenshots: { type: 'array', items: { type: 'string' } },
    open_issues: { type: 'array', items: { type: 'string' } },
    confidence: { type: 'string', enum: ['high', 'medium', 'low'] },
  },
  required: ['files', 'cross_module_edits', 'pytest_summary', 'replay_stdout', 'new_events', 'playwright', 'screenshots', 'open_issues', 'confidence'],
} })

return { modules: results, integration: integ }