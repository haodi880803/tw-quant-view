"""``state/`` persistence, counters, event log and run-mode flags (spec §8.1, §9.6, §9.9).

Layout (all under ``state/``; everything is committed to git because hosted
runners are stateless — spec §1.2 C6, §9.6):

    engine.json          {"next_event_id", "next_order_id", "next_params_id", "params_version",
                          "last_scan", "last_scan_kind", "next_scan", "scan_interval_min",
                          "override" ("無覆蓋" | "風險覆蓋 caution"), "override_date",
                          "market_state" ("normal" | "caution" | "halt"), "market" (last overview.market),
                          "ai_fail_count", "ai_pause_until", "ai_last_success", "ai_last_error",
                          "last_publish", "ai_models" {"sonnet": <model id>, "opus": <model id>},
                          "morning_date", "last_eod_date", "last_fetch_failed" (bool)}
    watchlist.json       [{"symbol": "2330.TW", "code": "2330", "name": "台積電"}, ...] fixed order (spec §3.1)
    params.json          active params object (spec §6.1 / §6.5 for v10)
    params_history.json  all rows newest first, exactly the model-health.json ``params_history`` shape (spec §7.5)
    account.json         {"initial_cash", "cash", "realized_pnl",
                          "positions": [{"symbol","code","name","qty","cost","avg","peak","first_fill",
                                         "adds": {"date": "YYYY-MM-DD", "n": int}}],   # insertion order = first fill
                          "reward": {"total": int, "history": [...]},                # history newest first (spec §8.6)
                          "eod_equity": {"YYYY-MM-DD": equity_close}}                 # one entry per EOD, for month marks
    scan.json            {"ts", "kind", "market": {...}, "rows": [...]} — the rows[] of the last scan
                         in the data.json shape (used for ``changed``, baking and position marks)
    eod.json             {"history": {"YYYY-MM-DD": {"<code>": total}}} — EOD totals for gate G4 (≤ 20 days kept)
    orders.jsonl         every order ever (spec §7.3 row shape); bake publishes the newest 50
    events.jsonl         every event ever ({"id","ts","level","source","message"}); bake publishes the last 100
    predictions.jsonl    forecast ledger rows (spec §4.10):
                         {"symbol","code","model","horizon","made_date","pred_ret","target_date",
                          "realized","abs_err","hit","resolved_at"}  (realized/abs_err/hit/resolved_at null while pending)
    predictions_seed.json frozen aggregates recovered from the 2026-10-31 snapshot (spec Q-P13 / K8):
                         {"source", "by_model_horizon": [...], "series": [...], "by_symbol": {"<code>": [...]}}
    calendar.json        {"events": [{"code","date","kind","note"}], "holidays": ["YYYY-MM-DD", ...]}
    cache/bars/<code>.json     {"symbol","fetched_at","bars": [[date,o,h,l,c,v], ...]}  full history (≥ 500 bars)
    cache/bars60/<code>.json   {"symbol","fetched_at","bars": [[iso_ts,o,h,l,c,v], ...]}
    cache/news/<code>.json     {"refreshed_at","score","items": [...]} (symbol-file ``news`` shape + refreshed_at)
    cache/t86/<YYYY-MM-DD>.json {"date", "rows": {"<code>": {"foreign","invtrust","dealer","total"}}}
    cache/info/<code>.json     {"fetched_at", "info": {...yfinance-style keys...}}
    cache/twii.json            {"fetched_at","bars": [[date,o,h,l,c,v], ...]}
    cache/quotes.json          {"<symbol>": {"price","ts","fresh"}} — quotes of the last scan
    shadow/panel.json          the sealed shadow.json object (frozen after the manual seal, spec §6.7)
    shadow/ledger.jsonl, fills_a.jsonl, fills_b.jsonl, spec.json, seal.json — archived arm data (spec §9.6)
    ai/report.json       {"date","generated_at","content"}
    ai/weekly.json       {"week","generated_at","text"} or absent
    ai/notes/<code>.json {"ts","rec_code","text"}
    KILL                 presence ⇒ engine.kill (spec §5.5)

Environment flags (spec §9.7, §9.9): ``TWQ_STATE_DIR`` (default ``<repo>/state``),
``TWQ_OFFLINE=1`` (serve every fetch from ``fixtures/<TWQ_AS_OF>/``), ``TWQ_AS_OF``,
``TWQ_NOW``, ``TWQ_DRY_RUN=1`` (no commit/push/heartbeat), ``TWQ_NIGHT_SYMBOL``.
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from . import clock

REPO_ROOT = Path(__file__).resolve().parent.parent
PUBLISHED_FILES = ("data.json", "orders.json", "events.json", "model-health.json", "shadow.json", "simple.html")

EVENT_LEVELS = ("INFO", "WARN", "ERROR")
EVENT_SOURCES = ("engine", "news", "ai", "tuner", "broker", "heartbeat", "data")


# ---------------------------------------------------------------- flags

def state_dir() -> Path:
    return Path(os.environ.get("TWQ_STATE_DIR") or (REPO_ROOT / "state"))


def offline() -> bool:
    return os.environ.get("TWQ_OFFLINE", "").strip() in ("1", "true", "yes")


def dry_run() -> bool:
    return os.environ.get("TWQ_DRY_RUN", "").strip() in ("1", "true", "yes")


def as_of() -> str:
    return os.environ.get("TWQ_AS_OF", "").strip()


def fixture_dir() -> Path:
    """``fixtures/<as_of>/`` used by offline replays (spec §9.9)."""
    return REPO_ROOT / "fixtures" / (as_of() or "latest")


# ---------------------------------------------------------------- serialization

def dumps(obj: Any) -> str:
    """Canonical published serialization (spec §1.5): one line, ``ensure_ascii=False``,
    default separators, NaN/Infinity rejected (spec §1.2 C4)."""
    return json.dumps(obj, ensure_ascii=False, allow_nan=False)


def check_finite(obj: Any, path: str = "$") -> None:
    """Raise ``ValueError`` naming the first NaN/Infinity found anywhere in ``obj``."""
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            raise ValueError(f"non-finite float at {path}")
    elif isinstance(obj, dict):
        for k, v in obj.items():
            check_finite(v, f"{path}.{k}")
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            check_finite(v, f"{path}[{i}]")


def write_text(path: Path, text: str) -> None:
    """Atomic UTF-8 write (tmp file + rename)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def write_published_json(path: Path, obj: Any) -> str:
    """Write a published JSON file exactly as the lost engine did (no trailing newline)."""
    raw = dumps(obj)
    assert json.dumps(json.loads(raw), ensure_ascii=False) == raw, f"round-trip broken for {path}"
    write_text(path, raw)
    return raw


