"""Conservative deterministic classification over explanation evidence/features."""

from __future__ import annotations

from typing import Any


EXPLANATION_CLASSIFICATION_SCHEMA_VERSION = 1
SUPPORTED_EVIDENCE_SCHEMA_VERSION = 1
SUPPORTED_FEATURES_SCHEMA_VERSION = 1


class ReasonId:
    """Stable machine-readable reason identifiers emitted by the classifier."""

    ACTUAL_CANDIDATE_MISSING = "actual_candidate_missing"
    ACTUAL_CANDIDATE_UNRELIABLE = "actual_candidate_unreliable"
    RECOMMENDED_CANDIDATE_MISSING = "recommended_candidate_missing"
    RECOMMENDED_CANDIDATE_UNRELIABLE = "recommended_candidate_unreliable"
    SPATIAL_COMPARISON_UNUSABLE = "spatial_comparison_unusable"
    SPATIAL_COMPARISON_INVALID = "spatial_comparison_invalid"
    EVIDENCE_SCHEMA_UNSUPPORTED = "evidence_schema_unsupported"
    FEATURES_SCHEMA_UNSUPPORTED = "features_schema_unsupported"

    MOVES_IN_SAME_REGION = "moves_in_same_region"
    MOVES_SPATIALLY_NEAR = "moves_spatially_near"
    MOVES_SPATIALLY_FAR = "moves_spatially_far"
    RECOMMENDED_PV_LOCAL = "recommended_pv_local"
    ACTUAL_PV_LOCAL = "actual_pv_local"
    RECOMMENDED_PV_NONLOCAL = "recommended_pv_nonlocal"
    ACTUAL_PV_NONLOCAL = "actual_pv_nonlocal"
    RECOMMENDED_PV_UNUSABLE = "recommended_pv_unusable"
    ACTUAL_PV_UNUSABLE = "actual_pv_unusable"
    PVS_LOCAL_AT_SEPARATE_ANCHORS = "pvs_local_at_separate_anchors"

    OPPONENT_REPLY_NEAR_RECOMMENDATION = (
        "opponent_reply_near_recommendation"
    )
    OPPONENT_REPLY_NEAR_BOTH_MOVES = "opponent_reply_near_both_moves"
    OPPONENT_REPLY_POINTS_ELSEWHERE = "opponent_reply_points_elsewhere"
    BOTH_MOVES_NEAR_RECENT_PLAY = "both_moves_near_recent_play"
    RECOMMENDED_MATCHES_RECENT_PLAY = "recommended_matches_recent_play"
    RECENT_PLAY_POINTS_ELSEWHERE = "recent_play_points_elsewhere"
    CANDIDATES_CONCENTRATED_IN_SHARED_REGION = (
        "candidates_concentrated_in_shared_region"
    )
    CANDIDATES_CONCENTRATED_NEAR_RECOMMENDATION = (
        "candidates_concentrated_near_recommendation"
    )

    STRONG_LOCALITY_CONFLICT = "strong_locality_conflict"
    CONFLICTING_CLASSIFICATION_EVIDENCE = (
        "conflicting_classification_evidence"
    )
    INSUFFICIENT_INDEPENDENT_EVIDENCE = (
        "insufficient_independent_evidence"
    )

    GEOMETRY_ONLY_CLASSIFICATION = "geometry_only_classification"
    PARTIAL_PV_SUPPORT = "partial_pv_support"
    CONTEXT_FEATURES_ARE_SUPPORT_ONLY = "context_features_are_support_only"
    UNSUPPORTED_SCHEMA_VERSION = "unsupported_schema_version"
    CLASSIFICATION_ABSTAINED = "classification_abstained"


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _add(items: list[str], reason: str) -> None:
    if reason not in items:
        items.append(reason)


def _result(
    category: str,
    confidence: str,
    *,
    supporting: list[str],
    contradictions: list[str],
    missing: list[str],
    limitations: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": EXPLANATION_CLASSIFICATION_SCHEMA_VERSION,
        "category": category,
        "confidence": confidence,
        "abstained": category == "uncertain",
        "supporting_evidence": supporting,
        "contradictions": contradictions,
        "missing_evidence": missing,
        "limitations": limitations,
    }


def _uncertain(
    *,
    supporting: list[str],
    contradictions: list[str],
    missing: list[str],
    limitations: list[str],
) -> dict[str, Any]:
    _add(limitations, ReasonId.CLASSIFICATION_ABSTAINED)
    return _result(
        "uncertain",
        "low",
        supporting=supporting,
        contradictions=contradictions,
        missing=missing,
        limitations=limitations,
    )


def _candidate_gate(
    candidate: dict[str, Any],
    *,
    missing_id: str,
    unreliable_id: str,
    missing: list[str],
) -> None:
    if candidate.get("found") is not True:
        _add(missing, missing_id)
    elif candidate.get("reliable") is not True:
        _add(missing, unreliable_id)


