"""Deterministic whole-game review selection from existing move analyses.

The selector is deliberately a cheap post-processing layer. It does not call
KataGo, LogosEngine, a classifier, CSV data, or any mutable global service.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

from analysis_logic import IMPORTANCE_THRESHOLDS, ImportanceThresholds


GAME_REVIEW_SCHEMA_VERSION = 1
REVIEW_HARD_MAX = 8


class SelectionReason:
    DECISIVE_MOVE = "decisive_move"
    IMPORTANT_MOVE = "important_move"
    NOTICE_FALLBACK = "notice_fallback"
    LARGE_OBSERVED_CHANGE = "large_observed_change"
    RELIABLE_RECOMMENDATION = "reliable_recommendation"
    VARIATION_AVAILABLE = "variation_available"
    HIGHEST_SEVERITY_IN_CLUSTER = "highest_severity_in_cluster"
    ADDITIONAL_STRONG_DECISIVE = "additional_strong_decisive_in_cluster"
    ABOVE_TARGET_STRONG_DECISIVE = "selected_above_target_as_strong_decisive"


class SuppressionReason:
    NEARBY_LOWER_SEVERITY = "nearby_lower_severity"
    REVIEW_TARGET_CAPACITY = "review_target_capacity"
    REVIEW_MAXIMUM_CAPACITY = "review_maximum_capacity"
    INVALID_STRUCTURED_EXPLANATION = "invalid_structured_explanation"


@dataclass(frozen=True)
class ReviewSelectionConfig:
    target_highlights: int = 5
    max_highlights: int = REVIEW_HARD_MAX
    nearby_window: int = 3
    decisive_exception_ratio: float = 1.5
    decisive_exception_min_distance: int = 2
    allow_notice_fallback: bool = False


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


def _tier(importance: Any) -> int:
    return {"notice": 1, "important": 2, "decisive": 3}.get(importance, 0)


def _threshold_pair(
    importance: str,
    thresholds: ImportanceThresholds,
) -> tuple[float, float]:
    if importance == "decisive":
        return (
            thresholds.decisive_winrate_loss,
            thresholds.decisive_score_loss,
        )
    if importance == "important":
        return (
            thresholds.important_winrate_loss,
            thresholds.important_score_loss,
        )
    return thresholds.notice_winrate_loss, thresholds.notice_score_loss


def _threshold_ratio(
    winrate_loss: Any,
    score_loss: Any,
    importance: str,
    thresholds: ImportanceThresholds,
) -> float:
    winrate_threshold, score_threshold = _threshold_pair(
        importance, thresholds
    )
    winrate = max(0.0, _finite(winrate_loss) or 0.0)
    score = max(0.0, _finite(score_loss) or 0.0)
    return max(winrate / winrate_threshold, score / score_threshold)


def _explanation(record: dict[str, Any]) -> dict[str, Any]:
    return _mapping(record.get("structured_explanation"))


def _recommendation(explanation: dict[str, Any]) -> dict[str, Any]:
    return _mapping(explanation.get("recommendation"))


def _severity_parts(
    record: dict[str, Any],
    thresholds: ImportanceThresholds,
) -> dict[str, Any] | None:
    explanation = _explanation(record)
    move = _mapping(explanation.get("move"))
    severity = _mapping(explanation.get("severity"))
    observed = _mapping(severity.get("observed"))
    combined = _mapping(severity.get("combined_importance_basis"))
    move_number = _positive_int(move.get("number"))
    player = move.get("player")
    actual_move = move.get("actual")
    observed_wr = _finite(observed.get("winrate_loss"))
    observed_score = _finite(observed.get("score_loss"))
    if (
        explanation.get("schema_version") != 1
        or move_number is None
        or player not in {"B", "W"}
        or not isinstance(actual_move, str)
        or not actual_move
        or (observed_wr is None and observed_score is None)
    ):
        return None

    importance = record.get("importance")
    if importance not in {"notice", "important", "decisive"}:
        return None
    combined_wr = _finite(combined.get("winrate_loss"))
    combined_score = _finite(combined.get("score_loss"))
    if combined_wr is None:
        combined_wr = observed_wr
    if combined_score is None:
        combined_score = observed_score
    combined_ratio = _threshold_ratio(
        combined_wr,
        combined_score,
        importance,
        thresholds,
    )
    observed_ratio = _threshold_ratio(
        observed_wr,
        observed_score,
        importance,
        thresholds,
    )
    recommendation = _recommendation(explanation)
    recommendation_available = (
        recommendation.get("reliable") is True
        and isinstance(recommendation.get("move"), str)
        and bool(recommendation.get("move"))
    )
    variation_available = recommendation.get("variation_available") is True
    return {
        "record": record,
        "explanation": explanation,
        "move_number": move_number,
        "player": player,
        "actual_move": actual_move,
        "importance": importance,
        "importance_tier": _tier(importance),
        "combined_winrate_loss": combined_wr,
        "combined_score_loss": combined_score,
        "observed_winrate_loss": observed_wr,
        "observed_score_loss": observed_score,
        "combined_threshold_ratio": combined_ratio,
        "observed_threshold_ratio": observed_ratio,
        "recommendation_available": recommendation_available,
        "variation_available": variation_available,
        "selection_reasons": [],
    }


def _ranking_key(candidate: dict[str, Any]) -> tuple[Any, ...]:
    """Rank without adding unlike winrate and score units."""

    return (
        -candidate["importance_tier"],
        -candidate["combined_threshold_ratio"],
        -candidate["observed_threshold_ratio"],
        -int(candidate["recommendation_available"]),
        -int(candidate["variation_available"]),
        candidate["move_number"],
    )


def _clusters(
    candidates: list[dict[str, Any]],
    nearby_window: int,
) -> list[list[dict[str, Any]]]:
    ordered = sorted(candidates, key=lambda item: item["move_number"])
    clusters: list[list[dict[str, Any]]] = []
    for candidate in ordered:
        if (
            not clusters
            or candidate["move_number"]
            - clusters[-1][-1]["move_number"]
            > nearby_window
        ):
            clusters.append([candidate])
        else:
            clusters[-1].append(candidate)
    return clusters


def _can_keep_decisive_exception(
    candidate: dict[str, Any],
    selected: list[dict[str, Any]],
    config: ReviewSelectionConfig,
) -> bool:
    if (
        candidate["importance"] != "decisive"
        or candidate["combined_threshold_ratio"]
        < config.decisive_exception_ratio
    ):
        return False
    for existing in selected:
        if (
            existing["importance"] != "decisive"
            or existing["combined_threshold_ratio"]
            < config.decisive_exception_ratio
            or abs(existing["move_number"] - candidate["move_number"])
            < config.decisive_exception_min_distance
        ):
            return False
    return True


def _nearest_selected(
    candidate: dict[str, Any],
    selected: list[dict[str, Any]],
) -> dict[str, Any]:
    return min(
        selected,
        key=lambda item: (
            abs(item["move_number"] - candidate["move_number"]),
            _ranking_key(item),
        ),
    )


def _selection_reasons(
    candidate: dict[str, Any],
    cluster_reason: str,
    thresholds: ImportanceThresholds,
    *,
    notice_fallback_used: bool,
) -> list[str]:
    if candidate["importance"] == "decisive":
        reasons = [SelectionReason.DECISIVE_MOVE]
    elif candidate["importance"] == "important":
        reasons = [SelectionReason.IMPORTANT_MOVE]
    else:
        reasons = [SelectionReason.NOTICE_FALLBACK]
    important_observed_ratio = _threshold_ratio(
        candidate["observed_winrate_loss"],
        candidate["observed_score_loss"],
        "important",
        thresholds,
    )
    if important_observed_ratio >= 1.0:
        reasons.append(SelectionReason.LARGE_OBSERVED_CHANGE)
    if candidate["recommendation_available"]:
        reasons.append(SelectionReason.RELIABLE_RECOMMENDATION)
    if candidate["variation_available"]:
        reasons.append(SelectionReason.VARIATION_AVAILABLE)
    if cluster_reason not in reasons:
        reasons.append(cluster_reason)
    if notice_fallback_used and SelectionReason.NOTICE_FALLBACK not in reasons:
        reasons.insert(0, SelectionReason.NOTICE_FALLBACK)
    return reasons


def _game_phase(move_number: int, total_moves: int) -> str:
    if total_moves <= 0:
        return "unknown"
    progress = move_number / total_moves
    if progress <= 1 / 3:
        return "opening"
    if progress <= 2 / 3:
        return "middle"
    return "endgame"


def _suppression_entry(
    candidate: dict[str, Any],
    reason: str,
    *,
    suppressed_by: int | None = None,
) -> dict[str, Any]:
    return {
        "move_number": candidate.get("move_number"),
        "importance": candidate.get("importance"),
        "suppressed_by_move": suppressed_by,
        "reason": reason,
    }


def _validate_config(config: ReviewSelectionConfig) -> tuple[int, int]:
    if config.target_highlights < 1:
        raise ValueError("target_highlights 必須至少為 1")
    if config.max_highlights < 1:
        raise ValueError("max_highlights 必須至少為 1")
    if config.nearby_window < 0:
        raise ValueError("nearby_window 不可為負數")
    effective_max = min(config.max_highlights, REVIEW_HARD_MAX)
    return min(config.target_highlights, effective_max), effective_max


def build_game_review(
    move_analyses: Any,
    *,
    total_moves: int | None = None,
    config: ReviewSelectionConfig = ReviewSelectionConfig(),
    thresholds: ImportanceThresholds = IMPORTANCE_THRESHOLDS,
) -> dict[str, Any]:
    """Select review highlights without mutating the move analyses."""

    target, maximum = _validate_config(config)
    records = move_analyses if isinstance(move_analyses, list) else []
    resolved_total = (
        total_moves
        if isinstance(total_moves, int) and total_moves >= 0
        else len(records)
    )
    counts = {
        importance: sum(
            1
            for record in records
            if isinstance(record, dict)
            and record.get("importance") == importance
        )
        for importance in ("notice", "important", "decisive")
    }
    primary_records = [
        record
        for record in records
        if isinstance(record, dict)
        and record.get("importance") in {"important", "decisive"}
    ]
    notice_fallback_used = False
    if not primary_records and config.allow_notice_fallback:
        primary_records = [
            record
            for record in records
            if isinstance(record, dict) and record.get("importance") == "notice"
        ]
        notice_fallback_used = bool(primary_records)

    eligible: list[dict[str, Any]] = []
    suppressed: list[dict[str, Any]] = []
    for record in primary_records:
        candidate = _severity_parts(record, thresholds)
        if candidate is None:
            suppressed.append(
                {
                    "move_number": record.get("move_number"),
                    "importance": record.get("importance"),
                    "suppressed_by_move": None,
                    "reason": SuppressionReason.INVALID_STRUCTURED_EXPLANATION,
                }
            )
        else:
            eligible.append(candidate)

    survivors: list[dict[str, Any]] = []
    nearby_suppressed_by_selected: dict[int, list[int]] = {}
    for cluster in _clusters(eligible, config.nearby_window):
        ranked = sorted(cluster, key=_ranking_key)
        primary = ranked[0]
        primary["selection_reasons"] = _selection_reasons(
            primary,
            SelectionReason.HIGHEST_SEVERITY_IN_CLUSTER,
            thresholds,
            notice_fallback_used=notice_fallback_used,
        )
        cluster_selected = [primary]
        survivors.append(primary)
        for candidate in ranked[1:]:
            if _can_keep_decisive_exception(candidate, cluster_selected, config):
                candidate["selection_reasons"] = _selection_reasons(
                    candidate,
                    SelectionReason.ADDITIONAL_STRONG_DECISIVE,
                    thresholds,
                    notice_fallback_used=notice_fallback_used,
                )
                cluster_selected.append(candidate)
                survivors.append(candidate)
                continue
            selected = _nearest_selected(candidate, cluster_selected)
            suppressed.append(
                _suppression_entry(
                    candidate,
                    SuppressionReason.NEARBY_LOWER_SEVERITY,
                    suppressed_by=selected["move_number"],
                )
            )
            nearby_suppressed_by_selected.setdefault(
                selected["move_number"], []
            ).append(candidate["move_number"])

    ranked_survivors = sorted(survivors, key=_ranking_key)
    selected: list[dict[str, Any]] = []
    for candidate in ranked_survivors:
        if len(selected) < target:
            selected.append(candidate)
            continue
        if len(selected) >= maximum:
            suppressed.append(
                _suppression_entry(
                    candidate,
                    SuppressionReason.REVIEW_MAXIMUM_CAPACITY,
                )
            )
            continue
        if (
            candidate["importance"] == "decisive"
            and candidate["combined_threshold_ratio"]
            >= config.decisive_exception_ratio
        ):
            candidate["selection_reasons"].append(
                SelectionReason.ABOVE_TARGET_STRONG_DECISIVE
            )
            selected.append(candidate)
        else:
            suppressed.append(
                _suppression_entry(
                    candidate,
                    SuppressionReason.REVIEW_TARGET_CAPACITY,
                )
            )

    highlights = []
    for review_index, candidate in enumerate(
        sorted(selected, key=lambda item: item["move_number"]),
        start=1,
    ):
        highlights.append(
            {
                "review_index": review_index,
                "move_number": candidate["move_number"],
                "player": candidate["player"],
                "actual_move": candidate["actual_move"],
                "importance": candidate["importance"],
                "phase": _game_phase(candidate["move_number"], resolved_total),
                "selection": {
                    "severity_basis": {
                        "importance_tier": candidate["importance_tier"],
                        "combined_threshold_ratio": candidate[
                            "combined_threshold_ratio"
                        ],
                        "observed_threshold_ratio": candidate[
                            "observed_threshold_ratio"
                        ],
                        "combined_winrate_loss": candidate[
                            "combined_winrate_loss"
                        ],
                        "combined_score_loss": candidate[
                            "combined_score_loss"
                        ],
                        "observed_winrate_loss": candidate[
                            "observed_winrate_loss"
                        ],
                        "observed_score_loss": candidate[
                            "observed_score_loss"
                        ],
                    },
                    "reasons": list(candidate["selection_reasons"]),
                    "suppressed_nearby_moves": sorted(
                        nearby_suppressed_by_selected.get(
                            candidate["move_number"], []
                        )
                    ),
                },
                "explanation": candidate["explanation"],
                "recommendation_available": candidate[
                    "recommendation_available"
                ],
                "variation_available": candidate["variation_available"],
            }
        )

    suppressed.sort(
        key=lambda item: (
            item.get("move_number") is None,
            item.get("move_number") or 0,
            item["reason"],
        )
    )
    return {
        "schema_version": GAME_REVIEW_SCHEMA_VERSION,
        "summary": {
            "total_moves": resolved_total,
            "notice_count": counts["notice"],
            "important_count": counts["important"],
            "decisive_count": counts["decisive"],
            "candidate_count": len(primary_records),
            "eligible_candidate_count": len(eligible),
            "selected_count": len(highlights),
            "suppressed_count": len(suppressed),
            "notice_fallback_used": notice_fallback_used,
            "target_highlights": target,
            "max_highlights": maximum,
            "nearby_window": config.nearby_window,
        },
        "highlights": highlights,
        "suppressed": suppressed,
    }
