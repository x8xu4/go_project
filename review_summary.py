"""Evidence-grounded whole-game review summaries.

This module only reads the Phase 4B ``game_review`` model. It does not alter
highlight selection, call KataGo, inspect classifier output, or infer Go
principles from geometry.
"""

from __future__ import annotations

import math
from typing import Any


REVIEW_SUMMARY_SCHEMA_VERSION = 1


class ReviewSummaryLimitation:
    NO_HIGHLIGHTS = "no_highlights"
    LIMITED_HIGHLIGHTS = "limited_highlights"
    INCOMPLETE_EXPLANATION_EVIDENCE = "incomplete_explanation_evidence"
    SPECIFIC_GO_PATTERNS_NOT_ESTABLISHED = (
        "specific_go_patterns_not_established"
    )


class ReviewSummaryReason:
    HIGHEST_PHASE4B_SEVERITY = "highest_phase4b_severity"


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _finite(value: Any) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _positive_int(value: Any) -> int | None:
    number = _finite(value)
    if number is None or int(number) != number or number < 1:
        return None
    return int(number)


def _importance_tier(highlight: dict[str, Any]) -> int:
    basis = _mapping(_mapping(highlight.get("selection")).get("severity_basis"))
    stored = _finite(basis.get("importance_tier"))
    if stored is not None:
        return int(stored)
    return {
        "notice": 1,
        "important": 2,
        "decisive": 3,
    }.get(highlight.get("importance"), 0)


def _severity_order_key(highlight: dict[str, Any]) -> tuple[Any, ...]:
    """Mirror Phase 4B ranking using its persisted severity basis."""

    selection = _mapping(highlight.get("selection"))
    basis = _mapping(selection.get("severity_basis"))
    combined_ratio = _finite(basis.get("combined_threshold_ratio")) or 0.0
    observed_ratio = _finite(basis.get("observed_threshold_ratio")) or 0.0
    move_number = _positive_int(highlight.get("move_number")) or 0
    return (
        -_importance_tier(highlight),
        -combined_ratio,
        -observed_ratio,
        -int(highlight.get("recommendation_available") is True),
        -int(highlight.get("variation_available") is True),
        move_number,
    )


def _valid_highlights(game_review: dict[str, Any]) -> list[dict[str, Any]]:
    raw = game_review.get("highlights")
    if not isinstance(raw, list):
        return []
    return [
        highlight
        for highlight in raw
        if isinstance(highlight, dict)
        and _positive_int(highlight.get("move_number")) is not None
    ]


def _observed_loss(highlight: dict[str, Any], key: str) -> float | None:
    selection = _mapping(highlight.get("selection"))
    basis = _mapping(selection.get("severity_basis"))
    value = _finite(basis.get(key))
    return max(0.0, value) if value is not None else None


def _largest_observed(
    highlights: list[dict[str, Any]],
    key: str,
) -> dict[str, Any] | None:
    available = [
        (highlight, _observed_loss(highlight, key))
        for highlight in highlights
    ]
    available = [item for item in available if item[1] is not None]
    if not available:
        return None
    highlight, loss = max(
        available,
        key=lambda item: (
            item[1],
            -(_positive_int(item[0].get("move_number")) or 0),
        ),
    )
    return {
        "move_number": _positive_int(highlight.get("move_number")),
        "observed_loss": loss,
    }


def _has_complete_explanation(highlight: dict[str, Any]) -> bool:
    explanation = _mapping(highlight.get("explanation"))
    move = _mapping(explanation.get("move"))
    severity = _mapping(explanation.get("severity"))
    observed = _mapping(severity.get("observed"))
    return (
        explanation.get("schema_version") == 1
        and _positive_int(move.get("number")) is not None
        and move.get("player") in {"B", "W"}
        and isinstance(move.get("actual"), str)
        and bool(move.get("actual"))
        and (
            _finite(observed.get("winrate_loss")) is not None
            or _finite(observed.get("score_loss")) is not None
        )
    )