def read_json(path: Path, default: Any = None) -> Any:
    path = Path(path)
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, obj: Any) -> None:
    """State-file JSON: pretty-ish (indent 1) so git diffs stay readable; NaN rejected."""
    write_text(path, json.dumps(obj, ensure_ascii=False, allow_nan=False, indent=1) + "\n")


def read_jsonl(path: Path) -> list:
    path = Path(path)
    if not path.exists():
        return []
    out = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def append_jsonl(path: Path, row: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")


def write_jsonl(path: Path, rows: list) -> None:
    write_text(path, "".join(json.dumps(r, ensure_ascii=False, allow_nan=False) + "\n" for r in rows))


# ---------------------------------------------------------------- State

class State:
    """In-memory mirror of ``state/``.  ``load()`` reads everything small; the
    JSONL ledgers are loaded lazily by the properties below; ``save()`` writes
    the small files back (ledgers are append-only and written as they grow).
    """

    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root else state_dir()
        self.engine: dict = {}
        self.watchlist: list = []
        self.params: dict = {}
        self.params_history: list = []
        self.account: dict = {}
        self.scan: dict = {}
        self.eod: dict = {}
        self.calendar: dict = {}
        self._orders: list | None = None
        self._events: list | None = None
        self._predictions: list | None = None
        self._predictions_seed: dict | None = None
        self.new_events: list = []      # events appended during this run (for the log)

    # ----- paths
    def path(self, *parts: str) -> Path:
        return self.root.joinpath(*parts)

    def cache_path(self, kind: str, key: str) -> Path:
        return self.root / "cache" / kind / f"{key}.json"

    def read_cache(self, kind: str, key: str, default: Any = None) -> Any:
        return read_json(self.cache_path(kind, key), default)

    def write_cache(self, kind: str, key: str, obj: Any) -> None:
        write_json(self.cache_path(kind, key), obj)

    # ----- load / save
    @classmethod
    def load(cls, root: Path | None = None) -> "State":
        st = cls(root)
        st.engine = read_json(st.path("engine.json"), {}) or {}
        st.watchlist = read_json(st.path("watchlist.json"), []) or []
        st.params = read_json(st.path("params.json"), {}) or {}
        st.params_history = read_json(st.path("params_history.json"), []) or []
        st.account = read_json(st.path("account.json"), {}) or {}
        st.scan = read_json(st.path("scan.json"), {}) or {}
        st.eod = read_json(st.path("eod.json"), {"history": {}}) or {"history": {}}
        st.calendar = read_json(st.path("calendar.json"), {"events": [], "holidays": []}) or {}
        return st

    def save(self) -> None:
        write_json(self.path("engine.json"), self.engine)
        write_json(self.path("watchlist.json"), self.watchlist)
        write_json(self.path("params.json"), self.params)
        write_json(self.path("params_history.json"), self.params_history)
        write_json(self.path("account.json"), self.account)
        write_json(self.path("scan.json"), self.scan)
        write_json(self.path("eod.json"), self.eod)
        write_json(self.path("calendar.json"), self.calendar)

    # ----- ledgers (lazy)
    @property
    def orders(self) -> list:
        if self._orders is None:
            self._orders = read_jsonl(self.path("orders.jsonl"))
        return self._orders

    @property
    def events(self) -> list:
        if self._events is None:
            self._events = read_jsonl(self.path("events.jsonl"))
        return self._events

    @property
    def predictions(self) -> list:
        if self._predictions is None:
            self._predictions = read_jsonl(self.path("predictions.jsonl"))
        return self._predictions

    @property
    def predictions_seed(self) -> dict:
        if self._predictions_seed is None:
            self._predictions_seed = read_json(self.path("predictions_seed.json"), {}) or {}
        return self._predictions_seed

    def save_predictions(self) -> None:
        """Rewrite the ledger after an upsert (resolution mutates rows in place)."""
        if self._predictions is not None:
            write_jsonl(self.path("predictions.jsonl"), self._predictions)

    def append_order(self, order: dict) -> None:
        self.orders.append(order)
        append_jsonl(self.path("orders.jsonl"), order)

    # ----- counters (spec §1.2 C3)
    def next_id(self, kind: str) -> int:
        """``kind`` ∈ ``event`` | ``order`` | ``params``; returns the id and advances the counter."""
        key = f"next_{kind}_id"
        cur = int(self.engine.get(key, 1))
        self.engine[key] = cur + 1
        return cur

    # ----- events (spec §8.1)
    def log(self, level: str, source: str, message: str, at: datetime | None = None) -> dict:
        assert level in EVENT_LEVELS, level
        assert source in EVENT_SOURCES, source
        message = " ".join(str(message).splitlines())      # single line
        row = {"id": self.next_id("event"), "ts": clock.iso(at or clock.now()),
               "level": level, "source": source, "message": message}
        self.events.append(row)
        self.new_events.append(row)
        append_jsonl(self.path("events.jsonl"), row)
        return row

    # ----- misc
    @property
    def kill(self) -> bool:
        return self.path("KILL").exists()

    def symbol_of(self, code: str) -> dict | None:
        for w in self.watchlist:
            if w["code"] == code or w["symbol"] == code:
                return w
        return None

    @property
    def holidays(self) -> list:
        return list(self.calendar.get("holidays") or [])

    def position(self, code: str) -> dict | None:
        for p in self.account.get("positions", []):
            if p["code"] == code:
                return p
        return None
