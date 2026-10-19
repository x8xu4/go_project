"""Isolated Phase 3B prototype for objective two-branch comparisons.

This module builds and parses targeted KataGo queries. It is deliberately not
imported by the production analysis pipeline and does not classify Go concepts.
"""

from __future__ import annotations

import math
import statistics
from typing import Any

from explanation_features import compare_moves, region_of


COUNTERFACTUAL_EVIDENCE_SCHEMA_VERSION = 1
RAW_VALUE_PERSPECTIVE = "black"
DEFAULT_MAX_VISITS = 100
DEFAULT_PV_LENGTH = 8


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _opponent(player: str) -> str:
    if player == "B":
        return "W"
    if player == "W":
        return "B"
    raise ValueError(f"invalid player: {player!r}")


def _finite_float(mapping: dict[str, Any], key: str) -> float | None:
    value = mapping.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _nonnegative_int(mapping: dict[str, Any], key: str) -> int | None:
    value = mapping.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    integer = int(value)
    return integer if integer >= 0 else None


def normalize_black_values(
    black_winrate: float,
    black_score_lead: float,
    original_player: str,
) -> dict[str, float]:
    """Normalize fixed BLACK-perspective values to the original mover."""

    if original_player == "B":
        return {
            "mover_winrate": black_winrate,
            "mover_score_lead": black_score_lead,
        }
    if original_player == "W":
        return {
            "mover_winrate": 1.0 - black_winrate,
            "mover_score_lead": -black_score_lead,
        }
    raise ValueError(f"invalid player: {original_player!r}")


def _evaluation(
    source: dict[str, Any],
    original_player: str,
) -> dict[str, Any] | None:
    black_winrate = _finite_float(source, "winrate")
    black_score_lead = _finite_float(source, "scoreLead")
    if (
        black_winrate is None
        or not 0.0 <= black_winrate <= 1.0
        or black_score_lead is None
    ):
        return None
    normalized = normalize_black_values(
        black_winrate,
        black_score_lead,
        original_player,
    )
    return {
        "raw_perspective": RAW_VALUE_PERSPECTIVE,
        "black_winrate": black_winrate,
        "black_score_lead": black_score_lead,
        **normalized,
    }


def _ranked_move_infos(response: dict[str, Any]) -> list[dict[str, Any]]:
    raw_infos = response.get("moveInfos")
    infos = [item for item in raw_infos if isinstance(item, dict)] if isinstance(
        raw_infos, list
    ) else []

    def sort_key(indexed: tuple[int, dict[str, Any]]) -> tuple[bool, int, int]:
        index, info = indexed
        order = _nonnegative_int(info, "order")
        return order is None, order if order is not None else index, index

    return [info for _, info in sorted(enumerate(infos), key=sort_key)]


def build_branch_queries(
    base_moves: list[list[str]],
    *,
    original_player: str,
    recommended_move: str,
    actual_move: str,
    rules: str,
    komi: float,
    board_size: int = 19,
    max_visits: int = DEFAULT_MAX_VISITS,
    analysis_pv_len: int = DEFAULT_PV_LENGTH,
    initial_stones: list[list[str]] | None = None,
    query_id_prefix: str = "counterfactual",
) -> dict[str, dict[str, Any]]:
    """Build two symmetric queries, each positioned after its first move."""

    _opponent(original_player)
    if not isinstance(max_visits, int) or max_visits <= 0:
        raise ValueError("max_visits must be a positive integer")
    if not isinstance(board_size, int) or board_size <= 1:
        raise ValueError("board_size must be at least 2")

    common = {
        "rules": rules,
        "komi": float(komi),
        "boardXSize": board_size,
        "boardYSize": board_size,
        "maxVisits": max_visits,
        "analysisPVLen": analysis_pv_len,
        "includeOwnership": False,
    }
    if initial_stones:
        common["initialStones"] = [list(item) for item in initial_stones]

    queries = {}
    for name, move in (
        ("recommended_branch", recommended_move),
        ("actual_branch", actual_move),
    ):
        query = dict(common)
        query.update(
            {
                "id": f"{query_id_prefix}-{name}",
                "moves": [list(item) for item in base_moves]
                + [[original_player, move.upper()]],
            }
        )
        queries[name] = query
    return queries


