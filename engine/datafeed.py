"""External data: Yahoo Finance, Google News RSS, TWSE (spec §3).

Every public function takes the ``State`` (for caches, events and run flags) and
NEVER raises on network trouble: it degrades exactly as the spec table §3.2 says
(keep the cache, log the ``WARN`` event) and returns the cached value.

Offline mode (``state.offline()``): every fetch is served from
``fixtures/<TWQ_AS_OF>/`` and no socket is opened; when a fixture is missing the
state cache is used.  ``record_fixtures`` captures a live run into that layout.

Fixture / cache layout (shared with ``state.py``):
    bars/<code>.json      {"symbol","fetched_at","bars": [[date,o,h,l,c,v], ...]}   (also ``twii.json`` for ^TWII)
    bars60/<code>.json    {"symbol","fetched_at","bars": [[iso_ts,o,h,l,c,v], ...]}
    quotes.json           {"<symbol>": {"price","ts"}}
    news/<code>.json      {"fetched_at","items": [{"title","link","source","published"}]}   (raw, unscored)
    t86/<YYYY-MM-DD>.json {"date","rows": {"<code>": {"foreign","invtrust","dealer","total"}}}
    info/<code>.json      {"fetched_at","info": {"returnOnEquity","revenueGrowth","earningsGrowth","grossMargins","trailingPE"}}
    us.json               {"tsm_pct","sox_pct","night_pct"}  (percent, None when unknown)
    calendar.json         {"events": [...], "holidays": [...]}
"""
from __future__ import annotations

from datetime import datetime

from .state import State

RETRY_DELAYS = (1, 3, 9)        # spec §3.2 "3 attempts with backoff"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


def daily_bars(st: State, symbol: str, at: datetime | None = None) -> list:
    """Full adjusted daily history ``[[date, open, high, low, close, volume(int)], ...]``
    oldest first (spec §3.2 D1, §3.3).  Refreshes the cache with the degraded-response
    guard (newer → replace; equal → replace; older → keep + ``WARN data`` event);
    returns the cache on failure (``{symbol} 下載失敗({exc}),保留舊快取``)."""
    raise NotImplementedError


def quote(st: State, symbol: str, at: datetime) -> dict:
    """Intraday quote ``{"price": float, "ts": iso, "fresh": bool}`` (spec §3.2 D2, §3.4).
    ``fresh`` = market open and quote age ≤ 20 min; on failure the cached last close
    with ``fresh=False`` and ``ts`` = scan time."""
    raise NotImplementedError


def today_bar(st: State, symbol: str, at: datetime) -> list | None:
    """Today's provisional OHLCV from 1-minute data (spec §3.4) or ``None``."""
    raise NotImplementedError


def bars_60m(st: State, symbol: str) -> list:
    """60-minute bars ``[[iso_ts, o, h, l, c, v], ...]`` for the last month (spec §3.2 D3)."""
    raise NotImplementedError


def fundamentals(st: State, symbol: str) -> dict | None:
    """yfinance-style ``info`` subset (spec §3.2 D4) or the cache / ``None``."""
    raise NotImplementedError


def news_items(st: State, code: str, name: str, at: datetime, max_age_min: int = 30) -> list:
    """Raw Google News RSS items for the symbol (spec §3.2 D5, Q-A10): the first 8
    entries ``{"title","link","source","published"(+08:00 iso)}``; served from the
    cache when it is younger than ``max_age_min``; failure → cached items + ``WARN news``."""
    raise NotImplementedError


def t86(st: State, date: str) -> dict | None:
    """三大法人 rows for one trading date ``{code: {"foreign","invtrust","dealer","total"}}``
    (spec §3.2 D6; integer shares, thousands commas stripped)."""
    raise NotImplementedError


def t86_history(st: State, codes: list, days: int = 60) -> dict:
    """``{code: [(date, row), ...]}`` ascending by date from the cache (≤ ``days`` entries)."""
    raise NotImplementedError


def index_bars(st: State, at: datetime | None = None) -> list:
    """``^TWII`` daily bars (spec §3.2 D7) — same shape and guard as ``daily_bars``."""
    raise NotImplementedError


def us_overnight(st: State) -> dict:
    """``{"tsm_pct","sox_pct","night_pct"}`` for the morning brief (spec §3.2 D8); ``None`` when unknown."""
    raise NotImplementedError


def macro_news_count(st: State, at: datetime) -> int:
    """Count of ``q=台股`` RSS items published in the last 24 h (spec §3.2 D8)."""
    raise NotImplementedError


def calendar_sync(st: State, at: datetime) -> int:
    """Refresh ``calendar.json.events`` from TWSE (spec §3.2 D9); returns the number of
    ex-dividend rows found for watchlist codes within 30 days; logs the WARN on failure."""
    raise NotImplementedError


def holidays_sync(st: State) -> list:
    """Refresh ``calendar.json.holidays`` (spec §3.2 D10); returns the list (cache on failure)."""
    raise NotImplementedError


def record_fixtures(st: State, as_of: str, at: datetime) -> list:
    """Capture every live source into ``fixtures/<as_of>/`` (spec §9.9); returns written paths."""
    raise NotImplementedError
