/* tw-quant dashboard — single-file IIFE, no framework, no build step.
 * Talks to the FastAPI backend described in docs/DESIGN.md §server.py.
 * Taiwan color convention everywhere: red = up/buy, green = down/sell.
 * Colored values are always paired with signed numbers/labels so color
 * never carries meaning alone (CVD safety).
 */
(() => {
  'use strict';

  // ------------------------------------------------------------ constants
  const UP = '#f04452';            // 漲 / 買
  const DOWN = '#12b76a';          // 跌 / 賣
  const UP_A = 'rgba(240,68,82,0.55)';
  const DOWN_A = 'rgba(18,183,106,0.55)';
  const ACCENT = '#3987e5';        // neutral highlight / forecast fan
  const MA_COLORS = { ma5: '#e8b339', ma20: '#3987e5', ma60: '#b48ef0' };
  const GRID_LINE = '#1d2433';
  const AXIS_TEXT = '#8b93a7';
  // model-health lines: hue = horizon (validated dark categorical slots),
  // dash = model (secondary encoding besides color).
  const HZ_COLOR = { 1: '#3987e5', 5: '#c98500', 20: '#9085e9' };
  const HZ_FALLBACK = '#199e70';

  const REC = {
    STRONG_BUY:  { text: '強力買進', cls: 'rec-sbuy' },
    BUY:         { text: '買進',     cls: 'rec-buy' },
    HOLD:        { text: '觀望',     cls: 'rec-hold' },
    SELL:        { text: '賣出',     cls: 'rec-sell' },
    STRONG_SELL: { text: '強力賣出', cls: 'rec-ssell' },
  };
  const REGIME = {
    bull:  { text: '多頭', cls: 'up' },
    bear:  { text: '空頭', cls: 'down' },
    range: { text: '盤整', cls: '' },
  };
  const ORDER_STATUS = {
    FILLED: '成交', REJECTED: '拒絕', PENDING: '等待', CANCELLED: '取消',
  };
  // fallback fee rates (mirror config/settings.yaml defaults); overridden by
  // /api/config caps when the server exposes them. Estimates only — the
  // broker's fill is authoritative.
  const DEFAULT_FEES = { fee_rate: 0.001425, fee_discount: 0.6, sell_tax: 0.003, min_fee: 20 };

  // ------------------------------------------------------------ state
  const S = {
    config: null,          // /api/config payload
    overview: null,        // /api/overview payload
    detail: null,          // /api/symbol payload for the selected symbol
    selected: null,        // selected symbol, e.g. "2330.TW"
    lastScanSeen: null,    // engine.last_scan we last acted on
    lastEventId: 0,
    subTab: 'RSI',
    bottomTab: 'recs',
    sortKey: 'total',
    sortDir: -1,           // -1 desc, 1 asc
    zoom: null,            // {start, end} percent, persisted across renders
    chart: null,
    maeChart: null,
    hitChart: null,
    pendingOrder: null,    // intent shown in the confirm modal
    loadingSymbol: false,
    healthLoadedAt: 0,
    aiReport: null,        // /api/ai-report payload
    aiReportOpen: false,   // AI 收盤日報卡片展開狀態
    aiReportLoadedAt: 0,
  };

  // ------------------------------------------------------------ dom helpers
  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => Array.from(document.querySelectorAll(sel));

  function escapeHtml(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  // ------------------------------------------------------------ formatting
  function clsOf(v) { return v > 0 ? 'up' : v < 0 ? 'down' : 'flat'; }

  function fmtPrice(v) {
    if (v == null || !isFinite(v)) return '—';
    const a = Math.abs(v);
    if (a >= 1000) return v.toLocaleString('en-US', { maximumFractionDigits: 0 });
    if (a >= 100) return v.toFixed(1);
    return v.toFixed(2);
  }

  function fmtMoney(v) {
    if (v == null || !isFinite(v)) return '—';
    return Math.round(v).toLocaleString('en-US');
  }

  function fmtSignedMoney(v) {
    if (v == null || !isFinite(v)) return '—';
    const s = Math.round(Math.abs(v)).toLocaleString('en-US');
    return v > 0 ? '+' + s : v < 0 ? '-' + s : s;
  }

  function fmtPct(v, digits = 2) {
    if (v == null || !isFinite(v)) return '—';
    return (v > 0 ? '+' : '') + v.toFixed(digits) + '%';
  }

  function fmtRet(r, digits = 1) {  // fractional return -> signed percent
    if (r == null || !isFinite(r)) return '—';
    return fmtPct(r * 100, digits);
  }

  function fmtVol(v) {
    if (v == null || !isFinite(v)) return '—';
    if (v >= 1e8) return (v / 1e8).toFixed(1) + '億';
    if (v >= 1e4) return (v / 1e4).toFixed(0) + '萬';
    return String(Math.round(v));
  }

  function fmtClock(iso) {  // ISO -> HH:MM:SS, pinned to Asia/Taipei
    // engine timestamps are Taipei; the user's PC may be in another zone
    // (Tokyo, +1h) — rendering browser-local made "上次掃描" look one hour
    // off against the snapshot page's labeled Taipei time (bit us twice)
    if (!iso) return '—';
    const d = new Date(iso);
    if (isNaN(d)) return '—';
    try {
      return d.toLocaleTimeString('zh-TW', {
        timeZone: 'Asia/Taipei', hour12: false,
        hour: '2-digit', minute: '2-digit', second: '2-digit',
      });
    } catch (_) { return d.toTimeString().slice(0, 8); }
  }

  function fmtDateTime(iso) {
    if (!iso) return '—';
    return String(iso).replace('T', ' ').slice(0, 16);
  }

  function fmtHM(iso) {  // ISO -> HH:MM; blank-safe
    const t = fmtClock(iso);
    return t === '—' ? '—' : t.slice(0, 5);
  }

  function fmtTilt(v) {  // signed one-decimal tilt score; null/absent -> +0.0
    const x = (typeof v === 'number' && isFinite(v)) ? v : 0;
    return (x >= 0 ? '+' : '') + x.toFixed(1);
  }

  function fmtNewsTime(iso) {  // ISO -> "MM-DD HH:mm" in local time; blank-safe
    if (!iso) return '—';
    const d = new Date(iso);
    if (isNaN(d)) return '—';
    const p = (n) => String(n).padStart(2, '0');
    return p(d.getMonth() + 1) + '-' + p(d.getDate()) + ' ' + p(d.getHours()) + ':' + p(d.getMinutes());
  }

  function fmtChipDate(s) {  // "YYYYMMDD" or ISO-ish -> "YYYY-MM-DD"; blank-safe
    const t = String(s == null ? '' : s);
    if (/^\d{8}$/.test(t)) return t.slice(0, 4) + '-' + t.slice(4, 6) + '-' + t.slice(6, 8);
    return t ? t.slice(0, 10) : '—';
  }

  // ------------------------------------------------------------ networking
  //
  // Viewer mode (window.TWQ_VIEWER, set only by viewer.html): the page is a
  // read-only static export (GitHub Pages) with pre-baked JSON files and no
  // backend. api() maps every GET the dashboard makes onto those files and
  // never touches /api/*. Non-GET requests throw — the order/scan/tune UI is
  // removed from viewer.html, so reaching that throw is a bug by definition.
  // When TWQ_VIEWER is falsy, api() behaves exactly as before.
  const VIEWER = !!window.TWQ_VIEWER;

  async function viewerFetchJson(file) {
    // Unique ?t= query on every request: GitHub Pages' CDN caches each URL
    // for ~10 minutes, and a fresh query string bypasses that cache.
    try {
      const res = await fetch(file + '?t=' + Date.now(), { cache: 'no-store' });
      let data = null;
      try { data = await res.json(); } catch (_) { /* non-JSON body */ }
      return { ok: res.ok, status: res.status, data };
    } catch (_) {
      return { ok: false, status: 0, data: null };
    }
  }

  // data.json backs both /api/overview and /api/ai-report; memoize it for a
  // few seconds so one poll cycle fetches it once, while every 5-minute
  // viewer poll cycle still gets a fresh copy.
  let viewerDataMemo = { at: 0, promise: null };
  function viewerData() {
    if (!viewerDataMemo.promise || Date.now() - viewerDataMemo.at > 10000) {
      viewerDataMemo = { at: Date.now(), promise: viewerFetchJson('data.json') };
    }
    return viewerDataMemo.promise;
  }

  function renderViewerGenerated(iso) {
    const el = $('#viewer-generated');
    if (!el) return;
    let hm = '—';
    if (iso) {
      const d = new Date(iso);
      if (!isNaN(d)) {
        try {
          hm = d.toLocaleTimeString('zh-TW', {
            timeZone: 'Asia/Taipei', hour12: false, hour: '2-digit', minute: '2-digit',
          });
        } catch (_) { hm = fmtHM(iso); }
      }
    }
    el.textContent = '資料時間 ' + hm + ' 台北';
  }

  async function viewerApi(path, opts) {
    if (opts && opts.method && String(opts.method).toUpperCase() !== 'GET') {
      // belt-and-braces: the read-only build must never mutate anything
      throw new Error('唯讀檢視不允許 ' + opts.method + ' ' + path);
    }
    const p = String(path);
    if (p.startsWith('/api/overview')) {
      const r = await viewerData();
      if (r.ok && r.data) renderViewerGenerated(r.data.generated_at);
      return { ok: r.ok && !!r.data, status: r.status, data: r.data ? r.data.overview : null };
    }
    if (p.startsWith('/api/ai-report')) {
      const r = await viewerData();
      return { ok: r.ok && !!r.data, status: r.status, data: r.data ? r.data.ai_report : null };
    }
    if (p.startsWith('/api/symbol/')) {
      // /api/symbol/2330.TW?bars=250 -> symbol/2330.json (bare code, baked
      // with bars=250; query params are ignored)
      const raw = decodeURIComponent(p.slice('/api/symbol/'.length).split('?')[0]);
      const code = raw.replace(/\.(TW|TWO)$/i, '');
      return viewerFetchJson('symbol/' + encodeURIComponent(code) + '.json');
    }
    if (p.startsWith('/api/orders')) return viewerFetchJson('orders.json');
    if (p.startsWith('/api/model-health')) return viewerFetchJson('model-health.json');
    if (p.startsWith('/api/events')) {
      // 運作日誌 (2026-07-23): baked events.json holds the latest ~100
      // events; emulate the incremental after_id contract client-side so
      // the 5-minute viewer poll never re-appends rows it already showed.
      const m = p.match(/after_id=(\d+)/);
      const after = m ? parseInt(m[1], 10) : 0;
      const r = await viewerFetchJson('events.json');
      if (r.ok && r.data && Array.isArray(r.data.events)) {
        const evs = r.data.events.filter(e => (e.id || 0) > after);
        return {
          ok: true, status: 200,
          data: { events: evs, last_id: r.data.last_id != null ? r.data.last_id : after },
        };
      }
      return { ok: true, status: 200, data: { events: [], last_id: after } };
    }
    if (p.startsWith('/api/config')) {
      // no config export — the static viewer always shows paper-trade defaults
      return {
        ok: true, status: 200,
        data: { mode: 'paper', confirm_phrase_required: false, caps: {}, thresholds: {}, watchlist: [] },
      };
    }
    return { ok: false, status: 404, data: null };
  }

  async function api(path, opts) {
    // Returns {ok, status, data}; never throws (viewer-mode non-GET excepted).
    if (VIEWER) return viewerApi(path, opts);
    try {
      const res = await fetch(path, opts);
      let data = null;
      try { data = await res.json(); } catch (_) { /* non-JSON body */ }
      return { ok: res.ok, status: res.status, data };
    } catch (_) {
      return { ok: false, status: 0, data: null };
    }
  }

  function detailText(data, fallback) {
    if (!data) return fallback;
    const d = data.detail !== undefined ? data.detail : data.message;
    if (Array.isArray(d)) return d.map(String).join('；');
    if (typeof d === 'string' && d) return d;
    return fallback;
  }

  // ------------------------------------------------------------ toast
  function toast(msg, type = 'info', ms = 4200) {
    const el = document.createElement('div');
    el.className = 'toast ' + (type === 'info' ? '' : type);
    el.textContent = msg;
    $('#toasts').appendChild(el);
    setTimeout(() => { el.remove(); }, ms);
  }

  // ------------------------------------------------------------ fees
  function feeParams() {
    const caps = (S.config && S.config.caps) || {};
    const fees = (S.config && S.config.fees) || {};
    const pick = (k) => (typeof fees[k] === 'number' ? fees[k]
      : (typeof caps[k] === 'number' ? caps[k] : DEFAULT_FEES[k]));
    return {
      fee_rate: pick('fee_rate'),
      fee_discount: pick('fee_discount'),
      sell_tax: pick('sell_tax'),
      min_fee: pick('min_fee'),
      slippage_bps: typeof fees.slippage_bps === 'number' ? fees.slippage_bps : 5,
      max_order_value: typeof caps.max_order_value === 'number' ? caps.max_order_value : null,
    };
  }

  function estimate(side, qty, price) {
    const f = feeParams();
    // mirror PaperBroker: fills include deterministic slippage
    const slip = (f.slippage_bps || 0) / 10000;
    const fill = side === 'BUY' ? price * (1 + slip) : price * (1 - slip);
    const gross = qty * fill;
    const fee = Math.max(f.min_fee || 0, Math.round(gross * f.fee_rate * f.fee_discount));
    const tax = side === 'SELL' ? Math.round(gross * f.sell_tax) : 0;
    const total = side === 'BUY' ? gross + fee : gross - fee - tax;
    return { gross, fee, tax, total, overCap: f.max_order_value != null && qty * price > f.max_order_value };
  }

  // ------------------------------------------------------------ config
  async function loadConfig() {
    const r = await api('/api/config');
    if (r.ok && r.data) {
      S.config = r.data;
    } else {
      S.config = { mode: 'paper', confirm_phrase_required: false, caps: {}, thresholds: {}, watchlist: [] };
      toast('無法載入設定,暫以紙上交易預設值運作', 'warn');
    }
  }

  function phraseRequired() {
    if (!S.config) return false;
    return !!S.config.confirm_phrase_required || S.config.mode === 'real';
  }

  // ------------------------------------------------------------ overview
  async function refreshOverview() {
    const r = await api('/api/overview');
    const dot = $('#conn-dot');
    if (!r.ok || !r.data) {
      dot.className = 'conn-dot bad';
      dot.title = '連線中斷 — 無法取得 /api/overview';
      return;
    }
    dot.className = 'conn-dot ok';
    dot.title = '連線正常';
    S.overview = r.data;

    renderTopbar();
    renderWatchlist();
    renderAccount();
    renderPositions();
    renderRecs();
    renderOrderCard();
    renderSymbolHead();
    $('#disclaimer').textContent = S.overview.disclaimer || $('#disclaimer').textContent;

    // pick a default symbol on first load
    const rows = S.overview.rows || [];
    if (!S.selected && rows.length) {
      selectSymbol(sortedRows()[0].symbol);
    }

    // detect scan completion -> refresh the open symbol detail
    const ls = S.overview.engine && S.overview.engine.last_scan;
    if (ls && ls !== S.lastScanSeen) {
      const firstSeen = S.lastScanSeen === null;
      S.lastScanSeen = ls;
      if (!firstSeen && S.selected) loadSymbol(S.selected, { silent: true });
    }

    // AI 收盤日報:跟著 overview 輪詢載入(最多每 5 分鐘重抓一次,不另開計時器)。
    // 檢視模式本身就是 5 分鐘一輪,且日報與 overview 共用 memoized data.json,
    // 因此每輪都同步更新、不會多打一次網路。
    if (Date.now() - S.aiReportLoadedAt > (VIEWER ? 0 : 300000)) loadAiReport();
  }

  function rowOf(symbol) {
    const rows = (S.overview && S.overview.rows) || [];
    return rows.find((x) => x.symbol === symbol) || null;
  }

  function positionOf(symbol) {
    const ps = (S.overview && S.overview.positions) || [];
    return ps.find((p) => p.symbol === symbol) || null;
  }

  // ------------------------------------------------------------ topbar
  function renderTopbar() {
    const o = S.overview;
    const m = o.market || {};
    const e = o.engine || {};

    $('#market-label').textContent = m.label || (m.is_open ? '盤中' : '收盤');
    $('#market-badge').className = 'badge ' + (m.is_open ? 'blue' : 'gray');
    $('#market-index').textContent = m.index != null ? fmtPrice(m.index) : '—';
    const pctEl = $('#market-pct');
    pctEl.textContent = fmtPct(m.pct);
    pctEl.className = 'num ' + clsOf(m.pct || 0);
    const reg = $('#market-regime');
    if (m.regime_label) {
      reg.textContent = m.regime_label + (m.score != null ? ' ' + (m.score > 0 ? '+' : '') + m.score : '');
      reg.className = 'mini-chip ' + (m.score > 0 ? 'up' : m.score < 0 ? 'down' : '');
      reg.classList.remove('hidden');
    } else {
      reg.classList.add('hidden');
    }

    const mode = e.mode || 'paper';
    const mb = $('#mode-badge');
    mb.textContent = mode === 'real' ? '實盤' : '紙上交易';
    mb.className = 'badge ' + (mode === 'real' ? 'red' : 'blue');
    $('#acct-mode').textContent = mode === 'real' ? '實盤' : '紙上';

    const ap = $('#btn-autopilot');
    if (ap) {
      S.autopilot = !!e.autopilot;
      ap.textContent = '自動交易:' + (S.autopilot ? '開' : '關');
      ap.className = 'btn ' + (S.autopilot ? 'btn-primary' : 'btn-ghost');
      ap.disabled = mode === 'real';
      if (mode === 'real') ap.title = 'autopilot 僅支援紙上模式;實盤每筆委託都需要人工確認';
    }

    $('#kill-badge').classList.toggle('hidden', !e.kill);
    $('#params-badge').textContent = '參數 v' + (e.params_version != null ? e.params_version : '—');

    const ai = e.ai || {};
    const aiB = $('#ai-badge');
    aiB.textContent = 'AI 助理:' + (ai.enabled ? '啟用' : '未啟用');
    aiB.className = 'badge ' + (ai.enabled ? 'blue' : 'gray');  // also clears "hidden"
    aiB.title = ai.enabled
      ? '快速模型 ' + (ai.model_fast || '—') + ' ・ 深度模型 ' + (ai.model_deep || '—')
      : '後端 AI 助理未啟用';
    const scanState = $('#scan-state');   // absent in viewer.html
    if (scanState) scanState.classList.toggle('hidden', !e.scanning);
    const tuneState = $('#tune-state');   // absent in viewer.html
    if (tuneState) tuneState.classList.toggle('hidden', !e.tuning);

    tickCountdown();
  }

  function tickCountdown() {
    const e = (S.overview && S.overview.engine) || {};
    $('#last-scan').textContent = fmtClock(e.last_scan);
    const el = $('#next-scan');
    if (!el) return;                       // 下次掃描 countdown absent in viewer.html
    if (e.scanning) { el.textContent = '掃描中'; return; }
    const mkt = (S.overview && S.overview.market) || {};
    if (mkt.is_open === false) { el.textContent = '開盤後'; return; }
    if (!e.next_scan) { el.textContent = '--:--'; return; }
    const diff = Math.floor((new Date(e.next_scan).getTime() - Date.now()) / 1000);
    if (isNaN(diff)) { el.textContent = '--:--'; return; }
    if (diff <= 0) { el.textContent = '即將'; return; }
    const mm = String(Math.floor(diff / 60)).padStart(2, '0');
    const ss = String(diff % 60).padStart(2, '0');
    el.textContent = mm + ':' + ss;
  }

  // ------------------------------------------------------------ watchlist
  function sortedRows() {
    const rows = ((S.overview && S.overview.rows) || []).slice();
    const k = S.sortKey, dir = S.sortDir;
    rows.sort((a, b) => {
      const av = a[k] == null ? -Infinity : a[k];
      const bv = b[k] == null ? -Infinity : b[k];
      return av === bv ? a.symbol.localeCompare(b.symbol) : (av < bv ? dir : -dir);
    });
    return rows;
  }

  function renderWatchlist() {
    const body = $('#watchlist-body');
    const rows = sortedRows();
    if (!rows.length) {
      body.innerHTML = '<tr><td colspan="5" class="empty-cell">觀察清單為空</td></tr>';
      return;
    }
    body.innerHTML = rows.map((r) => {
      const rec = REC[r.rec_code] || REC.HOLD;
      const sel = r.symbol === S.selected ? ' selected' : '';
      const scoreTitle = '技術 ' + r.tech_total + ' ・ 大盤 ' + r.mkt_score + ' ・ 基本面 ' + r.fund_total +
        ' ・ 消息 ' + fmtTilt(r.news_total) + ' ・ 籌碼 ' + fmtTilt(r.chips_total) +
        (r.kd60 ? ' ・ 60分KD ' + r.kd60.label : '');
      const f5 = r.forecast5;
      const fcTitle = f5 ? '5日預測 ' + fmtRet(f5.pred_ret) + '(漲率 ' + Math.round((f5.prob_up || 0) * 100) + '%,' + escapeHtml(f5.model || '') + ')' : '';
      return '<tr class="clickable' + sel + '" data-symbol="' + escapeHtml(r.symbol) + '" title="' + fcTitle + '">' +
        '<td><div class="cell-name"><span class="code">' + escapeHtml(r.code) +
          (r.changed ? '<span class="changed-dot" title="本次掃描建議有變化">●</span>' : '') +
          (r.ai_note && r.ai_note.text
            ? '<span class="ai-dot" title="' + escapeHtml('AI 解讀 ' + fmtHM(r.ai_note.ts) + ':' + r.ai_note.text) + '">🤖</span>'
            : '') +
          '</span><span class="name">' + escapeHtml(r.name || '') + '</span></div></td>' +
        '<td class="r num">' + fmtPrice(r.price) +
          (r.quote_fresh
            ? ''
            : '<span class="dim" title="延遲價(非交易所即時報價),擷取 ' + escapeHtml(fmtHM(r.ts) || '') + '" style="font-size:.7em;margin-left:2px">延</span>') +
          '</td>' +
        '<td class="r num ' + clsOf(r.pct) + '">' + fmtPct(r.pct) + '</td>' +
        '<td class="r num ' + clsOf(r.total) + '" title="' + scoreTitle + '">' + (r.total != null ? r.total.toFixed(1) : '—') + '</td>' +
        '<td class="c"><span class="rec-badge ' + rec.cls + '">' + rec.text + '</span></td>' +
        '</tr>';
    }).join('');

    body.querySelectorAll('tr[data-symbol]').forEach((tr) => {
      tr.addEventListener('click', () => selectSymbol(tr.dataset.symbol));
    });

    // sort indicators on headers
    $$('#watchlist-table th.sortable').forEach((th) => {
      th.classList.remove('sorted-asc', 'sorted-desc');
      if (th.dataset.sort === S.sortKey) {
        th.classList.add(S.sortDir === 1 ? 'sorted-asc' : 'sorted-desc');
      }
    });
  }

  function selectSymbol(symbol) {
    if (!symbol) return;
    const changed = symbol !== S.selected;
    S.selected = symbol;
    renderWatchlist();
    renderOrderCard(changed);
    if (changed) {
      renderNews();   // clear stale news immediately; loadSymbol refills it
      renderChips();  // same for institutional-flow data
      loadSymbol(symbol);
    }
  }

  // ------------------------------------------------------------ account / positions
  function renderAccount() {
    const a = (S.overview && S.overview.account) || {};
    $('#acct-cash').textContent = fmtMoney(a.cash);
    $('#acct-value').textContent = fmtMoney(a.positions_value);
    $('#acct-equity').textContent = fmtMoney(a.equity);
    const re = $('#acct-realized');
    re.textContent = fmtSignedMoney(a.realized_pnl);
    re.className = 'num ' + clsOf(a.realized_pnl || 0);
    const un = $('#acct-unrealized');
    un.textContent = fmtSignedMoney(a.unrealized_pnl);
    un.className = 'num ' + clsOf(a.unrealized_pnl || 0);
    renderReward();
  }

  // Reward 記分板 (2026-07-23): display-only game layer — the card hides
  // itself when the backend has no reward block (disabled / no baseline)
  function renderReward() {
    const card = $('#reward-card');
    if (!card) return;
    const r = S.overview && S.overview.reward;
    if (!r) { card.style.display = 'none'; return; }
    card.style.display = '';
    $('#reward-total').textContent = String(r.total ?? 0) + ' 分';
    const monthEl = $('#reward-month');
    if (r.provisional) {
      const p = r.provisional;
      monthEl.textContent =
        (p.points >= 0 ? '+' : '') + p.points + ' 分(' +
        (p.ret_pct >= 0 ? '+' : '') + p.ret_pct.toFixed(2) + '%)';
      monthEl.className = 'num ' + clsOf(p.points || 0);
    } else {
      monthEl.textContent = '—';
      monthEl.className = 'num';
    }
    const hist = (r.history || []).filter(h => !h.skipped).slice(0, 3);
    $('#reward-history').textContent = hist.length
      ? hist.map(h =>
          h.month + ':' + (h.points >= 0 ? '+' : '') + h.points + '分' +
          (h.beat_market ? '(勝大盤)' : '')
        ).join(' ')
      : '尚無已結算月份';
  }

  function renderPositions() {
    const list = $('#positions-list');
    const tradable = !!$('#order-modal');  // order UI removed in viewer.html
    const ps = (S.overview && S.overview.positions) || [];
    $('#pos-count').textContent = ps.length ? ps.length + ' 檔' : '';
    if (!ps.length) {
      list.innerHTML = '<div class="empty-state small">目前無持股</div>';
      return;
    }
    list.innerHTML = ps.map((p) => {
      const isHold = !p.verdict || p.verdict === 'hold';
      const vcls = isHold ? 'verdict-hold' : 'verdict-exit';
      const vtext = isHold ? '續抱' : '該賣';
      const reasons = (p.reasons || []).join('、');
      return '<div class="pos-row" data-symbol="' + escapeHtml(p.symbol) + '" title="' + escapeHtml(reasons) + '">' +
        '<div class="pos-line">' +
          '<b>' + escapeHtml(p.code) + '</b> <span class="dim">' + escapeHtml(p.name || '') + '</span>' +
          '<span class="num dim">' + (p.qty || 0).toLocaleString('en-US') + '股</span>' +
          '<span class="spacer"></span>' +
          '<span class="num ' + clsOf(p.ret_pct) + '">' + fmtPct(p.ret_pct) + '</span>' +
          '<span class="verdict-badge ' + vcls + '">' + vtext + '</span>' +
        '</div>' +
        '<div class="pos-line sub">' +
          '<span>均價 <span class="num">' + fmtPrice(p.avg_price) + '</span></span>' +
          '<span>停損 <span class="num">' + fmtPrice(p.stop_price) + '</span></span>' +
          '<span>移停 <span class="num">' + fmtPrice(p.trail_price) + '</span></span>' +
          '<span class="spacer"></span>' +
          (tradable
            ? '<button class="btn btn-sell small pos-sell" data-symbol="' + escapeHtml(p.symbol) + '">賣出</button>'
            : '') +
        '</div>' +
        '</div>';
    }).join('');

    list.querySelectorAll('.pos-row').forEach((el) => {
      el.addEventListener('click', () => selectSymbol(el.dataset.symbol));
    });
    list.querySelectorAll('.pos-sell').forEach((btn) => {
      btn.addEventListener('click', (ev) => {
        ev.stopPropagation();
        const p = positionOf(btn.dataset.symbol);
        if (!p) return;
        selectSymbol(p.symbol);
        openOrderModal({ symbol: p.symbol, code: p.code, name: p.name, side: 'SELL', qty: p.qty, price: p.price });
      });
    });
  }

  // ------------------------------------------------------------ order card
  function renderOrderCard(resetQty = false) {
    if (!$('#order-card')) return;   // 一鍵下單 card removed in viewer.html
    const sym = S.selected;
    const row = sym ? rowOf(sym) : null;
    const pos = sym ? positionOf(sym) : null;
    const kill = !!(S.overview && S.overview.engine && S.overview.engine.kill);

    $('#order-symbol').textContent = row ? row.code + ' ' + (row.name || '') : (sym || '—');
    const price = row ? row.price : (pos ? pos.price : null);
    $('#order-price').textContent = fmtPrice(price);
    $('#order-held').textContent = pos ? pos.qty.toLocaleString('en-US') : '0';

    const qtyInput = $('#order-qty');
    if (resetQty && row) qtyInput.value = row.suggest_qty || 0;

    const qty = parseInt(qtyInput.value, 10) || 0;
    renderEstimate(qty, price);

    $('#btn-buy').disabled = kill || !row || !price;
    $('#btn-sell').disabled = kill || !sym || !pos || !price;
    $('#btn-buy').title = kill ? 'KILL 檔存在,下單封鎖中' : '';
    $('#btn-sell').title = kill ? 'KILL 檔存在,下單封鎖中' : (!pos ? '無持股' : '');
  }

  function renderEstimate(qty, price) {
    const est = $('#order-est');
    if (!qty || !price) {
      est.innerHTML = '<span class="dim">輸入股數以估算金額</span>';
      return;
    }
    const b = estimate('BUY', qty, price);
    const s = estimate('SELL', qty, price);
    est.innerHTML =
      '<div class="est-line"><span>買進估計(含手續費 ' + fmtMoney(b.fee) + ')</span><span class="num">' + fmtMoney(b.total) + '</span></div>' +
      '<div class="est-line"><span>賣出估計(費 ' + fmtMoney(s.fee) + ' + 稅 ' + fmtMoney(s.tax) + ')</span><span class="num">' + fmtMoney(s.total) + '</span></div>' +
      (b.overCap ? '<div class="est-line" style="color:var(--warn)">金額超過單筆上限,將被風控拒絕</div>' : '');
  }

  // ------------------------------------------------------------ symbol head (chips above chart)
  function renderSymbolHead() {
    renderAiNote();
    const d = S.detail;
    const row = S.selected ? rowOf(S.selected) : null;
    if (!d && !row) return;

    const code = (d && d.code) || (row && row.code) || '';
    const name = (d && d.name) || (row && row.name) || '';
    $('#sym-title').textContent = code + ' ' + name;

    const price = row ? row.price : lastClose(d);
    const pct = row ? row.pct : lastPct(d);
    $('#sym-price').textContent = fmtPrice(price);
    $('#sym-price').className = 'num big ' + clsOf(pct || 0);
    $('#sym-pct').textContent = fmtPct(pct);
    $('#sym-pct').className = 'num ' + clsOf(pct || 0);

    const regime = (row && row.regime) || (d && d.trend && d.trend.summary && d.trend.summary.regime);
    const rg = REGIME[regime];
    const rgEl = $('#sym-regime');
    if (rg) {
      rgEl.textContent = rg.text;
      rgEl.className = 'mini-chip ' + rg.cls;
      rgEl.classList.remove('hidden');
    } else {
      rgEl.classList.add('hidden');
    }

    // forecast chips
    const fEl = $('#forecast-chips');
    const fc = d && d.forecast;
    if (fc && Array.isArray(fc.horizons) && fc.horizons.length) {
      fEl.innerHTML = fc.horizons.map((h) => {
        const c = h.pred_ret > 0 ? 'up' : h.pred_ret < 0 ? 'down' : '';
        const t = '95%區間 ' + fmtRet(h.ci95 && h.ci95[0]) + ' ~ ' + fmtRet(h.ci95 && h.ci95[1]);
        return '<span class="mini-chip ' + c + '" title="' + t + '">' + h.horizon_days + '日 ' + fmtRet(h.pred_ret) +
          ' <span class="dim">漲率' + Math.round((h.prob_up || 0) * 100) + '%</span></span>';
      }).join('') + '<span class="mini-chip" title="預測模型(冠軍)">' + escapeHtml(fc.model || '') + '</span>';
    } else if (d) {
      fEl.innerHTML = '<span class="mini-chip warn">預測:資料累積中</span>';
    }

    // signal chips
    const sEl = $('#signal-chips');
    if (d) {
      const tech = (d.signals || []).map((s) =>
        '<span class="sig-chip ' + clsOf(s.score) + '" title="' + escapeHtml(s.note || '') + '(分數 ' + s.score + ')">' +
        escapeHtml(s.indicator) + ' ' + escapeHtml(s.label) + '</span>');
      const fund = (d.fund_signals || []).map((s) =>
        '<span class="sig-chip fund ' + clsOf(s.score) + '" title="' + escapeHtml(s.note || '') + '(分數 ' + s.score + ')">' +
        escapeHtml(s.indicator) + ' ' + escapeHtml(s.label) + '</span>');
      // news tilt chip — /api/symbol may lack "news" on older caches: treat as 0
      const nv = (row && typeof row.news_total === 'number' && isFinite(row.news_total)) ? row.news_total
        : (d.news && typeof d.news.score === 'number' && isFinite(d.news.score)) ? d.news.score : 0;
      const newsChip = '<span class="sig-chip news ' + clsOf(nv) +
        '" title="標題級情緒計分(AI 語意為主,詞典備援),僅供提示,不構成訊號;不納入回測">消息 ' + fmtTilt(nv) + '</span>';
      // chips tilt chip — /api/symbol may lack "chips" on older payloads: treat as 0
      const cv = (row && typeof row.chips_total === 'number' && isFinite(row.chips_total)) ? row.chips_total
        : (d.chips && typeof d.chips.score === 'number' && isFinite(d.chips.score)) ? d.chips.score : 0;
      const chipsChip = '<span class="sig-chip chips ' + clsOf(cv) +
        '" title="TWSE 三大法人買賣超(T86,收盤後公布);僅供提示,暫不納入回測">籌碼 ' + fmtTilt(cv) + '</span>';
      // 60-min KD chip — short-term aid; older payloads may lack the field
      const kdRow = (row && row.kd60) || (d.intraday_kd || null);
      const kv = (row && typeof row.kd60_total === 'number' && isFinite(row.kd60_total)) ? row.kd60_total
        : (kdRow && typeof kdRow.score === 'number' && isFinite(kdRow.score)) ? kdRow.score : 0;
      const kdChip = kdRow
        ? '<span class="sig-chip chips ' + clsOf(kv) +
          '" title="' + escapeHtml(kdRow.note || '60分K線 KD') +
          ';短線輔助(未回測,僅小幅 tilt)">60分KD ' + escapeHtml(kdRow.label || '中性') +
          (kv ? ' ' + fmtTilt(kv) : '') + '</span>'
        : '';
      sEl.innerHTML = tech.concat(fund).join('') + newsChip + chipsChip + kdChip;
    }
  }

  // ------------------------------------------------------------ AI 解讀 (per-symbol note)
  function aiEnabled() {
    const e = S.overview && S.overview.engine;
    return !!(e && e.ai && e.ai.enabled);
  }

  function renderAiNote() {
    const el = $('#ai-note');
    // only trust S.detail when it belongs to the current selection;
    // fall back to the overview row's ai_note (same shape) if any
    const d = (S.detail && S.detail.symbol === S.selected) ? S.detail : null;
    const row = S.selected ? rowOf(S.selected) : null;
    const note = (d && d.ai_note) || (row && row.ai_note) || null;
    if (note && note.text) {
      el.innerHTML = '<span class="ai-note-tag">🤖 AI 解讀</span>' +
        '<span class="ai-note-time num dim" title="產生時間">' + fmtHM(note.ts) + '</span>' +
        '<span class="ai-note-text">' + escapeHtml(note.text) + '</span>';
      el.classList.remove('hidden');
    } else if (aiEnabled() && S.selected) {
      el.innerHTML = '<span class="ai-note-tag">🤖 AI 解讀</span><span class="dim">尚未產生</span>';
      el.classList.remove('hidden');
    } else {
      el.classList.add('hidden');
    }
  }

  function lastClose(d) {
    if (!d || !d.bars || !d.bars.length) return null;
    return d.bars[d.bars.length - 1][4];
  }

  function lastPct(d) {
    if (!d || !d.bars || d.bars.length < 2) return null;
    const a = d.bars[d.bars.length - 2][4], b = d.bars[d.bars.length - 1][4];
    return a ? (b / a - 1) * 100 : null;
  }

  // ------------------------------------------------------------ symbol detail + chart
  async function loadSymbol(symbol, { silent = false } = {}) {
    // request-token pattern: rapid symbol switches must not drop the newest
    // request (a boolean guard would discard the second click entirely)
    const req = (S.loadSeq = (S.loadSeq || 0) + 1);
    const r = await api('/api/symbol/' + encodeURIComponent(symbol) + '?bars=250');
    if (req !== S.loadSeq) return;             // superseded by a newer request
    if (!r.ok || !r.data) {
      if (!silent) toast('無法載入 ' + symbol + ' 的資料', 'err');
      return;
    }
    if (r.data.symbol !== S.selected) return;  // user moved on meanwhile
    S.detail = r.data;
    renderSymbolHead();
    renderChart();
    renderNews();
    renderChips();
  }

  function renderChart() {
    const d = S.detail;
    const el = $('#main-chart');
    if (typeof echarts === 'undefined') {
      el.innerHTML = '<div class="empty-state">圖表引擎載入失敗(vendor 檔缺失且無法連上 CDN)</div>';
      return;
    }
    if (!d || !d.bars || !d.bars.length) {
      if (S.chart) { S.chart.dispose(); S.chart = null; }
      el.innerHTML = '<div class="empty-state">尚無K線資料</div>';
      return;
    }
    if (!S.chart) {
      el.innerHTML = '';
      S.chart = echarts.init(el, null, { renderer: 'canvas' });
      const rememberZoom = () => {
        const dz = S.chart.getOption().dataZoom;
        if (dz && dz[0]) S.zoom = { start: dz[0].start, end: dz[0].end };
      };
      S.chart.on('datazoom', rememberZoom);
      S.chart.on('dataZoom', rememberZoom);  // event casing differs across versions
    }
    S.chart.setOption(buildChartOption(d), true);
    // Defensive: if the chart was initialized while its container had no
    // layout size (hidden tab / early load), pick up the real size now.
    if (S.chart.getWidth() === 0 || S.chart.getHeight() === 0) S.chart.resize();
  }

  function diffArr(hi, lo) {
    return hi.map((h, i) => (h == null || lo[i] == null) ? null : h - lo[i]);
  }

  function buildChartOption(d) {
    const bars = d.bars;
    const ind = d.indicators || {};
    const dates = bars.map((b) => b[0]);
    const ohlc = bars.map((b) => [b[1], b[4], b[3], b[2]]); // [open, close, low, high]
    const volData = bars.map((b) => ({
      value: b[5],
      itemStyle: { color: b[4] >= b[1] ? UP_A : DOWN_A },
    }));

    // ---- combined axis: history + forecast fan dates beyond the last bar
    const fan = d.forecast && d.forecast.fan;
    const axis = dates.slice();
    let fanFull = null;   // {median, lo68, hi68, lo95, hi95} padded to axis length
    if (fan && Array.isArray(fan.dates) && fan.dates.length) {
      const seen = new Set(axis);
      for (const fd of fan.dates) if (!seen.has(fd)) { axis.push(fd); seen.add(fd); }
      const idxOf = new Map(axis.map((x, i) => [x, i]));
      const pad = (vals) => {
        const out = new Array(axis.length).fill(null);
        (vals || []).forEach((v, i) => {
          const j = idxOf.get(fan.dates[i]);
          if (j != null && v != null) out[j] = v;
        });
        return out;
      };
      fanFull = {
        median: pad(fan.median), lo68: pad(fan.lo68), hi68: pad(fan.hi68),
        lo95: pad(fan.lo95), hi95: pad(fan.hi95),
      };
    }

    // ---- regime background shading (bull faint red / bear faint green)
    const segs = (d.trend && d.trend.segments) || [];
    const areas = [];
    for (const s of segs) {
      if (s.regime === 'range') continue;
      if (s.end < dates[0]) continue;
      const start = s.start < dates[0] ? dates[0] : s.start;
      areas.push([
        { xAxis: start, itemStyle: { color: s.regime === 'bull' ? 'rgba(240,68,82,0.055)' : 'rgba(18,183,106,0.065)' } },
        { xAxis: s.end },
      ]);
    }

    // ---- markLines for the held position (avg / stop / trail)
    const pos = positionOf(d.symbol);
    const posLines = [];
    if (pos) {
      const line = (name, value, color) => ({
        name: name + ' ' + fmtPrice(value),
        yAxis: value,
        lineStyle: { color, type: 'dashed', width: 1 },
        label: { show: true, position: 'insideEndTop', color, fontSize: 10, formatter: '{b}' },
      });
      if (pos.avg_price) posLines.push(line('均價', pos.avg_price, '#8b93a7'));
      if (pos.stop_price) posLines.push(line('停損', pos.stop_price, '#e5a13a'));
      if (pos.trail_price) posLines.push(line('移停', pos.trail_price, '#4ac6b7'));
    }

    const series = [
      {
        name: 'K線', type: 'candlestick', xAxisIndex: 0, yAxisIndex: 0,
        data: ohlc,
        itemStyle: { color: UP, color0: DOWN, borderColor: UP, borderColor0: DOWN },
        markArea: areas.length ? { silent: true, data: areas } : undefined,
        markLine: posLines.length ? { silent: true, symbol: 'none', data: posLines } : undefined,
      },
    ];

    const thinLine = (name, data, color, width = 1.3) => ({
      name, type: 'line', xAxisIndex: 0, yAxisIndex: 0, data,
      symbol: 'none', lineStyle: { width, color }, itemStyle: { color },
      connectNulls: false, z: 3,
    });
    if (ind.ma5) series.push(thinLine('MA5', ind.ma5, MA_COLORS.ma5));
    if (ind.ma20) series.push(thinLine('MA20', ind.ma20, MA_COLORS.ma20));
    if (ind.ma60) series.push(thinLine('MA60', ind.ma60, MA_COLORS.ma60));

    // Bollinger band: two faint edge lines + a stacked area fill between them
    if (ind.bb_up && ind.bb_low) {
      const bbEdge = { width: 1, color: 'rgba(139,147,167,0.45)' };
      series.push({ name: '布林', type: 'line', xAxisIndex: 0, yAxisIndex: 0, data: ind.bb_up, symbol: 'none', lineStyle: bbEdge, itemStyle: { color: '#8b93a7' }, z: 2 });
      series.push({ name: '布林', type: 'line', xAxisIndex: 0, yAxisIndex: 0, data: ind.bb_low, symbol: 'none', lineStyle: bbEdge, itemStyle: { color: '#8b93a7' }, z: 2 });
      series.push({ name: '布林', type: 'line', xAxisIndex: 0, yAxisIndex: 0, data: ind.bb_low, stack: 'bb', symbol: 'none', lineStyle: { opacity: 0 }, silent: true, z: 1 });
      series.push({
        name: '布林', type: 'line', xAxisIndex: 0, yAxisIndex: 0,
        data: diffArr(ind.bb_up, ind.bb_low), stack: 'bb', symbol: 'none',
        lineStyle: { opacity: 0 }, areaStyle: { color: 'rgba(139,147,167,0.06)' }, silent: true, z: 1,
      });
    }

    // Forecast fan: 95 band (faintest), 68 band, dashed median
    if (fanFull) {
      const band = (name, lo, hi, opacity) => ([
        { name, type: 'line', xAxisIndex: 0, yAxisIndex: 0, data: lo, stack: name, symbol: 'none', lineStyle: { opacity: 0 }, silent: true, z: 4, itemStyle: { color: ACCENT } },
        { name, type: 'line', xAxisIndex: 0, yAxisIndex: 0, data: diffArr(hi, lo), stack: name, symbol: 'none', lineStyle: { opacity: 0 }, areaStyle: { color: 'rgba(57,135,229,' + opacity + ')' }, silent: true, z: 4, itemStyle: { color: ACCENT } },
      ]);
      series.push(...band('預測95%', fanFull.lo95, fanFull.hi95, 0.10));
      series.push(...band('預測68%', fanFull.lo68, fanFull.hi68, 0.16));
      series.push({
        name: '預測中位', type: 'line', xAxisIndex: 0, yAxisIndex: 0,
        data: fanFull.median, symbol: 'none',
        lineStyle: { width: 1.6, type: 'dashed', color: ACCENT }, itemStyle: { color: ACCENT }, z: 5,
      });
    }

    // volume
    series.push({
      name: '成交量', type: 'bar', xAxisIndex: 1, yAxisIndex: 1,
      data: volData, barWidth: '60%',
    });

    // sub-chart (RSI / MACD / KD)
    const guide = (vals) => ({
      silent: true, symbol: 'none',
      lineStyle: { color: '#3a4256', type: 'dashed', width: 1 },
      label: { show: true, position: 'end', color: '#5b6376', fontSize: 9 },
      data: vals.map((v) => ({ yAxis: v })),
    });
    let subYAxis = { scale: true };
    if (S.subTab === 'RSI') {
      subYAxis = { min: 0, max: 100, splitNumber: 2 };
      series.push({
        name: 'RSI', type: 'line', xAxisIndex: 2, yAxisIndex: 2,
        data: ind.rsi || [], symbol: 'none',
        lineStyle: { width: 1.4, color: '#e8b339' }, itemStyle: { color: '#e8b339' },
        markLine: guide([70, 30]),
      });
    } else if (S.subTab === 'MACD') {
      series.push({
        name: 'MACD柱', type: 'bar', xAxisIndex: 2, yAxisIndex: 2,
        data: (ind.macd_hist || []).map((v) => ({
          value: v, itemStyle: { color: v != null && v >= 0 ? UP_A : DOWN_A },
        })),
        barWidth: '60%',
      });
      series.push({
        name: 'DIF', type: 'line', xAxisIndex: 2, yAxisIndex: 2,
        data: ind.macd || [], symbol: 'none',
        lineStyle: { width: 1.3, color: ACCENT }, itemStyle: { color: ACCENT },
      });
      series.push({
        name: 'DEA', type: 'line', xAxisIndex: 2, yAxisIndex: 2,
        data: ind.macd_sig || [], symbol: 'none',
        lineStyle: { width: 1.3, color: '#e8b339' }, itemStyle: { color: '#e8b339' },
      });
    } else {  // KD
      subYAxis = { min: 0, max: 100, splitNumber: 2 };
      series.push({
        name: 'K值', type: 'line', xAxisIndex: 2, yAxisIndex: 2,
        data: ind.k || [], symbol: 'none',
        lineStyle: { width: 1.3, color: ACCENT }, itemStyle: { color: ACCENT },
        markLine: guide([80, 20]),
      });
      series.push({
        name: 'D值', type: 'line', xAxisIndex: 2, yAxisIndex: 2,
        data: ind.d || [], symbol: 'none',
        lineStyle: { width: 1.3, color: '#e8b339' }, itemStyle: { color: '#e8b339' },
      });
    }

    // default zoom: show roughly the last 130 sessions + the fan
    if (!S.zoom) {
      const n = axis.length;
      S.zoom = { start: n > 130 ? Math.round((1 - 130 / n) * 100) : 0, end: 100 };
    }

    const legendData = ['MA5', 'MA20', 'MA60', '布林']
      .concat(fanFull ? ['預測68%', '預測95%', '預測中位'] : []);

    const axisCommon = {
      type: 'category',
      data: axis,
      boundaryGap: true,
      axisLine: { lineStyle: { color: '#2a3247' } },
      axisTick: { show: false },
      splitLine: { show: false },
    };

    const tooltipFormatter = makeTooltipFormatter(d, axis, fanFull);

    return {
      animation: false,
      backgroundColor: 'transparent',
      legend: {
        data: legendData,
        top: 2, left: 6,
        textStyle: { color: AXIS_TEXT, fontSize: 11 },
        itemWidth: 14, itemHeight: 8,
        inactiveColor: '#3a4256',
      },
      axisPointer: { link: [{ xAxisIndex: 'all' }], label: { backgroundColor: '#1d2433' } },
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross', crossStyle: { color: '#3a4256' }, lineStyle: { color: '#3a4256' } },
        backgroundColor: 'rgba(23,29,41,0.95)',
        borderColor: '#232b3a',
        textStyle: { color: '#dfe4ee', fontSize: 11 },
        formatter: tooltipFormatter,
        confine: true,
      },
      grid: [
        { left: 8, right: 62, top: 24, height: '46%' },
        { left: 8, right: 62, top: '56%', height: '11%' },
        { left: 8, right: 62, top: '71%', height: '16%' },
      ],
      xAxis: [
        { ...axisCommon, gridIndex: 0, axisLabel: { show: false } },
        { ...axisCommon, gridIndex: 1, axisLabel: { show: false } },
        { ...axisCommon, gridIndex: 2, axisLabel: { color: AXIS_TEXT, fontSize: 10 } },
      ],
      yAxis: [
        {
          gridIndex: 0, scale: true, position: 'right',
          axisLabel: { color: AXIS_TEXT, fontSize: 10 },
          splitLine: { lineStyle: { color: GRID_LINE } },
          axisLine: { show: false }, axisTick: { show: false },
        },
        {
          gridIndex: 1, position: 'right', splitNumber: 2,
          axisLabel: { color: AXIS_TEXT, fontSize: 9, formatter: fmtVol },
          splitLine: { show: false }, axisLine: { show: false }, axisTick: { show: false },
        },
        {
          gridIndex: 2, position: 'right', ...subYAxis,
          axisLabel: { color: AXIS_TEXT, fontSize: 9 },
          splitLine: { lineStyle: { color: GRID_LINE } },
          axisLine: { show: false }, axisTick: { show: false },
        },
      ],
      dataZoom: [
        { type: 'inside', xAxisIndex: [0, 1, 2], start: S.zoom.start, end: S.zoom.end },
        {
          type: 'slider', xAxisIndex: [0, 1, 2], start: S.zoom.start, end: S.zoom.end,
          bottom: 2, height: 14,
          borderColor: '#232b3a', backgroundColor: 'transparent',
          fillerColor: 'rgba(57,135,229,0.12)',
          handleStyle: { color: '#3987e5' },
          textStyle: { color: '#5b6376', fontSize: 9 },
          dataBackground: { lineStyle: { color: '#2a3247' }, areaStyle: { color: 'rgba(42,50,71,0.4)' } },
        },
      ],
      series,
    };
  }

  function makeTooltipFormatter(d, axis, fanFull) {
    const bars = d.bars;
    const ind = d.indicators || {};
    const basePrice = d.forecast ? d.forecast.base_price : null;
    const row = (label, html) =>
      '<div style="display:flex;justify-content:space-between;gap:14px">' +
      '<span style="color:#8b93a7">' + label + '</span><span class="num">' + html + '</span></div>';
    const colored = (v, text) =>
      '<span style="color:' + (v > 0 ? UP : v < 0 ? DOWN : '#8b93a7') + '">' + text + '</span>';

    return (params) => {
      if (!params || !params.length) return '';
      const i = params[0].dataIndex;
      const date = axis[i] || '';
      let html = '<div style="font-weight:700;margin-bottom:3px">' + date + '</div>';

      if (i < bars.length) {
        const b = bars[i];
        const prev = i > 0 ? bars[i - 1][4] : null;
        const chg = prev ? (b[4] / prev - 1) * 100 : null;
        html += row('開', fmtPrice(b[1])) + row('高', fmtPrice(b[2])) +
                row('低', fmtPrice(b[3])) +
                row('收', colored(chg || 0, fmtPrice(b[4]) + (chg != null ? ' (' + fmtPct(chg) + ')' : '')));
        html += row('量', fmtVol(b[5]));
        const iv = (arr) => (arr && arr[i] != null ? arr[i] : null);
        if (iv(ind.ma5) != null) html += row('MA5', fmtPrice(ind.ma5[i]));
        if (iv(ind.ma20) != null) html += row('MA20', fmtPrice(ind.ma20[i]));
        if (iv(ind.ma60) != null) html += row('MA60', fmtPrice(ind.ma60[i]));
        if (S.subTab === 'RSI' && iv(ind.rsi) != null) html += row('RSI', ind.rsi[i].toFixed(1));
        if (S.subTab === 'MACD') {
          if (iv(ind.macd) != null) html += row('DIF', ind.macd[i].toFixed(2));
          if (iv(ind.macd_sig) != null) html += row('DEA', ind.macd_sig[i].toFixed(2));
          if (iv(ind.macd_hist) != null) html += row('柱', colored(ind.macd_hist[i], ind.macd_hist[i].toFixed(2)));
        }
        if (S.subTab === 'KD') {
          if (iv(ind.k) != null) html += row('K', ind.k[i].toFixed(1));
          if (iv(ind.d) != null) html += row('D', ind.d[i].toFixed(1));
        }
      } else if (fanFull) {
        const med = fanFull.median[i];
        html += '<div style="color:#3987e5;margin-bottom:2px">預測(' +
          escapeHtml((d.forecast && d.forecast.model) || '') + ')</div>';
        if (med != null) {
          const ret = basePrice ? (med / basePrice - 1) : null;
          html += row('中位', fmtPrice(med) + (ret != null ? ' (' + fmtRet(ret) + ')' : ''));
        }
        if (fanFull.lo68[i] != null) html += row('68%區間', fmtPrice(fanFull.lo68[i]) + ' ~ ' + fmtPrice(fanFull.hi68[i]));
        if (fanFull.lo95[i] != null) html += row('95%區間', fmtPrice(fanFull.lo95[i]) + ' ~ ' + fmtPrice(fanFull.hi95[i]));
        html += '<div style="color:#5b6376;margin-top:3px">預測必有誤差,僅供參考</div>';
      }
      return html;
    };
  }

  // ------------------------------------------------------------ recommendations tab
  function renderRecs() {
    const body = $('#recs-body');
    // viewer.html removes the order modal and the 一鍵下單 header column, so
    // its rows have one cell fewer than the normal dashboard's.
    const tradable = !!$('#order-modal');
    const nCols = tradable ? 7 : 6;
    const rows = ((S.overview && S.overview.rows) || [])
      .filter((r) => r.rec_code && r.rec_code !== 'HOLD')
      .sort((a, b) => Math.abs(b.total) - Math.abs(a.total));
    $('#recs-count').textContent = rows.length ? String(rows.length) : '';
    if (!rows.length) {
      body.innerHTML = '<tr><td colspan="' + nCols + '" class="empty-cell">目前沒有非觀望的建議</td></tr>';
      return;
    }
    const kill = !!(S.overview.engine && S.overview.engine.kill);
    body.innerHTML = rows.map((r) => {
      const rec = REC[r.rec_code] || REC.HOLD;
      const isBuy = r.rec_code === 'BUY' || r.rec_code === 'STRONG_BUY';
      const pos = positionOf(r.symbol);
      const qty = isBuy ? (r.suggest_qty || 0) : (pos ? pos.qty : 0);
      const f5 = r.forecast5;
      const fcell = f5
        ? '<span class="' + clsOf(f5.pred_ret) + '">' + fmtRet(f5.pred_ret) + '</span> <span class="dim">漲率' + Math.round((f5.prob_up || 0) * 100) + '%</span>'
        : '<span class="dim">累積中</span>';
      // 建議部位 % (2026-07-23 user request): a share count only means
      // something for THIS account's capital — % of equity travels. The
      // family viewer shows the % alone; the live dashboard keeps the
      // actionable share count next to it (and on the order button).
      const equity = (S.overview.account && S.overview.account.equity) || 0;
      const pctTxt = equity > 0 && qty > 0 && r.price > 0
        ? ((qty * r.price / equity) * 100).toFixed(1) + '%'
        : '—';
      const qtyCell = VIEWER
        ? pctTxt
        : pctTxt + (qty > 0 ? ' <span class="dim">(' + qty.toLocaleString('en-US') + '股)</span>' : '');
      const disabled = kill || qty <= 0;
      const title = kill ? 'KILL 檔存在,下單封鎖中' : (!isBuy && !pos ? '無持股' : '');
      const btn = !tradable ? '' :
        '<td class="c"><button class="btn ' + (isBuy ? 'btn-buy' : 'btn-sell') + ' small rec-order" ' +
        (disabled ? 'disabled ' : '') + 'title="' + title + '" ' +
        'data-symbol="' + escapeHtml(r.symbol) + '" data-side="' + (isBuy ? 'BUY' : 'SELL') + '" data-qty="' + qty + '">' +
        (isBuy ? '買進' : '賣出') + ' ' + qty.toLocaleString('en-US') + '股</button></td>';
      return '<tr class="clickable" data-symbol="' + escapeHtml(r.symbol) + '">' +
        '<td><b>' + escapeHtml(r.code) + '</b> <span class="dim">' + escapeHtml(r.name || '') + '</span></td>' +
        '<td class="c"><span class="rec-badge ' + rec.cls + '">' + rec.text + '</span></td>' +
        '<td class="r num ' + clsOf(r.total) + '">' + (r.total != null ? r.total.toFixed(1) : '—') + '</td>' +
        '<td class="r num">' + fmtPrice(r.price) + '</td>' +
        '<td class="r num">' + fcell + '</td>' +
        '<td class="r num">' + qtyCell + '</td>' +
        btn +
        '</tr>';
    }).join('');

    body.querySelectorAll('tr[data-symbol]').forEach((tr) => {
      tr.addEventListener('click', () => selectSymbol(tr.dataset.symbol));
    });
    body.querySelectorAll('.rec-order').forEach((btn) => {
      btn.addEventListener('click', (ev) => {
        ev.stopPropagation();
        const r = rowOf(btn.dataset.symbol);
        if (!r) return;
        selectSymbol(r.symbol);
        openOrderModal({
          symbol: r.symbol, code: r.code, name: r.name,
          side: btn.dataset.side, qty: parseInt(btn.dataset.qty, 10) || 0, price: r.price,
        });
      });
    });
  }

  // ------------------------------------------------------------ market news tab (消息面)
  const NEWS_BADGE = {  // Taiwan convention: red = bullish (利多), green = bearish (利空)
    pos: { text: '利多', cls: 'pos' },
    neg: { text: '利空', cls: 'neg' },
    neu: { text: '中性', cls: 'neu' },
  };

  function renderNews() {
    // only trust S.detail when it belongs to the current selection;
    // /api/symbol may lack "news" (older cache) -> treat as {score:0, items:[]}
    const d = (S.detail && S.detail.symbol === S.selected) ? S.detail : null;
    const news = (d && d.news) || {};
    const score = (typeof news.score === 'number' && isFinite(news.score)) ? news.score : 0;
    const items = Array.isArray(news.items) ? news.items : [];

    const row = S.selected ? rowOf(S.selected) : null;
    const code = (d && d.code) || (row && row.code) || '';
    const name = (d && d.name) || (row && row.name) || '';
    $('#news-symbol').textContent = code ? code + ' ' + (name || '') : '—';

    const scoreEl = $('#news-score');
    scoreEl.textContent = '消息面評分 ' + fmtTilt(score);
    scoreEl.className = 'mini-chip ' + (score > 0 ? 'up' : score < 0 ? 'down' : '');

    const list = $('#news-list');
    if (!items.length) {
      list.innerHTML = '<div class="empty-state small">暫無相關新聞或尚未載入</div>';
      return;
    }
    list.innerHTML = items.map((it) => {
      const badge = NEWS_BADGE[it.sentiment] ||
        (it.score > 0 ? NEWS_BADGE.pos : it.score < 0 ? NEWS_BADGE.neg : NEWS_BADGE.neu);
      // news titles/links are untrusted external text: escape everything,
      // and only allow http(s) hrefs (otherwise render a plain span).
      const title = escapeHtml(it.title || '');
      const link = (typeof it.link === 'string' && /^https?:\/\//i.test(it.link)) ? it.link : '';
      const titleHtml = link
        ? '<a class="news-title-link" href="' + escapeHtml(link) + '" target="_blank" rel="noopener">' + title + '</a>'
        : '<span class="news-title-link">' + title + '</span>';
      const rowTitle = (typeof it.score === 'number' && it.score !== 0)
        ? ' title="情緒分數 ' + fmtTilt(it.score) + '"' : '';
      return '<div class="news-row"' + rowTitle + '>' +
        '<span class="news-time num dim">' + fmtNewsTime(it.published) + '</span>' +
        '<span class="news-src dim">' + escapeHtml(it.source || '') + '</span>' +
        '<span class="news-badge ' + badge.cls + '">' + badge.text + '</span>' +
        titleHtml +
        '</div>';
    }).join('');
  }

  // ------------------------------------------------------------ institutional-flow tab (籌碼面)
  function renderChips() {
    // only trust S.detail when it belongs to the current selection;
    // /api/symbol may lack "chips" (older payload) -> treat as {score:0, signals:[], recent:[]}
    const d = (S.detail && S.detail.symbol === S.selected) ? S.detail : null;
    const chips = (d && d.chips) || {};
    const score = (typeof chips.score === 'number' && isFinite(chips.score)) ? chips.score : 0;
    const signals = Array.isArray(chips.signals) ? chips.signals : [];
    const recent = Array.isArray(chips.recent) ? chips.recent : [];

    const row = S.selected ? rowOf(S.selected) : null;
    const code = (d && d.code) || (row && row.code) || '';
    const name = (d && d.name) || (row && row.name) || '';
    $('#chips-symbol').textContent = code ? code + ' ' + (name || '') : '—';

    const scoreEl = $('#chips-score');
    scoreEl.textContent = '籌碼面評分 ' + fmtTilt(score);
    scoreEl.className = 'mini-chip ' + (score > 0 ? 'up' : score < 0 ? 'down' : '');

    // signal chips: 外資連買N日 etc — Taiwan colors, red positive / green negative
    $('#chips-signals').innerHTML = signals.map((s) =>
      '<span class="sig-chip chips ' + clsOf(s.score) + '" title="' + escapeHtml(s.note || '') +
      '(分數 ' + s.score + ')">' + escapeHtml(s.indicator) + ' ' + escapeHtml(s.label) + '</span>').join('');

    const body = $('#chips-body');
    if (!recent.length) {
      body.innerHTML = '<tr><td colspan="5" class="empty-cell">暫無籌碼資料(上櫃股票或資料尚未回填)</td></tr>';
      return;
    }
    // raw shares -> 張 (1000-share lots), signed, thousands separators; newest first
    const cell = (v) => {
      const lots = (v == null || !isFinite(v)) ? null : Math.round(v / 1000);
      const txt = lots == null ? '—' : (lots > 0 ? '+' : '') + lots.toLocaleString('en-US');
      return '<td class="r num ' + (lots == null ? 'flat' : clsOf(lots)) + '">' + txt + '</td>';
    };
    body.innerHTML = recent.slice()
      .sort((a, b) => String(b.date || '').localeCompare(String(a.date || '')))
      .map((r) => '<tr>' +
        '<td class="num dim">' + escapeHtml(fmtChipDate(r.date)) + '</td>' +
        cell(r.foreign) + cell(r.invtrust) + cell(r.dealer) + cell(r.total) +
        '</tr>').join('');
  }

  // ------------------------------------------------------------ AI 收盤日報 (/api/ai-report)
  async function loadAiReport() {
    S.aiReportLoadedAt = Date.now();
    const r = await api('/api/ai-report');
    if (!r.ok || !r.data) return;   // keep the last good report on transient errors
    S.aiReport = r.data;
    renderAiReport();
  }

  function renderAiReport() {
    const rep = S.aiReport;
    const dateEl = $('#ai-report-date');
    const metaEl = $('#ai-report-meta');
    const contentEl = $('#ai-report-content');
    if (rep && rep.date) {
      dateEl.textContent = rep.date;
      dateEl.classList.remove('hidden');
    } else {
      dateEl.classList.add('hidden');
    }
    if (!rep || !rep.content) {
      metaEl.textContent = '';
      contentEl.innerHTML = '<div class="empty-state small">收盤後自動產生</div>';
      return;
    }
    metaEl.textContent = '產生於 ' + fmtDateTime(rep.generated_at);
    contentEl.innerHTML = mdToHtml(rep.content);
  }

  // Minimal, safe markdown -> HTML: everything is HTML-escaped first, then
  // only ## headings, "- " list items, **bold** and blank-line paragraphs
  // are transformed. No raw HTML from the model ever reaches the DOM.
  function mdToHtml(md) {
    const inline = (s) => escapeHtml(s).replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    const out = [];
    let list = null;   // open <li> buffer
    let para = [];     // open paragraph buffer
    const flushPara = () => { if (para.length) { out.push('<p>' + para.join('<br>') + '</p>'); para = []; } };
    const flushList = () => { if (list) { out.push('<ul>' + list.join('') + '</ul>'); list = null; } };
    for (const raw of String(md || '').split(/\r?\n/)) {
      const t = raw.trim();
      if (!t) { flushPara(); flushList(); continue; }
      const h = t.match(/^(#{1,4})\s+(.*)$/);
      if (h) {
        flushPara(); flushList();
        out.push('<div class="ai-md-h' + h[1].length + '">' + inline(h[2]) + '</div>');
        continue;
      }
      if (/^-\s+/.test(t)) {
        flushPara();
        if (!list) list = [];
        list.push('<li>' + inline(t.replace(/^-\s+/, '')) + '</li>');
        continue;
      }
      flushList();
      para.push(inline(t));
    }
    flushPara(); flushList();
    return out.join('');
  }

  // ------------------------------------------------------------ orders tab
  async function loadOrders() {
    const r = await api('/api/orders?limit=50');
    const body = $('#orders-body');
    const orders = (r.ok && r.data && r.data.orders) || [];
    if (!orders.length) {
      body.innerHTML = '<tr><td colspan="10" class="empty-cell">尚無訂單</td></tr>';
      return;
    }
    body.innerHTML = orders.map((o) => {
      const isBuy = o.side === 'BUY';
      return '<tr>' +
        '<td class="num dim">' + fmtDateTime(o.created_at) + '</td>' +
        '<td><b>' + escapeHtml(o.code) + '</b> <span class="dim">' + escapeHtml(o.name || '') + '</span></td>' +
        '<td class="c"><span class="' + (isBuy ? 'up' : 'down') + '">' + (isBuy ? '買' : '賣') + '</span></td>' +
        '<td class="r num">' + (o.qty != null ? o.qty.toLocaleString('en-US') : '—') + '</td>' +
        '<td class="r num">' + fmtPrice(o.filled_price) + '</td>' +
        '<td class="r num">' + fmtMoney(o.fee) + '</td>' +
        '<td class="r num">' + fmtMoney(o.tax) + '</td>' +
        '<td class="r num ' + clsOf(o.pnl || 0) + '">' + (o.pnl != null ? fmtSignedMoney(o.pnl) : '—') + '</td>' +
        '<td class="c">' + (ORDER_STATUS[o.status] || escapeHtml(o.status || '')) + '</td>' +
        '<td class="c dim">' + (o.mode === 'real' ? '實盤' : '紙上') +
          (o.source === 'autopilot' ? ' <span class="mini-chip warn" title="autopilot 依訊號自動下的單">自動</span>' : '') +
        '</td>' +
        '</tr>';
    }).join('');
  }

  // ------------------------------------------------------------ model health tab
  async function loadHealth() {
    const r = await api('/api/model-health');
    S.healthLoadedAt = Date.now();
    if (!r.ok || !r.data) {
      $('#health-empty').classList.remove('hidden');
      $('#health-empty').textContent = '無法載入模型健康資料';
      $('#health-charts').classList.add('hidden');
      return;
    }
    renderHealth(r.data);
  }

  function renderHealth(data) {
    const metrics = data.metrics || {};
    const seriesRows = metrics.series || [];
    const brief = (S.overview && S.overview.model_health_brief) || {};

    // brief line
    const b5m = brief.mae_5d != null ? fmtRet(brief.mae_5d) : '—';
    const b5h = brief.hit_rate_5d != null ? Math.round(brief.hit_rate_5d * 100) + '%' : '—';
    $('#health-brief').textContent =
      '5日 MAE ' + b5m + ' ・ 命中率 ' + b5h + ' ・ 已兌現 ' + (brief.n_resolved || 0) + ' 筆';

    // champion chips
    const champ = metrics.champion || {};
    $('#health-champion').innerHTML = Object.keys(champ).sort((a, b) => (+a) - (+b))
      .map((h) => '<span class="champ-chip" title="樣本數足夠時取 MAE 較低者">' + h + '日冠軍:' + escapeHtml(champ[h]) + '</span>')
      .join('');
    $('#active-version').textContent = data.active_version != null ? '目前參數 v' + data.active_version : '';

    // charts (or the honest empty state — day one has no resolved forecasts)
    const emptyEl = $('#health-empty');
    const chartsEl = $('#health-charts');
    if (!seriesRows.length || typeof echarts === 'undefined') {
      emptyEl.classList.remove('hidden');
      if (typeof echarts === 'undefined') emptyEl.textContent = '圖表引擎未載入';
      chartsEl.classList.add('hidden');
    } else {
      emptyEl.classList.add('hidden');
      chartsEl.classList.remove('hidden');
      if (!S.maeChart) S.maeChart = echarts.init($('#mae-chart'));
      if (!S.hitChart) S.hitChart = echarts.init($('#hit-chart'));
      S.maeChart.setOption(healthChartOption(seriesRows, 'mae'), true);
      S.hitChart.setOption(healthChartOption(seriesRows, 'hit_rate'), true);
      S.maeChart.resize();
      S.hitChart.resize();
    }

    renderParamsHistory(data.params_history || [], data.active_version);
  }

  function healthChartOption(rows, field) {
    const isHit = field === 'hit_rate';
    const dates = Array.from(new Set(rows.map((r) => r.date))).sort();
    const keys = Array.from(new Set(rows.map((r) => r.model + '|' + r.horizon)))
      .sort((a, b) => {
        const [ma, ha] = a.split('|'), [mb, hb] = b.split('|');
        return ma === mb ? (+ha) - (+hb) : ma.localeCompare(mb);
      });
    const byKey = new Map();
    rows.forEach((r) => byKey.set(r.model + '|' + r.horizon + '|' + r.date, r));

    const series = keys.map((k) => {
      const [model, hz] = k.split('|');
      const color = HZ_COLOR[hz] || HZ_FALLBACK;
      return {
        name: model + ' ' + hz + '日',
        type: 'line',
        data: dates.map((dte) => {
          const r = byKey.get(k + '|' + dte);
          if (!r || r[field] == null) return null;
          return isHit ? +(r[field] * 100).toFixed(1) : +(r[field] * 100).toFixed(3);
        }),
        connectNulls: true,
        symbol: 'circle', symbolSize: 5,
        lineStyle: { width: 2, color, type: model === 'baseline' ? 'dashed' : 'solid' },
        itemStyle: { color },
        markLine: isHit && k === keys[0] ? {
          silent: true, symbol: 'none',
          lineStyle: { color: '#3a4256', type: 'dashed', width: 1 },
          label: { show: true, position: 'end', color: '#5b6376', fontSize: 9, formatter: '50%' },
          data: [{ yAxis: 50 }],
        } : undefined,
      };
    });

    return {
      animation: false,
      backgroundColor: 'transparent',
      legend: {
        type: 'scroll', top: 0, left: 0,
        textStyle: { color: AXIS_TEXT, fontSize: 10 },
        itemWidth: 14, itemHeight: 8, inactiveColor: '#3a4256',
      },
      tooltip: {
        trigger: 'axis',
        backgroundColor: 'rgba(23,29,41,0.95)', borderColor: '#232b3a',
        textStyle: { color: '#dfe4ee', fontSize: 11 },
        valueFormatter: (v) => (v == null ? '—' : v + '%'),
        confine: true,
      },
      grid: { left: 44, right: 14, top: 24, bottom: 20 },
      xAxis: {
        type: 'category', data: dates,
        axisLabel: { color: AXIS_TEXT, fontSize: 9 },
        axisLine: { lineStyle: { color: '#2a3247' } }, axisTick: { show: false },
      },
      yAxis: {
        type: 'value',
        scale: !isHit,
        min: isHit ? 0 : undefined,
        max: isHit ? 100 : undefined,
        axisLabel: { color: AXIS_TEXT, fontSize: 9, formatter: (v) => v + '%' },
        splitLine: { lineStyle: { color: GRID_LINE } },
      },
      series,
    };
  }

  function renderParamsHistory(hist, activeVersion) {
    const body = $('#params-body');
    if (!hist.length) {
      body.innerHTML = '<tr><td colspan="7" class="empty-cell">尚無調參紀錄</td></tr>';
      return;
    }
    const fmtMetric = (v) => (v == null ? '—' : Number(v).toFixed(3));
    body.innerHTML = hist.map((h) => {
      let summary = '';
      try {
        const p = JSON.parse(h.params_json || '{}');
        const ex = p.exit || {};
        summary = 'buy_th=' + p.buy_th +
          (ex.stop_pct != null ? ' 停損' + Math.round(ex.stop_pct * 100) + '%' : '') +
          (ex.trail_pct != null ? ' 移停' + Math.round(ex.trail_pct * 100) + '%' : '');
      } catch (_) { /* keep empty */ }
      const adopted = !!h.adopted;
      return '<tr class="' + (adopted ? 'adopted-row' : '') + '" title="' + escapeHtml(h.params_json || '') + '">' +
        '<td class="num dim">' + fmtDateTime(h.adopted_at) + '</td>' +
        '<td class="r num">v' + h.version + (h.version === activeVersion && adopted ? ' ●' : '') + '</td>' +
        '<td class="c">' + (adopted ? '<span class="up">是</span>' : '<span class="dim">否</span>') + '</td>' +
        '<td class="r num">' + fmtMetric(h.train_metric) + '</td>' +
        '<td class="r num">' + fmtMetric(h.valid_metric) + '</td>' +
        '<td class="r num">' + fmtMetric(h.champion_metric) + '</td>' +
        '<td>' + escapeHtml(h.reason || '') + (summary ? ' <span class="dim">' + escapeHtml(summary) + '</span>' : '') + '</td>' +
        '</tr>';
    }).join('');
  }

  // ------------------------------------------------------------ events (運作日誌)
  async function pollEvents() {
    const r = await api('/api/events?after_id=' + S.lastEventId + '&limit=100');
    if (!r.ok || !r.data) return;
    const events = r.data.events || [];
    if (r.data.last_id != null) S.lastEventId = r.data.last_id;
    else if (events.length) S.lastEventId = events[events.length - 1].id;
    if (!events.length) return;

    const feed = $('#event-feed');
    const empty = feed.querySelector('.empty-state');
    if (empty) empty.remove();
    const nearBottom = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 60;

    const frag = document.createDocumentFragment();
    for (const ev of events) {
      const div = document.createElement('div');
      const level = (ev.level || 'INFO').toUpperCase();
      div.className = 'ev-row ev-' + (['INFO', 'WARN', 'ERROR'].includes(level) ? level : 'INFO');
      div.innerHTML =
        '<span class="ev-ts">' + escapeHtml(String(ev.ts || '').slice(11, 19)) + '</span> ' +
        '<span class="ev-src">[' + escapeHtml(ev.source || '') + ']</span> ' +
        escapeHtml(ev.message || '');
      frag.appendChild(div);
    }
    feed.appendChild(frag);
    // cap the feed length
    while (feed.children.length > 400) feed.removeChild(feed.firstChild);
    if (nearBottom) feed.scrollTop = feed.scrollHeight;
  }

  // ------------------------------------------------------------ order modal
  function openOrderModal(intent) {
    if (!intent || !intent.qty || intent.qty <= 0) {
      toast('股數需大於 0', 'warn');
      return;
    }
    if (!intent.price) {
      toast('尚無參考價,無法下單', 'warn');
      return;
    }
    S.pendingOrder = intent;
    const isBuy = intent.side === 'BUY';
    const est = estimate(intent.side, intent.qty, intent.price);

    $('#modal-title').textContent = '確認' + (isBuy ? '買進' : '賣出') + ' — ' +
      intent.code + ' ' + (intent.name || '');
    $('#modal-real-warn').classList.toggle('hidden', S.config == null || S.config.mode !== 'real');

    const sideHtml = '<span class="' + (isBuy ? 'up' : 'down') + '" style="font-weight:700">' +
      (isBuy ? '買進' : '賣出') + '</span>';
    $('#modal-rows').innerHTML =
      '<div class="kv"><span>方向</span><span>' + sideHtml + '</span></div>' +
      '<div class="kv"><span>股數</span><span class="num">' + intent.qty.toLocaleString('en-US') + '</span></div>' +
      '<div class="kv"><span>參考價</span><span class="num">' + fmtPrice(intent.price) + '</span></div>' +
      '<div class="kv"><span>預估手續費</span><span class="num">' + fmtMoney(est.fee) + '</span></div>' +
      (intent.side === 'SELL'
        ? '<div class="kv"><span>預估證交稅</span><span class="num">' + fmtMoney(est.tax) + '</span></div>' : '') +
      '<div class="kv total"><span>' + (isBuy ? '預估支出' : '預估淨入') + '</span><span class="num">' +
        fmtMoney(est.total) + '</span></div>' +
      (est.overCap
        ? '<div class="kv" style="color:var(--warn)"><span>警告</span><span>金額超過單筆上限,將被風控拒絕</span></div>' : '');

    const needPhrase = phraseRequired();
    $('#phrase-row').classList.toggle('hidden', !needPhrase);
    $('#confirm-phrase').value = '';

    $('#btn-modal-confirm').disabled = false;
    $('#order-modal').classList.remove('hidden');
    if (needPhrase) $('#confirm-phrase').focus();
  }

  function closeModal() {
    $('#order-modal').classList.add('hidden');
    S.pendingOrder = null;
  }

  async function submitOrder() {
    const o = S.pendingOrder;
    if (!o || $('#btn-modal-confirm').disabled) return;  // guard double submit
    let phrase = '';
    if (phraseRequired()) {
      phrase = $('#confirm-phrase').value.trim();
      if (!phrase) {
        toast('實盤模式需輸入確認語', 'warn');
        $('#confirm-phrase').focus();
        return;
      }
    }
    const btn = $('#btn-modal-confirm');
    btn.disabled = true;
    const r = await api('/api/orders', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        symbol: o.symbol, side: o.side, qty: o.qty,
        confirm: true, confirm_phrase: phrase,
      }),
    });
    btn.disabled = false;

    if (r.ok && r.data) {
      // OrderResult dict
      const msg = r.data.message || (r.data.ok ? '委託完成' : '委託失敗');
      toast(msg, r.data.ok ? 'ok' : 'err', 5000);
      if (r.data.ok) closeModal();
    } else if (r.status === 403) {
      toast(detailText(r.data, '確認語不符,已拒絕下單'), 'err', 5000);
    } else if (r.status === 400) {
      toast(detailText(r.data, '委託未通過檢查'), 'err', 6000);
    } else {
      toast(detailText(r.data, '下單失敗:無法連線到伺服器'), 'err', 6000);
    }
    refreshOverview();
    loadOrders();
  }

  // ------------------------------------------------------------ top buttons
  async function triggerScan() {
    const r = await api('/api/scan', { method: 'POST' });
    if (r.ok && r.data && r.data.ok) toast('已觸發背景掃描', 'ok');
    else toast(detailText(r.data, '掃描已在執行中'), 'warn');
  }

  async function triggerTune() {
    const r = await api('/api/tune', { method: 'POST' });
    if (r.ok && r.data && r.data.ok) toast('已開始背景調參(僅樣本外驗證更好才會採用)', 'ok');
    else toast(detailText(r.data, '調參已在執行中'), 'warn');
  }

  // ------------------------------------------------------------ tabs & bindings
  function switchBottomTab(tab) {
    S.bottomTab = tab;
    $$('#bottom-tabs .btab').forEach((b) => b.classList.toggle('active', b.dataset.tab === tab));
    $$('#bottom-panel .tab-pane').forEach((p) => p.classList.toggle('active', p.id === 'tab-' + tab));
    if (tab === 'news') renderNews();
    if (tab === 'chips') renderChips();
    if (tab === 'orders') loadOrders();
    if (tab === 'health') loadHealth();
    if (tab === 'logs') {
      const feed = $('#event-feed');           // absent in viewer.html
      if (feed) feed.scrollTop = feed.scrollHeight;
    }
  }

  async function toggleAutopilot() {
    const turningOn = !S.autopilot;
    if (turningOn) {
      const msg = '開啟「自動交易(紙上)」?\n\n'
        + '引擎將在每輪掃描後自動買賣【虛擬】部位:\n'
        + '・先出場:持股觸發停損/移動停利、或建議轉賣出 → 全數賣出\n'
        + '・再進場:買進/強力買進訊號 → 按建議部位 %(自己的本金換算)買入;已持有可加碼\n'
        + '  (每檔每天最多加碼 1 次,單一持股 ≤ 權益 40%)\n'
        + '・每輪最多 3 筆,風控上限與 KILL 開關照常生效\n'
        + '・每筆自動單都會在訂單紀錄標「自動」並寫入運作日誌\n\n'
        + '此開關只影響紙上虛擬帳戶;真錢每一筆永遠需要你手動確認。';
      if (!window.confirm(msg)) return;
    }
    const r = await api('/api/autopilot', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: turningOn }),
    });
    if (r.ok && r.data && r.data.ok) {
      S.autopilot = !!r.data.enabled;
      toast(S.autopilot
        ? '自動交易(紙上)已開啟——之後每輪掃描它會自己買賣,你看戰績就好'
        : '自動交易(紙上)已關閉', S.autopilot ? 'ok' : 'warn');
      refreshOverview();
    } else {
      toast(detailText(r.data, '切換失敗'), 'err', 6000);
    }
  }

  function bindUI() {
    // scan / tune / autopilot controls are removed from viewer.html
    const btnScan = $('#btn-scan');
    if (btnScan) btnScan.addEventListener('click', triggerScan);
    const btnTune = $('#btn-tune');
    if (btnTune) btnTune.addEventListener('click', triggerTune);
    const btnAutopilot = $('#btn-autopilot');
    if (btnAutopilot) btnAutopilot.addEventListener('click', toggleAutopilot);

    $('#ai-report-toggle').addEventListener('click', () => {
      S.aiReportOpen = !S.aiReportOpen;
      $('#ai-report-body').classList.toggle('hidden', !S.aiReportOpen);
      $('#ai-report-caret').textContent = S.aiReportOpen ? '▾' : '▸';
    });

    $$('#watchlist-table th.sortable').forEach((th) => {
      th.addEventListener('click', () => {
        const key = th.dataset.sort;
        if (S.sortKey === key) S.sortDir = -S.sortDir;
        else { S.sortKey = key; S.sortDir = -1; }
        renderWatchlist();
      });
    });

    $$('#subtabs .subtab').forEach((btn) => {
      btn.addEventListener('click', () => {
        S.subTab = btn.dataset.tab;
        $$('#subtabs .subtab').forEach((b) => b.classList.toggle('active', b === btn));
        renderChart();
      });
    });

    $$('#bottom-tabs .btab').forEach((btn) => {
      btn.addEventListener('click', () => switchBottomTab(btn.dataset.tab));
    });

    // order card + confirm modal are removed from viewer.html entirely
    const qtyInput = $('#order-qty');
    if (qtyInput) qtyInput.addEventListener('input', () => renderOrderCard(false));

    const btnBuy = $('#btn-buy');
    if (btnBuy) btnBuy.addEventListener('click', () => {
      const row = rowOf(S.selected);
      if (!row) return;
      openOrderModal({
        symbol: row.symbol, code: row.code, name: row.name, side: 'BUY',
        qty: parseInt($('#order-qty').value, 10) || 0, price: row.price,
      });
    });
    const btnSell = $('#btn-sell');
    if (btnSell) btnSell.addEventListener('click', () => {
      const row = rowOf(S.selected);
      const pos = positionOf(S.selected);
      const price = row ? row.price : (pos ? pos.price : null);
      if (!S.selected || !price) return;
      openOrderModal({
        symbol: S.selected,
        code: (row && row.code) || (pos && pos.code) || S.selected,
        name: (row && row.name) || (pos && pos.name) || '',
        side: 'SELL',
        qty: parseInt($('#order-qty').value, 10) || 0, price,
      });
    });

    const modal = $('#order-modal');
    if (modal) {
      $('#btn-modal-cancel').addEventListener('click', closeModal);
      $('#btn-modal-confirm').addEventListener('click', submitOrder);
      modal.addEventListener('click', (ev) => {
        if (ev.target === modal) closeModal();
      });
      document.addEventListener('keydown', (ev) => {
        if (ev.key === 'Escape' && !modal.classList.contains('hidden')) closeModal();
      });
      $('#confirm-phrase').addEventListener('keydown', (ev) => {
        if (ev.key === 'Enter') submitOrder();
      });
    }

    window.addEventListener('resize', () => {
      if (S.chart) S.chart.resize();
      if (S.maeChart) S.maeChart.resize();
      if (S.hitChart) S.hitChart.resize();
    });
  }

  // ------------------------------------------------------------ boot
  async function init() {
    bindUI();
    await loadConfig();
    await refreshOverview();
    if ($('#event-feed')) {
      await pollEvents();
      // live dashboard: incremental every 3s; viewer: with the 5-minute
      // baked-JSON cadence (CDN-backed static file, no backend to poll)
      setInterval(pollEvents, VIEWER ? 300000 : 3000);
    }

    // overview every 10s (backend merges ~15s poller quotes at serve time,
    // 2026-07-23); the static viewer re-reads the baked JSON every 5
    // minutes instead (exporter cadence + GitHub Pages CDN), and also
    // refreshes the currently-open symbol's JSON on each cycle.
    setInterval(() => {
      refreshOverview();
      if (VIEWER && S.selected) loadSymbol(S.selected, { silent: true });
    }, VIEWER ? 300000 : 10000);
    setInterval(tickCountdown, 1000);      // countdown ticks every second
    setInterval(() => {                    // keep health tab fresh while open
      if (S.bottomTab === 'health' && Date.now() - S.healthLoadedAt > (VIEWER ? 300000 : 60000)) loadHealth();
    }, 10000);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