def build_structured_review_summary(game_review: Any) -> dict[str, Any]:
    """Build a JSON-safe summary without mutating the Phase 4B review."""

    game_review = _mapping(game_review)
    highlights = _valid_highlights(game_review)
    chronological = sorted(
        highlights,
        key=lambda item: _positive_int(item.get("move_number")) or 0,
    )
    severity_order = sorted(highlights, key=_severity_order_key)
    primary = severity_order[0] if severity_order else None
    review_order = [
        _positive_int(highlight.get("move_number"))
        for highlight in chronological
    ]
    priority_order = [
        _positive_int(highlight.get("move_number"))
        for highlight in severity_order
    ]
    phase_distribution = {
        "opening": 0,
        "middle": 0,
        "endgame": 0,
        "unknown": 0,
    }
    for highlight in highlights:
        phase = highlight.get("phase")
        if phase not in phase_distribution:
            phase = "unknown"
        phase_distribution[phase] += 1

    limitations = [ReviewSummaryLimitation.SPECIFIC_GO_PATTERNS_NOT_ESTABLISHED]
    if not highlights:
        limitations.insert(0, ReviewSummaryLimitation.NO_HIGHLIGHTS)
    elif len(highlights) <= 2:
        limitations.insert(0, ReviewSummaryLimitation.LIMITED_HIGHLIGHTS)
    raw_highlights = game_review.get("highlights")
    raw_highlight_count = len(raw_highlights) if isinstance(raw_highlights, list) else 0
    if len(highlights) != raw_highlight_count or any(
        not _has_complete_explanation(highlight) for highlight in highlights
    ):
        limitations.insert(
            0,
            ReviewSummaryLimitation.INCOMPLETE_EXPLANATION_EVIDENCE,
        )

    selected_important = sum(
        1 for highlight in highlights if highlight.get("importance") == "important"
    )
    selected_decisive = sum(
        1 for highlight in highlights if highlight.get("importance") == "decisive"
    )
    return {
        "schema_version": REVIEW_SUMMARY_SCHEMA_VERSION,
        "overview": {
            "highlight_count": len(highlights),
            "important_highlight_count": selected_important,
            "decisive_highlight_count": selected_decisive,
        },
        "priority": {
            "primary_move": _positive_int(primary.get("move_number"))
            if primary is not None
            else None,
            "reasons": [ReviewSummaryReason.HIGHEST_PHASE4B_SEVERITY]
            if primary is not None
            else [],
            "other_priority_moves": priority_order[1:],
        },
        "phase_distribution": phase_distribution,
        "largest_observed_changes": {
            "winrate": _largest_observed(
                highlights, "observed_winrate_loss"
            ),
            "score": _largest_observed(highlights, "observed_score_loss"),
        },
        "review_order": review_order,
        "variation_available_count": sum(
            1
            for highlight in highlights
            if highlight.get("variation_available") is True
        ),
        "limitations": limitations,
    }


def _move_list(move_numbers: Any) -> str:
    if not isinstance(move_numbers, list) or not move_numbers:
        return ""
    valid = [str(move) for move in move_numbers if _positive_int(move) is not None]
    return "第 " + "、".join(valid) + " 手" if valid else ""


def _phase_text(distribution: dict[str, Any]) -> str:
    names = (("opening", "開局"), ("middle", "中盤"), ("endgame", "後段"))
    parts = [
        f"{label} {int(distribution.get(key, 0))} 個"
        for key, label in names
        if isinstance(distribution.get(key), int) and distribution.get(key) > 0
    ]
    unknown = distribution.get("unknown")
    if isinstance(unknown, int) and unknown > 0:
        parts.append(f"未分類 {unknown} 個")
    return "、".join(parts)