def _pv_state(
    feature: dict[str, Any],
    *,
    local_id: str,
    nonlocal_id: str,
    unusable_id: str,
    supporting: list[str],
    contradictions: list[str],
    missing: list[str],
) -> str:
    if feature.get("usable") is not True:
        _add(missing, unusable_id)
        return "unusable"
    if feature.get("stays_local") is True:
        _add(supporting, local_id)
        return "local"
    if feature.get("stays_local") is False:
        _add(contradictions, nonlocal_id)
        return "nonlocal"
    _add(missing, unusable_id)
    return "unusable"


def _context_reasons(
    features: dict[str, Any],
    *,
    local_signal: bool,
    global_signal: bool,
    supporting: list[str],
    soft_contradictions: list[str],
) -> None:
    recent = _mapping(features.get("recent_play"))
    if recent.get("usable") is True:
        actual_stays = recent.get("actual_stays_near_recent_play")
        recommended_stays = recent.get("recommended_stays_near_recent_play")
        if actual_stays is True and recommended_stays is True and local_signal:
            _add(supporting, ReasonId.BOTH_MOVES_NEAR_RECENT_PLAY)
        elif actual_stays is False and recommended_stays is True and global_signal:
            _add(supporting, ReasonId.RECOMMENDED_MATCHES_RECENT_PLAY)
        elif actual_stays is False and recommended_stays is False:
            _add(soft_contradictions, ReasonId.RECENT_PLAY_POINTS_ELSEWHERE)

    reply = _mapping(features.get("opponent_reply"))
    if reply.get("usable") is True:
        near_recommended = reply.get("near_original_recommendation")
        near_actual = reply.get("near_actual_move")
        if near_recommended is True and near_actual is True and local_signal:
            _add(supporting, ReasonId.OPPONENT_REPLY_NEAR_BOTH_MOVES)
        elif near_recommended is True and near_actual is False and global_signal:
            _add(supporting, ReasonId.OPPONENT_REPLY_NEAR_RECOMMENDATION)
        elif near_recommended is False and near_actual is False:
            _add(soft_contradictions, ReasonId.OPPONENT_REPLY_POINTS_ELSEWHERE)

    distribution = _mapping(features.get("candidate_distribution"))
    if (
        distribution.get("usable") is True
        and distribution.get("spatially_concentrated") is True
    ):
        dominant = distribution.get("dominant_region")
        actual_region = features.get("actual_region")
        recommended_region = features.get("recommended_region")
        if (
            local_signal
            and dominant is not None
            and dominant == actual_region == recommended_region
        ):
            _add(
                supporting,
                ReasonId.CANDIDATES_CONCENTRATED_IN_SHARED_REGION,
            )
        elif (
            global_signal
            and dominant is not None
            and dominant == recommended_region
            and dominant != actual_region
        ):
            _add(
                supporting,
                ReasonId.CANDIDATES_CONCENTRATED_NEAR_RECOMMENDATION,
            )


