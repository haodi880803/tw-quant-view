"""Shadow A/B panel: manual seal and frozen publication (spec §6.7, §7.6).

The experiment is closed by owner decision in favour of arm B; after the seal the
panel (``state/shadow/panel.json``) is published verbatim and never recomputed.
"""
from __future__ import annotations

from datetime import datetime

from .state import State

SEAL_NEXT = "採用 B(risk-exit-consensus)為正式參數 v10;影子對照結案"
SEAL_EVENT = "影子對照裁決:B 組勝出,手動採用(第 55/60 交易日,B 平倉 2/10);risk-exit-consensus 升為正式參數 v10"


def seal_manual(panel: dict, at: datetime) -> dict:
    """Return the sealed ``shadow.json`` object per spec §6.7 (only ``progress``, ``verdict``,
    ``verdict_sealed``, ``computing``, ``refresh_failed`` change; key order preserved)."""
    raise NotImplementedError


def is_sealed(st: State) -> bool:
    raise NotImplementedError


def panel(st: State) -> dict:
    """The object to publish as ``shadow.json`` (the frozen sealed panel)."""
    raise NotImplementedError
