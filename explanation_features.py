"""Pure spatial features derived from Phase 1 explanation evidence."""

from __future__ import annotations

from collections import Counter
from math import ceil
from typing import Any

from sgf_utils import gtp_to_board_xy


EXPLANATION_FEATURES_SCHEMA_VERSION = 1
RECENT_PLAY_WINDOW = 6

LOCALITY_NEAR_BOARD_RATIO = 0.15
LOCALITY_FAR_BOARD_RATIO = 0.40

MIN_PV_BOARD_MOVES = 2
PV_STAYS_LOCAL_RATIO = 0.70
MIN_RECENT_BOARD_MOVES = 2
RECENT_DOMINANT_REGION_RATIO = 0.60
MIN_CANDIDATE_DISTRIBUTION_COUNT = 2
CANDIDATE_CONCENTRATION_RATIO = 0.60

REGION_NAMES = (
    "top-left",
    "top",
    "top-right",
    "left",
    "center",
    "right",
    "bottom-left",
    "bottom",
    "bottom-right",
)


def _valid_board_size(board_size: Any) -> bool:
    return (
        isinstance(board_size, int)
        and not isinstance(board_size, bool)
        and board_size >= 2
    )


def _parse_move(move: Any, board_size: int) -> tuple[tuple[int, int] | None, str | None]:
    if not _valid_board_size(board_size):
        return None, "invalid_board_size"
    if not isinstance(move, str) or not move.strip():
        return None, "missing_move"
    if move.upper() == "PASS":
        return None, "pass"
    try:
        coords = gtp_to_board_xy(move, board_size)
    except (TypeError, ValueError):
        return None, "invalid_coordinate"
    if coords is None:
        return None, "pass"
    return coords, None


