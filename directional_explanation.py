"""Deterministic board-direction evidence derived from Phase 2 features.

This module describes geometry visible in already-computed KataGo evidence. It
does not infer urgency, attack, defense, shape, timing, or any other Go cause.
"""

from __future__ import annotations

from typing import Any

from explanation_features import compare_moves, region_of


DIRECTIONAL_EVIDENCE_SCHEMA_VERSION = 1

REGION_LABELS_ZH = {
    "top-left": "左上",
    "top": "上方",
    "top-right": "右上",
    "left": "左側",
    "center": "中央",
    "right": "右側",
    "bottom-left": "左下",
    "bottom": "下方",
    "bottom-right": "右下",
}


class DirectionalFactId:
    SAME_DIRECTION = "same_direction"
    DIFFERENT_DIRECTION = "different_direction"
    RECOMMENDED_PV_STAYS_LOCAL = "recommended_pv_stays_local"
    CANDIDATES_CONCENTRATED = "candidates_concentrated"
    CANDIDATES_DISTRIBUTED = "candidates_distributed"


class DirectionalLimitationId:
    ACTUAL_DIRECTION_UNAVAILABLE = "actual_direction_unavailable"
    RECOMMENDATION_DIRECTION_UNAVAILABLE = (
        "recommendation_direction_unavailable"
    )
    RECOMMENDATION_UNRELIABLE = "recommendation_unreliable"
    REGION_BOUNDARY_NEAR = "region_boundary_near"
    RECOMMENDED_PV_UNAVAILABLE = "recommended_pv_unavailable"
    RECOMMENDED_PV_NOT_LOCAL = "recommended_pv_not_local"
    CANDIDATE_DISTRIBUTION_UNAVAILABLE = (
        "candidate_distribution_unavailable"
    )


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _move(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip().upper()


def _board_size(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 2:
        return value
    return None


def _region(value: Any) -> str | None:
    return value if value in REGION_LABELS_ZH else None


def region_label_zh(region: Any) -> str | None:
    """Return the stable Traditional-Chinese label for a coarse region."""

    return REGION_LABELS_ZH.get(region)


def _recommended_move(record: dict[str, Any]) -> str | None:
    evidence = _mapping(record.get("explanation_evidence"))
    before = _mapping(evidence.get("before"))
    recommended = _mapping(before.get("recommended"))
    return _move(recommended.get("move")) or _move(record.get("best_move"))


def _fact(fact_id: str, **details: Any) -> dict[str, Any]:
    return {"id": fact_id, **details}


def build_directional_evidence(
    record: Any,
    *,
    recommendation_found: bool,
    recommendation_reliable: bool,
    variation_available: bool,
) -> dict[str, Any]:
    """Build a JSON-safe directional description from existing geometry."""

    record = _mapping(record)
    features = _mapping(record.get("explanation_features"))
    size = _board_size(features.get("board_size"))
    actual_move = _move(record.get("actual_move"))
    recommended_move = _recommended_move(record)

    actual_region = region_of(actual_move, size) if size is not None else None
    recommended_region = (
        region_of(recommended_move, size) if size is not None else None
    )
    facts: list[dict[str, Any]] = []
    limitations: list[str] = []

    comparison = {
        "available": False,
        "same_region": None,
        "distance_class": None,
        "direction_difference": None,
    }
    if actual_region is None:
        limitations.append(
            DirectionalLimitationId.ACTUAL_DIRECTION_UNAVAILABLE
        )
    if not recommendation_found or recommended_region is None:
        limitations.append(
            DirectionalLimitationId.RECOMMENDATION_DIRECTION_UNAVAILABLE
        )
    elif not recommendation_reliable:
        limitations.append(DirectionalLimitationId.RECOMMENDATION_UNRELIABLE)
    elif actual_region is not None and size is not None:
        raw_comparison = compare_moves(actual_move, recommended_move, size)
        if raw_comparison.get("usable") is True:
            same_region = raw_comparison.get("same_region") is True
            locality = raw_comparison.get("locality")
            comparison = {
                "available": True,
                "same_region": same_region,
                "distance_class": locality,
                "direction_difference": (
                    "same"
                    if same_region
                    else "different"
                    if locality in {"medium", "far"}
                    else "boundary_near"
                ),
            }
            if same_region:
                facts.append(
                    _fact(
                        DirectionalFactId.SAME_DIRECTION,
                        actual_region=actual_region,
                        recommended_region=recommended_region,
                    )
                )
            elif locality in {"medium", "far"}:
                facts.append(
                    _fact(
                        DirectionalFactId.DIFFERENT_DIRECTION,
                        actual_region=actual_region,
                        recommended_region=recommended_region,
                        distance_class=locality,
                    )
                )
            else:
                limitations.append(
                    DirectionalLimitationId.REGION_BOUNDARY_NEAR
                )

    raw_pv = _mapping(features.get("recommended_pv"))
    pv_usable = (
        variation_available
        and raw_pv.get("usable") is True
        and raw_pv.get("invalid_moves") == 0
        and isinstance(raw_pv.get("total_board_moves"), int)
        and raw_pv.get("total_board_moves") >= 2
    )
    pv_dominant_region = _region(raw_pv.get("dominant_region"))
    pv = {
        "available": pv_usable,
        "stays_local": raw_pv.get("stays_local") if pv_usable else None,
        "dominant_region": pv_dominant_region if pv_usable else None,
        "local_ratio": raw_pv.get("near_ratio") if pv_usable else None,
        "valid_move_count": (
            raw_pv.get("total_board_moves") if pv_usable else 0
        ),
        "pass_move_count": raw_pv.get("pass_moves") if pv_usable else 0,
    }
    if pv_usable and raw_pv.get("stays_local") is True:
        focus_region = pv_dominant_region or recommended_region
        if focus_region is not None:
            facts.append(
                _fact(
                    DirectionalFactId.RECOMMENDED_PV_STAYS_LOCAL,
                    region=focus_region,
                )
            )
    elif pv_usable:
        limitations.append(DirectionalLimitationId.RECOMMENDED_PV_NOT_LOCAL)
    else:
        limitations.append(DirectionalLimitationId.RECOMMENDED_PV_UNAVAILABLE)

    raw_distribution = _mapping(features.get("candidate_distribution"))
    reliable_count = raw_distribution.get("usable_candidate_count")
    distribution_usable = (
        raw_distribution.get("usable") is True
        and isinstance(reliable_count, int)
        and not isinstance(reliable_count, bool)
        and reliable_count >= 2
    )
    dominant_region = _region(raw_distribution.get("dominant_region"))
    concentrated = (
        raw_distribution.get("spatially_concentrated")
        if distribution_usable
        else None
    )
    distribution = {
        "available": distribution_usable,
        "dominant_region": dominant_region if distribution_usable else None,
        "concentration_ratio": (
            raw_distribution.get("dominant_region_ratio")
            if distribution_usable
            else None
        ),
        "reliable_candidate_count": reliable_count if distribution_usable else 0,
        "distinct_region_count": (
            raw_distribution.get("distinct_regions")
            if distribution_usable
            else 0
        ),
        "is_concentrated": concentrated,
    }
    if distribution_usable and concentrated is True and dominant_region:
        facts.append(
            _fact(
                DirectionalFactId.CANDIDATES_CONCENTRATED,
                region=dominant_region,
            )
        )
    elif (
        distribution_usable
        and concentrated is False
        and isinstance(raw_distribution.get("distinct_regions"), int)
        and raw_distribution.get("distinct_regions") >= 2
    ):
        facts.append(_fact(DirectionalFactId.CANDIDATES_DISTRIBUTED))
    else:
        limitations.append(
            DirectionalLimitationId.CANDIDATE_DISTRIBUTION_UNAVAILABLE
        )

    return {
        "schema_version": DIRECTIONAL_EVIDENCE_SCHEMA_VERSION,
        "available": bool(facts),
        "actual": {"move": actual_move, "region": actual_region},
        "recommendation": {
            "move": recommended_move,
            "region": recommended_region,
            "reliable": recommendation_found and recommendation_reliable,
        },
        "relationship": comparison,
        "recommended_pv": pv,
        "candidate_distribution": distribution,
        "facts": facts,
        "limitations": list(dict.fromkeys(limitations)),
    }