def parse_branch_response(
    branch_name: str,
    response: Any,
    *,
    original_player: str,
    first_move: str,
    base_move_count: int,
    requested_visits: int,
) -> dict[str, Any]:
    """Parse one position-after-first-move response into objective evidence."""

    opponent = _opponent(original_player)
    after_first_move_count = base_move_count + 1
    after_reply_move_count = base_move_count + 2
    reasons: list[str] = []
    result = {
        "name": branch_name,
        "first_move": first_move.upper(),
        "first_player": original_player,
        "base_move_count": base_move_count,
        "after_first_move_count": after_first_move_count,
        "after_reply_move_count": after_reply_move_count,
        "requested_visits": requested_visits,
        "side_to_move_after_first": opponent,
        "side_to_move_after_reply": original_player,
        "evaluation_after_first": None,
        "opponent_reply": None,
        "reliability": {
            "usable": False,
            "root_visits_sufficient": False,
            "reply_visits_sufficient": False,
            "turn_number_correct": False,
            "side_to_move_correct": False,
            "reply_location_usable": False,
            "reasons": reasons,
        },
    }
    if not isinstance(response, dict):
        reasons.append("missing_branch_response")
        return result
    if response.get("isDuringSearch") is True:
        reasons.append("non_final_response")
        return result

    turn_number_correct = response.get("turnNumber") == after_first_move_count
    if not turn_number_correct:
        reasons.append("unexpected_turn_number")

    root = response.get("rootInfo")
    root = root if isinstance(root, dict) else {}
    root_evaluation = _evaluation(root, original_player)
    if root_evaluation is None:
        reasons.append("invalid_root_evaluation")
    root_visits = _nonnegative_int(root, "visits")
    root_visits_sufficient = (
        root_visits is not None and root_visits >= requested_visits
    )
    if not root_visits_sufficient:
        reasons.append("insufficient_root_visits")
    side_to_move_correct = root.get("currentPlayer") == opponent
    if not side_to_move_correct:
        reasons.append("unexpected_side_to_move")

    ranked = _ranked_move_infos(response)
    reply = ranked[0] if ranked else None
    reply_payload = None
    reply_visits_sufficient = False
    reply_location_usable = False
    if reply is None:
        reasons.append("missing_opponent_response")
    else:
        reply_move = reply.get("move")
        reply_evaluation = _evaluation(reply, original_player)
        reply_visits = _nonnegative_int(reply, "visits")
        minimum_reply_visits = max(3, int((root_visits or 0) * 0.05))
        reply_visits_sufficient = (
            reply_visits is not None
            and reply_visits >= minimum_reply_visits
        )
        if not reply_visits_sufficient:
            reasons.append("insufficient_reply_visits")
        if reply_evaluation is None:
            reasons.append("invalid_reply_evaluation")
        reply_location_usable = (
            isinstance(reply_move, str) and reply_move.upper() != "PASS"
        )
        if not reply_location_usable:
            reasons.append("reply_location_unavailable")
        raw_pv = reply.get("pv")
        pv = (
            [move.upper() for move in raw_pv[:DEFAULT_PV_LENGTH]
             if isinstance(move, str)]
            if isinstance(raw_pv, list)
            else []
        )
        reply_payload = {
            "player": opponent,
            "move": reply_move.upper() if isinstance(reply_move, str) else None,
            "visits": reply_visits,
            "minimum_reliable_visits": minimum_reply_visits,
            "pv": pv,
            "evaluation_after_reply": reply_evaluation,
        }

    usable = all(
        (
            turn_number_correct,
            root_evaluation is not None,
            root_visits_sufficient,
            side_to_move_correct,
            reply_payload is not None,
            reply_payload is not None
            and reply_payload["evaluation_after_reply"] is not None,
            reply_visits_sufficient,
        )
    )
    result["evaluation_after_first"] = root_evaluation
    if result["evaluation_after_first"] is not None:
        result["evaluation_after_first"]["visits"] = root_visits
    result["opponent_reply"] = reply_payload
    result["reliability"] = {
        "usable": usable,
        "root_visits_sufficient": root_visits_sufficient,
        "reply_visits_sufficient": reply_visits_sufficient,
        "turn_number_correct": turn_number_correct,
        "side_to_move_correct": side_to_move_correct,
        "reply_location_usable": reply_location_usable,
        "reasons": reasons,
    }
    return result


