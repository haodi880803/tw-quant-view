"""CLI (spec §2, §9.5):

    python -m engine schedule decide --event E --cron C --mode M --as-of D   → prints mode=/kind=/reason=
    python -m engine run --mode M [--kind K] [--offline] [--as-of D] [--dry-run]
    python -m engine bake
    python -m engine record --as-of D
    python -m engine replay --as-of D --mode M
"""
from __future__ import annotations

import argparse
import os
import sys


def main(argv: list | None = None) -> int:
    p = argparse.ArgumentParser(prog="engine")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("schedule")
    s.add_argument("action", choices=["decide"])
    s.add_argument("--event", default="workflow_dispatch")
    s.add_argument("--cron", default="")
    s.add_argument("--mode", default="auto")
    s.add_argument("--as-of", default="")

    r = sub.add_parser("run")
    r.add_argument("--mode", required=True)
    r.add_argument("--kind", default="")
    r.add_argument("--offline", action="store_true")
    r.add_argument("--as-of", default="")
    r.add_argument("--dry-run", action="store_true")

    sub.add_parser("bake")

    rec = sub.add_parser("record")
    rec.add_argument("--as-of", required=True)

    rp = sub.add_parser("replay")
    rp.add_argument("--as-of", required=True)
    rp.add_argument("--mode", default="eod")

    a = p.parse_args(argv)
    from . import clock, pipelines, state

    if a.cmd == "schedule":
        st = state.State.load()
        d = clock.decide(a.event, a.cron, a.mode, a.as_of, holidays=st.holidays)
        for k in ("mode", "kind", "reason"):
            print(f"{k}={d[k]}")
        return 0
    if a.cmd == "run":
        if a.offline:
            os.environ["TWQ_OFFLINE"] = "1"
        if a.as_of:
            os.environ["TWQ_AS_OF"] = a.as_of
        if a.dry_run:
            os.environ["TWQ_DRY_RUN"] = "1"
        pipelines.run(a.mode, a.kind)
        return 0
    if a.cmd == "bake":
        pipelines.run("bake", "")
        return 0
    if a.cmd == "record":
        from . import datafeed
        st = state.State.load()
        paths = datafeed.record_fixtures(st, a.as_of, clock.now())
        print("\n".join(str(x) for x in paths))
        return 0
    if a.cmd == "replay":
        os.environ["TWQ_OFFLINE"] = "1"
        os.environ["TWQ_AS_OF"] = a.as_of
        os.environ["TWQ_DRY_RUN"] = "1"
        pipelines.run(a.mode, "")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
