"""Taipei clock, date helpers and the cron → mode decision (spec §1.4, §3.5, §9.3).

All timestamps the engine emits are Taipei-local with an explicit ``+08:00``
offset and second precision (spec §1.4).  ``TWQ_NOW`` overrides the clock for
replays and tests; it accepts an ISO string with or without an offset
(a naive value is interpreted as Taipei time).
"""
from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Taipei")

OPEN_TIME = time(9, 0)
CLOSE_TIME = time(13, 30)
FIXING_TIME = time(13, 30)          # scan at/after this clock time is 收盤定盤
EOD_TIME = time(14, 15)
SCAN_INTERVAL_MIN = 30              # real cadence under GitHub Actions (spec §9.2, R7)

CRON_MORNING = "30 0 * * 1-5"
CRON_SCAN = "*/30 1-5 * * 1-5"
CRON_EOD = "15 6 * * 1-5"
CRON_TUNE = "0 2 * * 6"

MODES = ("auto", "morning", "scan", "eod", "tune", "bake", "replay")
KIND_INTRADAY = "盤中"
KIND_FIXING = "收盤定盤"
KIND_EOD = "EOD"
KIND_STARTUP = "啟動"


def now() -> datetime:
    """Current Taipei time (aware).  ``TWQ_NOW`` overrides it."""
    override = os.environ.get("TWQ_NOW", "").strip()
    if override:
        return parse_iso(override)
    return datetime.now(TZ).replace(microsecond=0)


def parse_iso(text: str) -> datetime:
    """Parse an ISO timestamp; naive values are Taipei; result is Taipei-aware."""
    dt = datetime.fromisoformat(text.strip())
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return dt.astimezone(TZ).replace(microsecond=0)


def iso(dt: datetime) -> str:
    """``2026-10-31T14:15:22+08:00`` — never ``Z``, never microseconds (spec §1.4)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return dt.astimezone(TZ).replace(microsecond=0).isoformat(timespec="seconds")


def ymd(d: date | datetime) -> str:
    if isinstance(d, datetime):
        d = d.astimezone(TZ).date() if d.tzinfo else d.date()
    return d.isoformat()


def parse_date(text: str) -> date:
    return date.fromisoformat(text[:10])


def month_key(d: date | datetime) -> str:
    return ymd(d)[:7]


def iso_week(d: date | datetime) -> str:
    """``2026-W31`` (ISO week of the date)."""
    if isinstance(d, datetime):
        d = d.date()
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def monday_of(d: date | datetime) -> date:
    if isinstance(d, datetime):
        d = d.date()
    return d - timedelta(days=d.weekday())


def is_weekday(d: date) -> bool:
    return d.weekday() < 5


def is_trading_day(d: date, holidays: list[str] | set[str] | None = None) -> bool:
    """Calendar part of spec §3.5: Mon–Fri and not in ``calendar.json.holidays``.

    The "no new ^TWII bar ⇒ holiday" rule needs the data feed and lives in the
    scan pipeline (``engine.pipelines``), not here.
    """
    if not is_weekday(d):
        return False
    return ymd(d) not in set(holidays or ())


def previous_trading_day(d: date, holidays=None) -> date:
    cur = d - timedelta(days=1)
    while not is_trading_day(cur, holidays):
        cur -= timedelta(days=1)
    return cur


def next_trading_day(d: date, holidays=None) -> date:
    cur = d + timedelta(days=1)
    while not is_trading_day(cur, holidays):
        cur += timedelta(days=1)
    return cur


def is_open(at: datetime, holidays=None) -> bool:
    """Market session flag used for ``overview.market.is_open`` (spec Q-A16)."""
    at = at.astimezone(TZ)
    if not is_trading_day(at.date(), holidays):
        return False
    return OPEN_TIME <= at.time() <= CLOSE_TIME


def scan_kind(at: datetime) -> str:
    """``收盤定盤`` for the 13:30 slot (clock ≥ 13:30), else ``盤中`` (spec §9.3)."""
    return KIND_FIXING if at.astimezone(TZ).time() >= FIXING_TIME else KIND_INTRADAY


def next_scan(at: datetime, holidays=None) -> datetime:
    """Next 30-minute scan slot (09:00–13:30 Taipei) at or after ``at`` (spec §7.1 ``next_scan``)."""
    at = at.astimezone(TZ)
    day = at.date()
    while True:
        if is_trading_day(day, holidays):
            start = datetime.combine(day, OPEN_TIME, TZ)
            end = datetime.combine(day, CLOSE_TIME, TZ)
            slot = start
            while slot <= end:
                if slot > at:
                    return slot
                slot += timedelta(minutes=SCAN_INTERVAL_MIN)
        day += timedelta(days=1)


def decide(event: str, cron: str, mode: str, as_of: str, at: datetime | None = None,
           holidays=None) -> dict:
    """Cron → mode decision of spec §9.3.

    Returns ``{"mode": ..., "kind": ..., "reason": ...}``; ``mode == "skip"`` means
    nothing runs (non-trading day for ``morning``/``scan``).  ``eod``/``tune`` are
    never skipped.  ``workflow_dispatch`` with an explicit mode uses kind ``啟動``
    (``bake``/``replay`` do not change the kind, so ``kind`` is empty for them).
    """
    at = at or now()
    mode = (mode or "auto").strip() or "auto"
    if mode not in MODES:
        return {"mode": "skip", "kind": "", "reason": f"unknown mode {mode}"}
    if mode == "auto":
        if event == "schedule":
            table = {CRON_MORNING: "morning", CRON_SCAN: "scan", CRON_EOD: "eod", CRON_TUNE: "tune"}
            mode = table.get((cron or "").strip(), "")
            if not mode:
                return {"mode": "skip", "kind": "", "reason": f"unmapped cron {cron!r}"}
        else:
            # manual dispatch without a mode: infer from the Taipei clock
            t = at.astimezone(TZ)
            if t.weekday() == 5:
                mode = "tune"
            elif t.time() >= EOD_TIME:
                mode = "eod"
            elif t.time() >= time(8, 30) and t.time() < OPEN_TIME:
                mode = "morning"
            else:
                mode = "scan"
        kind = scan_kind(at) if mode == "scan" else (KIND_EOD if mode == "eod" else KIND_STARTUP)
    else:
        kind = "" if mode in ("bake", "replay") else KIND_STARTUP
        if mode == "scan":
            kind = scan_kind(at)
        if mode == "eod":
            kind = KIND_EOD
    if mode in ("morning", "scan") and not is_trading_day(at.astimezone(TZ).date(), holidays):
        return {"mode": "skip", "kind": "", "reason": "非交易日"}
    if mode == "replay" and not as_of:
        return {"mode": "skip", "kind": "", "reason": "replay needs --as-of"}
    return {"mode": mode, "kind": kind, "reason": f"{event}:{cron or '-'}"}