def _signed_gap(
    recommended: dict[str, Any],
    actual: dict[str, Any],
    key: str,
) -> float:
    return float(recommended[key]) - float(actual[key])


def build_counterfactual_evidence(
    *,
    base_move_count: int,
    original_player: str,
    recommended_move: str,
    actual_move: str,
    recommended_branch: Any,
    actual_branch: Any,
    board_size: int = 19,
    requested_visits: int = DEFAULT_MAX_VISITS,
) -> dict[str, Any]:
    """Compare symmetric branches without producing a Go-principle conclusion."""

    recommended_branch = (
        recommended_branch if isinstance(recommended_branch, dict) else {}
    )
    actual_branch = actual_branch if isinstance(actual_branch, dict) else {}
    limitations = ["single_search_stability_not_measured"]
    reliability_reasons: list[str] = []

    recommended_reliability = recommended_branch.get("reliability")
    recommended_reliability = (
        recommended_reliability
        if isinstance(recommended_reliability, dict)
        else {}
    )
    actual_reliability = actual_branch.get("reliability")
    actual_reliability = (
        actual_reliability if isinstance(actual_reliability, dict) else {}
    )
    recommended_usable = recommended_reliability.get("usable") is True
    actual_usable = actual_reliability.get("usable") is True
    if not recommended_usable:
        reliability_reasons.append("recommended_branch_unusable")
    if not actual_usable:
        reliability_reasons.append("actual_branch_unusable")

    equal_depth = (
        recommended_branch.get("after_first_move_count")
        == actual_branch.get("after_first_move_count")
        == base_move_count + 1
        and recommended_branch.get("after_reply_move_count")
        == actual_branch.get("after_reply_move_count")
        == base_move_count + 2
    )
    if not equal_depth:
        reliability_reasons.append("unequal_branch_depth")
    same_side_to_move = (
        recommended_branch.get("side_to_move_after_first")
        == actual_branch.get("side_to_move_after_first")
        == _opponent(original_player)
        and recommended_branch.get("side_to_move_after_reply")
        == actual_branch.get("side_to_move_after_reply")
        == original_player
    )
    if not same_side_to_move:
        reliability_reasons.append("incomparable_side_to_move")
    equal_visit_budget = (
        recommended_branch.get("requested_visits")
        == actual_branch.get("requested_visits")
        == requested_visits
    )
    if not equal_visit_budget:
        reliability_reasons.append("unequal_visit_budget")

    comparable = (
        recommended_usable
        and actual_usable
        and equal_depth
        and same_side_to_move
        and equal_visit_budget
    )
    comparison = {
        "usable": comparable,
        "positive_gap_means": "recommended_branch_better_for_original_player",
        "after_first_move": None,
        "after_opponent_reply": None,
        "gap_change_after_replies": None,
        "actual_reply_vs_recommendation": None,
    }
    if comparable:
        rec_first = recommended_branch["evaluation_after_first"]
        act_first = actual_branch["evaluation_after_first"]
        rec_reply = recommended_branch["opponent_reply"][
            "evaluation_after_reply"
        ]
        act_reply = actual_branch["opponent_reply"]["evaluation_after_reply"]
        first_wr_gap = _signed_gap(rec_first, act_first, "mover_winrate")
        first_score_gap = _signed_gap(
            rec_first, act_first, "mover_score_lead"
        )
        reply_wr_gap = _signed_gap(rec_reply, act_reply, "mover_winrate")
        reply_score_gap = _signed_gap(
            rec_reply, act_reply, "mover_score_lead"
        )
        comparison.update(
            {
                "after_first_move": {
                    "mover_winrate_gap": first_wr_gap,
                    "mover_score_gap": first_score_gap,
                },
                "after_opponent_reply": {
                    "mover_winrate_gap": reply_wr_gap,
                    "mover_score_gap": reply_score_gap,
                },
                "gap_change_after_replies": {
                    "mover_winrate_gap_change": reply_wr_gap - first_wr_gap,
                    "mover_score_gap_change": reply_score_gap - first_score_gap,
                },
            }
        )

        actual_reply = actual_branch["opponent_reply"].get("move")
        comparison["actual_reply_vs_recommendation"] = compare_moves(
            actual_reply,
            recommended_move,
            board_size,
        )

    return {
        "schema_version": COUNTERFACTUAL_EVIDENCE_SCHEMA_VERSION,
        "value_perspective": {
            "raw": RAW_VALUE_PERSPECTIVE,
            "normalized": "original_player",
            "original_player": original_player,
        },
        "base": {
            "move_count": base_move_count,
            "side_to_move": original_player,
            "recommended_move": recommended_move.upper(),
            "actual_move": actual_move.upper(),
            "board_size": board_size,
            "requested_visits_per_branch": requested_visits,
        },
        "recommended_branch": recommended_branch or None,
        "actual_branch": actual_branch or None,
        "comparison": comparison,
        "reliability": {
            "usable": comparable,
            "branch_depth_equal": equal_depth,
            "side_to_move_comparable": same_side_to_move,
            "visit_budget_equal": equal_visit_budget,
            "stability_assessed": False,
            "reasons": reliability_reasons,
        },
        "limitations": limitations,
    }


