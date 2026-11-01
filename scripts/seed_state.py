"""Build ``state/`` from the frozen 2026-10-31 snapshot (spec §9.6 seeding, §1.2 C3),
adopt params v10 (spec §6.5–§6.6) and seal the shadow panel (spec §6.7).

Usage:  python scripts/seed_state.py [--snapshot fixtures/snapshot-2026-10-31] [--state state]
                                     [--cutover 2026-11-01T12:00:00+08:00]
Idempotent: re-running on an already seeded state directory is a no-op (checks engine.json).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main(argv: list | None = None) -> int:
    raise NotImplementedError


if __name__ == "__main__":
    sys.exit(main())