def _region_for_xy(x: int, y: int, board_size: int) -> str:
    horizontal = min(2, x * 3 // board_size)
    vertical = min(2, y * 3 // board_size)
    return REGION_NAMES[vertical * 3 + horizontal]


def region_of(move: Any, board_size: int) -> str | None:
    """Return a board-size-aware coarse 3x3 region for a GTP move."""

    coords, _ = _parse_move(move, board_size)
    if coords is None:
        return None
    return _region_for_xy(coords[0], coords[1], board_size)


def locality_thresholds(board_size: int) -> dict[str, int] | None:
    if not _valid_board_size(board_size):
        return None
    near_max = max(1, ceil(board_size * LOCALITY_NEAR_BOARD_RATIO))
    far_min = max(near_max + 1, ceil(board_size * LOCALITY_FAR_BOARD_RATIO))
    return {
        "near_max_chebyshev": near_max,
        "far_min_chebyshev": far_min,
    }


def move_distances(
    first: Any, second: Any, board_size: int
) -> dict[str, int] | None:
    first_coords, _ = _parse_move(first, board_size)
    second_coords, _ = _parse_move(second, board_size)
    if first_coords is None or second_coords is None:
        return None
    dx = abs(first_coords[0] - second_coords[0])
    dy = abs(first_coords[1] - second_coords[1])
    return {
        "manhattan": dx + dy,
        "chebyshev": max(dx, dy),
    }


def classify_locality(first: Any, second: Any, board_size: int) -> str | None:
    distances = move_distances(first, second, board_size)
    thresholds = locality_thresholds(board_size)
    if distances is None or thresholds is None:
        return None
    if distances["chebyshev"] <= thresholds["near_max_chebyshev"]:
        return "near"
    if distances["chebyshev"] >= thresholds["far_min_chebyshev"]:
        return "far"
    return "medium"


def compare_moves(first: Any, second: Any, board_size: int) -> dict[str, Any]:
    first_coords, first_error = _parse_move(first, board_size)
    second_coords, second_error = _parse_move(second, board_size)
    if first_coords is None or second_coords is None:
        reason_parts = []
        if first_error is not None:
            reason_parts.append(f"first_{first_error}")
        if second_error is not None:
            reason_parts.append(f"second_{second_error}")
        return {
            "usable": False,
            "unusable_reason": ",".join(reason_parts) or "missing_coordinates",
            "same_region": None,
            "manhattan_distance": None,
            "chebyshev_distance": None,
            "locality": None,
        }

    distances = move_distances(first, second, board_size)
    return {
        "usable": True,
        "unusable_reason": None,
        "same_region": region_of(first, board_size) == region_of(second, board_size),
        "manhattan_distance": distances["manhattan"],
        "chebyshev_distance": distances["chebyshev"],
        "locality": classify_locality(first, second, board_size),
    }


def _region_counts(regions: list[str]) -> dict[str, int]:
    counts = Counter(regions)
    return {region: counts[region] for region in REGION_NAMES if counts[region]}


def _unique_dominant_region(
    counts: dict[str, int],
    total: int,
    *,
    minimum_ratio: float = 0.0,
) -> tuple[str | None, float | None]:
    if total <= 0 or not counts:
        return None, None
    maximum = max(counts.values())
    ratio = maximum / total
    winners = [region for region, count in counts.items() if count == maximum]
    if len(winners) != 1 or ratio < minimum_ratio:
        return None, ratio
    return winners[0], ratio


def _empty_pv_locality(reason: str, anchor: Any, raw_pv: Any) -> dict[str, Any]:
    return {
        "usable": False,
        "unusable_reason": reason,
        "anchor": anchor.upper() if isinstance(anchor, str) else None,
        "anchor_region": None,
        "total_pv_moves": len(raw_pv) if isinstance(raw_pv, list) else 0,
        "total_board_moves": 0,
        "pass_moves": 0,
        "invalid_moves": 0,
        "moves_near_anchor": None,
        "near_ratio": None,
        "dominant_region": None,
        "region_counts": {},
        "stays_local": None,
    }


def pv_locality(
    pv: Any,
    anchor: Any,
    board_size: int,
    *,
    candidate_found: bool = True,
    candidate_reliable: bool = True,
) -> dict[str, Any]:
    """Describe whether a reliable PV remains spatially near its first move."""

    if not candidate_found:
        return _empty_pv_locality("candidate_missing", anchor, pv)
    if not candidate_reliable:
        return _empty_pv_locality("candidate_unreliable", anchor, pv)
    anchor_coords, anchor_error = _parse_move(anchor, board_size)
    if anchor_coords is None:
        return _empty_pv_locality(f"anchor_{anchor_error}", anchor, pv)
    if not isinstance(pv, list) or not pv:
        return _empty_pv_locality("pv_missing", anchor, pv)

    board_moves: list[str] = []
    regions: list[str] = []
    pass_moves = 0
    invalid_moves = 0
    for move in pv:
        coords, error = _parse_move(move, board_size)
        if coords is None:
            if error == "pass":
                pass_moves += 1
            else:
                invalid_moves += 1
            continue
        board_moves.append(move)
        regions.append(_region_for_xy(coords[0], coords[1], board_size))

    if len(board_moves) < MIN_PV_BOARD_MOVES:
        result = _empty_pv_locality("pv_too_short", anchor, pv)
        result.update(
            {
                "anchor_region": region_of(anchor, board_size),
                "total_board_moves": len(board_moves),
                "pass_moves": pass_moves,
                "invalid_moves": invalid_moves,
                "region_counts": _region_counts(regions),
            }
        )
        return result

    moves_near_anchor = sum(
        1
        for move in board_moves
        if classify_locality(anchor, move, board_size) == "near"
    )
    near_ratio = moves_near_anchor / len(board_moves)
    counts = _region_counts(regions)
    dominant_region, _ = _unique_dominant_region(counts, len(board_moves))
    return {
        "usable": True,
        "unusable_reason": None,
        "anchor": anchor.upper(),
        "anchor_region": region_of(anchor, board_size),
        "total_pv_moves": len(pv),
        "total_board_moves": len(board_moves),
        "pass_moves": pass_moves,
        "invalid_moves": invalid_moves,
        "moves_near_anchor": moves_near_anchor,
        "near_ratio": near_ratio,
        "dominant_region": dominant_region,
        "region_counts": counts,
        "stays_local": near_ratio >= PV_STAYS_LOCAL_RATIO,
    }


def _candidate_pv_locality(candidate: Any, board_size: int) -> dict[str, Any]:
    if not isinstance(candidate, dict):
        return _empty_pv_locality("candidate_missing", None, None)
    return pv_locality(
        candidate.get("pv"),
        candidate.get("move"),
        board_size,
        candidate_found=candidate.get("found") is True,
        candidate_reliable=candidate.get("reliable") is True,
    )


def opponent_reply_features(
    reply: Any,
    recommended_move: Any,
    actual_move: Any,
    board_size: int,
) -> dict[str, Any]:
    base = {
        "usable": False,
        "unusable_reason": "candidate_missing",
        "move": reply.get("move") if isinstance(reply, dict) else None,
        "region": None,
        "vs_recommended": compare_moves(None, recommended_move, board_size),
        "vs_actual": compare_moves(None, actual_move, board_size),
        "near_original_recommendation": None,
        "near_actual_move": None,
    }
    if not isinstance(reply, dict) or reply.get("found") is not True:
        return base
    if reply.get("reliable") is not True:
        base["unusable_reason"] = "candidate_unreliable"
        return base
    move = reply.get("move")
    _, move_error = _parse_move(move, board_size)
    if move_error is not None:
        base["unusable_reason"] = f"reply_{move_error}"
        return base

    vs_recommended = compare_moves(move, recommended_move, board_size)
    vs_actual = compare_moves(move, actual_move, board_size)

    def near_area(comparison: dict[str, Any]) -> bool | None:
        if not comparison["usable"]:
            return None
        return comparison["same_region"] or comparison["locality"] == "near"

    return {
        "usable": True,
        "unusable_reason": None,
        "move": move.upper(),
        "region": region_of(move, board_size),
        "vs_recommended": vs_recommended,
        "vs_actual": vs_actual,
        "near_original_recommendation": near_area(vs_recommended),
        "near_actual_move": near_area(vs_actual),
    }


def _move_from_history_item(item: Any) -> Any:
    if isinstance(item, (list, tuple)) and len(item) >= 2:
        return item[1]
    return None


def _move_near_recent_region(
    move: Any,
    recent_moves: list[str],
    dominant_region: str | None,
    board_size: int,
) -> bool | None:
    if dominant_region is None or region_of(move, board_size) is None:
        return None
    if region_of(move, board_size) == dominant_region:
        return True
    dominant_moves = [
        recent
        for recent in recent_moves
        if region_of(recent, board_size) == dominant_region
    ]
    return any(
        classify_locality(move, recent, board_size) == "near"
        for recent in dominant_moves
    )


def recent_play_features(
    all_moves: list[list[str]],
    move_number: int,
    actual_move: Any,
    recommended_move: Any,
    board_size: int,
    *,
    window_size: int = RECENT_PLAY_WINDOW,
) -> dict[str, Any]:
    current_index = max(0, move_number - 1)
    bounded_window = max(1, window_size)
    recent_items = all_moves[max(0, current_index - bounded_window):current_index]
    board_moves: list[str] = []
    regions: list[str] = []
    pass_moves = 0
    invalid_moves = 0
    for item in recent_items:
        move = _move_from_history_item(item)
        coords, error = _parse_move(move, board_size)
        if coords is None:
            if error == "pass":
                pass_moves += 1
            else:
                invalid_moves += 1
            continue
        board_moves.append(move)
        regions.append(_region_for_xy(coords[0], coords[1], board_size))

    counts = _region_counts(regions)
    if len(board_moves) < MIN_RECENT_BOARD_MOVES:
        return {
            "usable": False,
            "unusable_reason": "insufficient_recent_moves",
            "window_size": bounded_window,
            "considered_moves": len(recent_items),
            "usable_moves": len(board_moves),
            "pass_moves": pass_moves,
            "invalid_moves": invalid_moves,
            "dominant_region": None,
            "region_counts": counts,
            "concentration_ratio": None,
            "actual_stays_near_recent_play": None,
            "recommended_stays_near_recent_play": None,
        }

    dominant_region, ratio = _unique_dominant_region(
        counts,
        len(board_moves),
        minimum_ratio=RECENT_DOMINANT_REGION_RATIO,
    )
    return {
        "usable": True,
        "unusable_reason": None,
        "window_size": bounded_window,
        "considered_moves": len(recent_items),
        "usable_moves": len(board_moves),
        "pass_moves": pass_moves,
        "invalid_moves": invalid_moves,
        "dominant_region": dominant_region,
        "region_counts": counts,
        "concentration_ratio": ratio,
        "actual_stays_near_recent_play": _move_near_recent_region(
            actual_move, board_moves, dominant_region, board_size
        ),
        "recommended_stays_near_recent_play": _move_near_recent_region(
            recommended_move, board_moves, dominant_region, board_size
        ),
    }


def candidate_distribution(candidates: Any, board_size: int) -> dict[str, Any]:
    raw_candidates = candidates if isinstance(candidates, list) else []
    regions: list[str] = []
    ignored_unreliable = 0
    pass_candidates = 0
    invalid_candidates = 0
    for candidate in raw_candidates:
        if not isinstance(candidate, dict) or candidate.get("reliable") is not True:
            ignored_unreliable += 1
            continue
        move = candidate.get("move")
        coords, error = _parse_move(move, board_size)
        if coords is None:
            if error == "pass":
                pass_candidates += 1
            else:
                invalid_candidates += 1
            continue
        regions.append(_region_for_xy(coords[0], coords[1], board_size))

    counts = _region_counts(regions)
    usable_count = len(regions)
    if usable_count < MIN_CANDIDATE_DISTRIBUTION_COUNT:
        return {
            "usable": False,
            "unusable_reason": "insufficient_reliable_candidates",
            "usable_candidate_count": usable_count,
            "ignored_unreliable_candidates": ignored_unreliable,
            "pass_candidates": pass_candidates,
            "invalid_candidates": invalid_candidates,
            "distinct_regions": len(counts),
            "dominant_region": None,
            "dominant_region_ratio": None,
            "region_counts": counts,
            "spatially_concentrated": None,
        }

    dominant_region, ratio = _unique_dominant_region(
        counts,
        usable_count,
        minimum_ratio=CANDIDATE_CONCENTRATION_RATIO,
    )
    return {
        "usable": True,
        "unusable_reason": None,
        "usable_candidate_count": usable_count,
        "ignored_unreliable_candidates": ignored_unreliable,
        "pass_candidates": pass_candidates,
        "invalid_candidates": invalid_candidates,
        "distinct_regions": len(counts),
        "dominant_region": dominant_region,
        "dominant_region_ratio": ratio,
        "region_counts": counts,
        "spatially_concentrated": dominant_region is not None,
    }


def build_explanation_features(
    explanation_evidence: dict[str, Any],
    all_moves: list[list[str]],
    move_number: int,
    *,
    board_size: int = 19,
) -> dict[str, Any]:
    """Build deterministic geometry only; never classify or explain a move."""

    before = explanation_evidence.get("before", {})
    after = explanation_evidence.get("after", {})
    recommended = before.get("recommended", {})
    actual = before.get("actual", {})
    reply = after.get("opponent_best_response", {})
    recommended_move = recommended.get("move") if isinstance(recommended, dict) else None
    actual_move = actual.get("move") if isinstance(actual, dict) else None
    thresholds = locality_thresholds(board_size)

    return {
        "schema_version": EXPLANATION_FEATURES_SCHEMA_VERSION,
        "board_size": board_size,
        "locality_thresholds": thresholds,
        "actual_region": region_of(actual_move, board_size),
        "recommended_region": region_of(recommended_move, board_size),
        "actual_recommended": compare_moves(
            actual_move, recommended_move, board_size
        ),
        "recommended_pv": _candidate_pv_locality(recommended, board_size),
        "actual_pv": _candidate_pv_locality(actual, board_size),
        "opponent_reply": opponent_reply_features(
            reply, recommended_move, actual_move, board_size
        ),
        "recent_play": recent_play_features(
            all_moves,
            move_number,
            actual_move,
            recommended_move,
            board_size,
        ),
        "candidate_distribution": candidate_distribution(
            before.get("candidates"), board_size
        ),
    }