def _metric_summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {
            "count": 0,
            "mean": None,
            "median": None,
            "minimum": None,
            "maximum": None,
            "range": None,
        }
    return {
        "count": len(values),
        "mean": statistics.mean(values),
        "median": statistics.median(values),
        "minimum": min(values),
        "maximum": max(values),
        "range": max(values) - min(values),
    }


def _nested_number(mapping: dict[str, Any], *keys: str) -> float | None:
    value: Any = mapping
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def aggregate_stability_runs(runs: list[Any]) -> dict[str, Any]:
    """Aggregate repeated counterfactual evidence without classifying it."""

    usable_runs = [
        run
        for run in runs
        if isinstance(run, dict)
        and _mapping(run.get("comparison")).get("usable") is True
    ]
    board_size = 19
    for run in usable_runs:
        size = _mapping(run.get("base")).get("board_size")
        if isinstance(size, int):
            board_size = size
            break

    def reply_stability(branch_key: str) -> dict[str, Any]:
        moves = []
        for run in usable_runs:
            branch = _mapping(run.get(branch_key))
            reply = _mapping(branch.get("opponent_reply"))
            move = reply.get("move")
            moves.append(move.upper() if isinstance(move, str) else None)
        regions = [region_of(move, board_size) for move in moves]
        usable_moves = [move for move in moves if move is not None]
        usable_regions = [region for region in regions if region is not None]
        return {
            "moves": moves,
            "regions": regions,
            "exact_move_stable": (
                len(usable_moves) == len(usable_runs)
                and len(set(usable_moves)) == 1
                if len(usable_runs) >= 2
                else None
            ),
            "region_stable": (
                len(usable_regions) == len(usable_runs)
                and len(set(usable_regions)) == 1
                if len(usable_runs) >= 2
                else None
            ),
        }

    metric_paths = {
        "first_move_winrate_gap": (
            "comparison",
            "after_first_move",
            "mover_winrate_gap",
        ),
        "first_move_score_gap": (
            "comparison",
            "after_first_move",
            "mover_score_gap",
        ),
        "post_reply_winrate_gap": (
            "comparison",
            "after_opponent_reply",
            "mover_winrate_gap",
        ),
        "post_reply_score_gap": (
            "comparison",
            "after_opponent_reply",
            "mover_score_gap",
        ),
        "gap_change_winrate": (
            "comparison",
            "gap_change_after_replies",
            "mover_winrate_gap_change",
        ),
        "gap_change_score": (
            "comparison",
            "gap_change_after_replies",
            "mover_score_gap_change",
        ),
    }
    metrics = {}
    for name, path in metric_paths.items():
        values = []
        for run in usable_runs:
            value = _nested_number(run, *path)
            if value is not None:
                values.append(value)
        metrics[name] = _metric_summary(values)

    return {
        "run_count": len(runs),
        "usable_run_count": len(usable_runs),
        "missing_or_failed_run_count": len(runs) - len(usable_runs),
        "recommended_reply": reply_stability("recommended_branch"),
        "actual_reply": reply_stability("actual_branch"),
        "metrics": metrics,
    }


