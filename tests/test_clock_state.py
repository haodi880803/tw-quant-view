import json

from engine import clock, state


def test_iso_format(frozen_now):
    n = clock.now()
    assert clock.iso(n) == frozen_now
    assert clock.iso(clock.parse_iso("2026-10-30T12:37:47Z")) == "2026-10-30T20:37:47+08:00"


def test_decide_table():
    at = clock.parse_iso("2026-10-30T09:00:10+08:00")
    assert clock.decide("schedule", clock.CRON_SCAN, "auto", "", at)["mode"] == "scan"
    assert clock.decide("schedule", clock.CRON_SCAN, "auto", "", at)["kind"] == "盤中"
    fixing = clock.parse_iso("2026-10-30T13:30:05+08:00")
    assert clock.decide("schedule", clock.CRON_SCAN, "auto", "", fixing)["kind"] == "收盤定盤"
    assert clock.decide("schedule", clock.CRON_EOD, "auto", "", at)["mode"] == "eod"
    assert clock.decide("schedule", clock.CRON_TUNE, "auto", "", at)["mode"] == "tune"
    sat = clock.parse_iso("2026-10-31T09:00:00+08:00")
    assert clock.decide("schedule", clock.CRON_SCAN, "auto", "", sat)["mode"] == "skip"
    assert clock.decide("schedule", clock.CRON_EOD, "auto", "", sat)["mode"] == "eod"
    hol = clock.decide("schedule", clock.CRON_SCAN, "auto", "", at, holidays=["2026-10-30"])
    assert hol == {"mode": "skip", "kind": "", "reason": "非交易日"}
    assert clock.decide("workflow_dispatch", "", "bake", "", at)["mode"] == "bake"
    assert clock.decide("workflow_dispatch", "", "eod", "", at)["kind"] == "EOD"


def test_week_helpers():
    d = clock.parse_date("2026-10-30")
    assert clock.iso_week(d) == "2026-W44"
    assert clock.monday_of(d).isoformat() == "2026-10-26"
    assert clock.previous_trading_day(d, ["2026-10-29"]).isoformat() == "2026-10-28"


def test_dumps_rejects_nan_and_roundtrips():
    raw = state.dumps({"a": [1.0, "中文", None, True, 0.625]})
    assert raw == '{"a": [1.0, "中文", null, true, 0.625]}'
    assert json.dumps(json.loads(raw), ensure_ascii=False) == raw
    try:
        state.dumps({"x": float("nan")})
        assert False, "NaN must be rejected"
    except ValueError:
        pass


def test_state_log_and_counters(tmp_state, frozen_now):
    st = state.State.load()
    st.engine = {"next_event_id": 6763, "next_order_id": 109, "next_params_id": 26}
    row = st.log("INFO", "engine", "hello\nworld")
    assert row == {"id": 6763, "ts": frozen_now, "level": "INFO", "source": "engine", "message": "hello world"}
    assert st.next_id("order") == 109 and st.engine["next_order_id"] == 110
    st.save()
    again = state.State.load()
    assert again.engine["next_event_id"] == 6764
    assert again.events[-1]["id"] == 6763