def render_auto_review_summary(summary: Any) -> str:
    """Render a concise deterministic whole-game summary."""

    summary = _mapping(summary)
    overview = _mapping(summary.get("overview"))
    priority = _mapping(summary.get("priority"))
    count = int(_finite(overview.get("highlight_count")) or 0)
    decisive_count = int(
        _finite(overview.get("decisive_highlight_count")) or 0
    )
    order = summary.get("review_order")
    order = order if isinstance(order, list) else []
    primary = _positive_int(priority.get("primary_move"))
    if count == 0:
        return "目前沒有選出足夠明確的主要復盤重點。"
    if count == 1:
        move_text = _move_list(order)
        return f"本局整理出 1 個主要復盤重點，位於{move_text}。建議先從這一手開始查看。"

    first = f"本局整理出 {count} 個主要復盤重點"
    if decisive_count > 0:
        first += f"，包含 {decisive_count} 個明顯局勢轉折"
    first += "。"
    second = (
        f"若只先看一處，建議從第 {primary} 手開始。"
        if primary is not None
        else ""
    )
    third = f"重點分布在{_move_list(order)}。" if order else ""
    return "\n".join(part for part in (first, second, third) if part)


def _largest_change_text(
    largest: dict[str, Any],
    key: str,
) -> str | None:
    entry = _mapping(largest.get(key))
    move_number = _positive_int(entry.get("move_number"))
    loss = _finite(entry.get("observed_loss"))
    if move_number is None or loss is None or loss <= 0.0:
        return None
    if key == "winrate":
        return (
            f"在已選重點中，第 {move_number} 手落子後的勝率估計下降幅度最大，"
            f"約 {loss * 100:.1f} 個百分點。"
        )
    return (
        f"第 {move_number} 手落子後的目數評估下降幅度最大，"
        f"約 {loss:.1f} 目。"
    )


def render_detailed_review_summary(summary: Any) -> str:
    """Render a detailed summary without unsupported Go-pattern claims."""

    summary = _mapping(summary)
    overview = _mapping(summary.get("overview"))
    priority = _mapping(summary.get("priority"))
    count = int(_finite(overview.get("highlight_count")) or 0)
    order = summary.get("review_order")
    order = order if isinstance(order, list) else []
    if count == 0:
        return (
            "目前沒有選出足夠明確的主要復盤重點。\n\n"
            "本次總結只使用客觀局勢變化，不會為了湊數加入較弱的位置。"
        )

    paragraphs = [
        f"本局共選出 {count} 個主要復盤位置：{_move_list(order)}。"
    ]
    primary = _positive_int(priority.get("primary_move"))
    if count == 1:
        paragraphs.append("依目前的客觀評估變化，建議優先回看這一手。")
    elif primary is not None:
        paragraphs.append(
            f"第 {primary} 手依目前的客觀評估變化排序，"
            "是最值得優先回看的位置。"
        )

    largest = _mapping(summary.get("largest_observed_changes"))
    largest_parts = [
        text
        for key in ("winrate", "score")
        if (text := _largest_change_text(largest, key)) is not None
    ]
    if largest_parts:
        paragraphs.append("".join(largest_parts))

    phase_text = _phase_text(_mapping(summary.get("phase_distribution")))
    if phase_text:
        paragraphs.append(f"這些重點的棋局階段分布為：{phase_text}。")
    paragraphs.append(
        f"建議依棋局順序查看：{_move_list(order)}。"
        "每個位置都可回到既有單手分析查看客觀變化；"
        "若有可靠推薦，也可查看相應內容。"
    )
    variation_count = int(
        _finite(summary.get("variation_available_count")) or 0
    )
    if variation_count > 0:
        if count == 1:
            paragraphs.append("此位置保存了可靠的推薦變化，可在棋盤上查看。")
        else:
            paragraphs.append(
                f"其中 {variation_count} 個位置保存了可靠的推薦變化，"
                "可在棋盤上查看。"
            )
    paragraphs.append(
        "目前總結以客觀局勢變化與 KataGo 推薦為主，"
        "不對整盤棋推測尚未被證據支持的棋理模式。"
    )
    return "\n\n".join(paragraphs)


def build_review_summary(game_review: Any) -> dict[str, Any]:
    """Build structured summary plus deterministic rendered forms."""

    structured = build_structured_review_summary(game_review)
    return {
        **structured,
        "rendered": {
            "auto": render_auto_review_summary(structured),
            "detailed": render_detailed_review_summary(structured),
        },
    }