def classify_explanation(
    explanation_evidence: Any,
    explanation_features: Any,
) -> dict[str, Any]:
    """Classify only well-supported local-vs-global spatial relationships."""

    supporting: list[str] = []
    contradictions: list[str] = []
    missing: list[str] = []
    limitations = [
        ReasonId.GEOMETRY_ONLY_CLASSIFICATION,
        ReasonId.CONTEXT_FEATURES_ARE_SUPPORT_ONLY,
    ]

    evidence = _mapping(explanation_evidence)
    features = _mapping(explanation_features)
    if evidence.get("schema_version") != SUPPORTED_EVIDENCE_SCHEMA_VERSION:
        _add(missing, ReasonId.EVIDENCE_SCHEMA_UNSUPPORTED)
    if features.get("schema_version") != SUPPORTED_FEATURES_SCHEMA_VERSION:
        _add(missing, ReasonId.FEATURES_SCHEMA_UNSUPPORTED)
    if missing:
        _add(limitations, ReasonId.UNSUPPORTED_SCHEMA_VERSION)
        return _uncertain(
            supporting=supporting,
            contradictions=contradictions,
            missing=missing,
            limitations=limitations,
        )

    before = _mapping(evidence.get("before"))
    actual = _mapping(before.get("actual"))
    recommended = _mapping(before.get("recommended"))
    _candidate_gate(
        actual,
        missing_id=ReasonId.ACTUAL_CANDIDATE_MISSING,
        unreliable_id=ReasonId.ACTUAL_CANDIDATE_UNRELIABLE,
        missing=missing,
    )
    _candidate_gate(
        recommended,
        missing_id=ReasonId.RECOMMENDED_CANDIDATE_MISSING,
        unreliable_id=ReasonId.RECOMMENDED_CANDIDATE_UNRELIABLE,
        missing=missing,
    )

    comparison = _mapping(features.get("actual_recommended"))
    if comparison.get("usable") is not True:
        _add(missing, ReasonId.SPATIAL_COMPARISON_UNUSABLE)
    if missing:
        return _uncertain(
            supporting=supporting,
            contradictions=contradictions,
            missing=missing,
            limitations=limitations,
        )

    same_region = comparison.get("same_region")
    locality = comparison.get("locality")
    if not isinstance(same_region, bool) or locality not in {
        "near",
        "medium",
        "far",
    }:
        _add(missing, ReasonId.SPATIAL_COMPARISON_INVALID)
        return _uncertain(
            supporting=supporting,
            contradictions=contradictions,
            missing=missing,
            limitations=limitations,
        )

    local_signal = same_region or locality == "near"
    global_signal = locality == "far"
    if same_region:
        _add(supporting, ReasonId.MOVES_IN_SAME_REGION)
    if locality == "near":
        _add(supporting, ReasonId.MOVES_SPATIALLY_NEAR)
    elif locality == "far":
        _add(supporting, ReasonId.MOVES_SPATIALLY_FAR)

    recommended_pv = _mapping(features.get("recommended_pv"))
    actual_pv = _mapping(features.get("actual_pv"))
    recommended_pv_state = _pv_state(
        recommended_pv,
        local_id=ReasonId.RECOMMENDED_PV_LOCAL,
        nonlocal_id=ReasonId.RECOMMENDED_PV_NONLOCAL,
        unusable_id=ReasonId.RECOMMENDED_PV_UNUSABLE,
        supporting=supporting,
        contradictions=contradictions,
        missing=missing,
    )
    actual_pv_state = _pv_state(
        actual_pv,
        local_id=ReasonId.ACTUAL_PV_LOCAL,
        nonlocal_id=ReasonId.ACTUAL_PV_NONLOCAL,
        unusable_id=ReasonId.ACTUAL_PV_UNUSABLE,
        supporting=supporting,
        contradictions=contradictions,
        missing=missing,
    )

    soft_contradictions: list[str] = []
    _context_reasons(
        features,
        local_signal=local_signal,
        global_signal=global_signal,
        supporting=supporting,
        soft_contradictions=soft_contradictions,
    )

    if local_signal and global_signal:
        _add(contradictions, ReasonId.STRONG_LOCALITY_CONFLICT)
        _add(contradictions, ReasonId.CONFLICTING_CLASSIFICATION_EVIDENCE)
        return _uncertain(
            supporting=supporting,
            contradictions=contradictions,
            missing=missing,
            limitations=limitations,
        )

    local_pv_count = sum(
        state == "local"
        for state in (recommended_pv_state, actual_pv_state)
    )
    has_nonlocal_pv = "nonlocal" in {
        recommended_pv_state,
        actual_pv_state,
    }
    if has_nonlocal_pv:
        _add(contradictions, ReasonId.STRONG_LOCALITY_CONFLICT)
        return _uncertain(
            supporting=supporting,
            contradictions=contradictions,
            missing=missing,
            limitations=limitations,
        )
    if local_pv_count == 0:
        _add(missing, ReasonId.INSUFFICIENT_INDEPENDENT_EVIDENCE)
        return _uncertain(
            supporting=supporting,
            contradictions=contradictions,
            missing=missing,
            limitations=limitations,
        )

    contradictions.extend(
        item for item in soft_contradictions if item not in contradictions
    )
    if local_signal:
        confidence = (
            "high"
            if local_pv_count == 2 and not soft_contradictions
            else "medium"
        )
        if local_pv_count < 2:
            _add(limitations, ReasonId.PARTIAL_PV_SUPPORT)
        return _result(
            "local_sequence",
            confidence,
            supporting=supporting,
            contradictions=contradictions,
            missing=missing,
            limitations=limitations,
        )

    if global_signal:
        separate_anchors = (
            recommended_pv.get("anchor_region") is not None
            and actual_pv.get("anchor_region") is not None
            and recommended_pv.get("anchor_region")
            != actual_pv.get("anchor_region")
        )
        if local_pv_count == 2 and separate_anchors and not soft_contradictions:
            _add(supporting, ReasonId.PVS_LOCAL_AT_SEPARATE_ANCHORS)
            confidence = "high"
        else:
            confidence = "medium"
            if local_pv_count < 2:
                _add(limitations, ReasonId.PARTIAL_PV_SUPPORT)
        return _result(
            "global_direction",
            confidence,
            supporting=supporting,
            contradictions=contradictions,
            missing=missing,
            limitations=limitations,
        )

    _add(missing, ReasonId.INSUFFICIENT_INDEPENDENT_EVIDENCE)
    return _uncertain(
        supporting=supporting,
        contradictions=contradictions,
        missing=missing,
        limitations=limitations,
    )
