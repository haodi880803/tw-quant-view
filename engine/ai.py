"""Claude calls with the global circuit breaker (spec §3.6, §8.3, D11).

Uses the official ``anthropic`` SDK; model aliases ``sonnet``/``opus`` map to real model
ids via ``st.engine["ai_models"]`` and only the aliases are ever published.  Without
``ANTHROPIC_API_KEY`` (or offline) every call returns ``None`` silently and the rule-based
paths are used.  Failures log ``AI 呼叫失敗({alias},rc={rc}):{tail}``; the 3rd consecutive
failure logs the 15-minute pause line instead (spec §8.3).
"""
from __future__ import annotations

from datetime import datetime

from .state import State

ALIASES = {"sonnet": "claude-sonnet-5-5", "opus": "claude-opus-5-5"}
NOTE_SUFFIX = "以上為數據解讀,非投資建議。"
REPORT_HEADINGS = ("大盤與市場氛圍", "觀察清單重點", "持倉與損益", "模型健康", "明日留意")


def enabled() -> bool:
    """``ANTHROPIC_API_KEY`` set and not offline."""
    raise NotImplementedError


def engine_block(st: State) -> dict:
    """``overview.engine.ai`` ``{"enabled", "model_fast": "sonnet", "model_deep": "opus"}``."""
    raise NotImplementedError


def paused(st: State, at: datetime) -> bool:
    raise NotImplementedError


def call(st: State, caller: str, alias: str, system: str, user: str, at: datetime,
         max_tokens: int = 2000) -> str | None:
    """One Claude call through the breaker; ``caller`` ∈ news|ai|tuner is the event source."""
    raise NotImplementedError


def score_title(st: State, title: str, at: datetime) -> int | None:
    """Integer sentiment −3…+3 from ``sonnet`` or ``None`` (fallback: ``scoring.lexicon_score``)."""
    raise NotImplementedError


def note(st: State, payload: dict, at: datetime) -> str | None:
    """Per-symbol plain-text note (≤ 5 paragraphs, ends with ``NOTE_SUFFIX``) via ``opus``."""
    raise NotImplementedError


def daily_report(st: State, payload: dict, at: datetime) -> str | None:
    """Markdown report with the five ``## `` headings via ``opus``."""
    raise NotImplementedError


def weekly_review(st: State, payload: dict, at: datetime) -> str | None:
    raise NotImplementedError


def tuner_candidate(st: State, payload: dict, at: datetime) -> dict | None:
    """Optional LLM-suggested params candidate for the tuner (spec §6.9)."""
    raise NotImplementedError