def calibration_table_row(
    case_result: dict[str, Any],
    stability: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Serialize one flattened, JSON-safe calibration-table row."""

    case = _mapping(case_result.get("case"))
    phase3a = _mapping(case_result.get("phase3a"))
    quality = _mapping(case_result.get("actual_candidate_quality"))
    experiment = _mapping(case_result.get("experiment"))
    evidence = _mapping(case_result.get("counterfactual_evidence"))
    comparison = _mapping(evidence.get("comparison"))
    rec_branch = _mapping(evidence.get("recommended_branch"))
    act_branch = _mapping(evidence.get("actual_branch"))
    rec_reply = _mapping(rec_branch.get("opponent_reply"))
    act_reply = _mapping(act_branch.get("opponent_reply"))
    reply_comparison = _mapping(
        comparison.get("actual_reply_vs_recommendation")
    )
    first = _mapping(comparison.get("after_first_move"))
    post = _mapping(comparison.get("after_opponent_reply"))
    change = _mapping(comparison.get("gap_change_after_replies"))
    return {
        "case_id": case.get("id"),
        "sgf": case.get("sgf"),
        "move_number": case.get("move_number"),
        "expected_case_type": case.get("expected_case_type"),
        "player": phase3a.get("player"),
        "actual": phase3a.get("actual_move"),
        "recommendation": (
            case.get("recommended_move")
            or phase3a.get("recommended_move")
        ),
        "phase3a_category": phase3a.get("category"),
        "phase3a_confidence": phase3a.get("confidence"),
        "actual_order": quality.get("actual_order"),
        "actual_visits": quality.get("actual_visits"),
        "recommended_visits": quality.get("recommended_visits"),
        "actual_visit_share": quality.get("actual_visit_share"),
        "initial_winrate_gap": quality.get("initial_winrate_gap"),
        "initial_score_gap": quality.get("initial_score_gap"),
        "recommended_branch_reply": rec_reply.get("move"),
        "actual_branch_reply": act_reply.get("move"),
        "actual_reply_near_recommendation": (
            reply_comparison.get("same_region") is True
            or reply_comparison.get("locality") == "near"
            if reply_comparison.get("usable") is True
            else None
        ),
        "first_move_gap_winrate": first.get("mover_winrate_gap"),
        "first_move_gap_score": first.get("mover_score_gap"),
        "post_reply_gap_winrate": post.get("mover_winrate_gap"),
        "post_reply_gap_score": post.get("mover_score_gap"),
        "gap_change_winrate": change.get("mover_winrate_gap_change"),
        "gap_change_score": change.get("mover_score_gap_change"),
        "query_count": experiment.get("query_count"),
        "total_runtime_seconds": experiment.get("total_runtime_seconds"),
        "reliable": _mapping(evidence.get("reliability")).get("usable"),
        "stability": stability,
        "notes": case.get("selection_note"),
    }
