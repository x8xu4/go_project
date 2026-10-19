"""Pure helpers for turning KataGo position results into move-level facts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from explanation_classifier import classify_explanation
from explanation_features import build_explanation_features
from structured_explanation import build_structured_explanation


GTP_COLUMNS = "ABCDEFGHJKLMNOPQRST"
EXPLANATION_EVIDENCE_SCHEMA_VERSION = 1
EXPLANATION_EVIDENCE_TOP_K = 8
EXPLANATION_EVIDENCE_PV_MAX_MOVES = 8
KATAGO_VALUE_PERSPECTIVE = "black"


@dataclass(frozen=True)
class ImportanceThresholds:
    """Centralised thresholds calibrated from representative project SGFs."""

    notice_winrate_loss: float = 0.050
    important_winrate_loss: float = 0.120
    decisive_winrate_loss: float = 0.220
    notice_score_loss: float = 3.0
    important_score_loss: float = 7.0
    decisive_score_loss: float = 12.0


IMPORTANCE_THRESHOLDS = ImportanceThresholds()


def _as_float(mapping: dict[str, Any], key: str) -> float:
    value = mapping.get(key)
    if not isinstance(value, (int, float)):
        raise ValueError(f"KataGo rootInfo 缺少有效 {key}")
    return float(value)


def _mover_value(black_value: float, player: str, *, probability: bool) -> float:
    if player == "B":
        return black_value
    return 1.0 - black_value if probability else -black_value


def classify_importance(
    winrate_loss: float,
    score_loss: float,
    *,
    thresholds: ImportanceThresholds = IMPORTANCE_THRESHOLDS,
) -> str:
    """Classify the impact on the player who made the move."""

    if (
        winrate_loss >= thresholds.decisive_winrate_loss
        or score_loss >= thresholds.decisive_score_loss
    ):
        return "decisive"
    if (
        winrate_loss >= thresholds.important_winrate_loss
        or score_loss >= thresholds.important_score_loss
    ):
        return "important"
    if (
        winrate_loss >= thresholds.notice_winrate_loss
        or score_loss >= thresholds.notice_score_loss
    ):
        return "notice"
    return "ordinary"


def _find_actual_move_info(
    move_infos: list[dict[str, Any]], actual_move: str
) -> dict[str, Any] | None:
    target = actual_move.upper()
    for info in move_infos:
        move = info.get("move")
        if isinstance(move, str) and move.upper() == target:
            return info
    return None


def _is_valid_gtp_move(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    move = value.upper()
    if move == "PASS":
        return True
    if len(move) < 2 or move[0] not in GTP_COLUMNS:
        return False
    try:
        row = int(move[1:])
    except ValueError:
        return False
    return 1 <= row <= 19


def _optional_float(mapping: dict[str, Any], key: str) -> float | None:
    value = mapping.get(key)
    return (
        float(value)
        if isinstance(value, (int, float)) and not isinstance(value, bool)
        else None
    )


def _optional_int(mapping: dict[str, Any], key: str) -> int | None:
    value = mapping.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    integer = int(value)
    return integer if integer >= 0 else None


def _bounded_pv(candidate: dict[str, Any]) -> list[str]:
    raw_pv = candidate.get("pv")
    if not isinstance(raw_pv, list):
        return []
    return [
        move.upper()
        for move in raw_pv[:EXPLANATION_EVIDENCE_PV_MAX_MOVES]
        if isinstance(move, str) and _is_valid_gtp_move(move)
    ]


def _minimum_reliable_visits(root_visits: int) -> int:
    """Return the shared minimum search evidence for one candidate."""

    return max(3, int(max(0, root_visits) * 0.05))


def _candidate_reliability(
    candidate: dict[str, Any] | None, root_visits: int
) -> tuple[bool, str]:
    if candidate is None:
        return False, "missing_candidate"
    visits = _optional_int(candidate, "visits")
    if visits is None or visits < _minimum_reliable_visits(root_visits):
        return False, "insufficient_visits"
    return True, "sufficient_visits"


def _candidate_evidence(
    candidate: dict[str, Any] | None,
    root_visits: int,
    *,
    missing_move: str | None = None,
) -> dict[str, Any]:
    reliable, reason = _candidate_reliability(candidate, root_visits)
    if candidate is None:
        return {
            "found": False,
            "move": missing_move.upper() if isinstance(missing_move, str) else None,
            "order": None,
            "visits": None,
            "prior": None,
            "winrate_black": None,
            "score_lead_black": None,
            "pv": [],
            "reliable": reliable,
            "reliability_reason": reason,
        }

    move = candidate.get("move")
    return {
        "found": True,
        "move": move.upper() if isinstance(move, str) else None,
        "order": _optional_int(candidate, "order"),
        "visits": _optional_int(candidate, "visits"),
        "prior": _optional_float(candidate, "prior"),
        "winrate_black": _optional_float(candidate, "winrate"),
        "score_lead_black": _optional_float(candidate, "scoreLead"),
        "pv": _bounded_pv(candidate),
        "reliable": reliable,
        "reliability_reason": reason,
    }


def _valid_move_infos(position: dict[str, Any]) -> list[dict[str, Any]]:
    raw_move_infos = position.get("moveInfos")
    if not isinstance(raw_move_infos, list):
        return []
    return [
        item
        for item in raw_move_infos
        if isinstance(item, dict) and _is_valid_gtp_move(item.get("move"))
    ]


def _candidate_sort_key(
    indexed_candidate: tuple[int, dict[str, Any]],
) -> tuple[bool, int, int]:
    index, candidate = indexed_candidate
    order = _optional_int(candidate, "order")
    return order is None, order if order is not None else index, index


def _ranked_candidates(move_infos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Use KataGo's explicit order, with response order only as a safe fallback."""

    return [
        candidate
        for _, candidate in sorted(enumerate(move_infos), key=_candidate_sort_key)
    ]


def _recommended_candidate(
    move_infos: list[dict[str, Any]],
) -> dict[str, Any] | None:
    ranked = _ranked_candidates(move_infos)
    return ranked[0] if ranked else None


def _root_visits(root_info: dict[str, Any]) -> int:
    return _optional_int(root_info, "visits") or 0


def _build_explanation_evidence(
    before: dict[str, Any],
    after: dict[str, Any],
    before_root: dict[str, Any],
    after_root: dict[str, Any],
    actual_move: str,
) -> dict[str, Any]:
    before_root_visits = _root_visits(before_root)
    after_root_visits = _root_visits(after_root)
    before_candidates = _valid_move_infos(before)
    after_candidates = _valid_move_infos(after)
    ranked_before = _ranked_candidates(before_candidates)
    recommended = ranked_before[0] if ranked_before else None
    actual = _find_actual_move_info(before_candidates, actual_move)
    opponent_best_response = _recommended_candidate(after_candidates)

    return {
        "schema_version": EXPLANATION_EVIDENCE_SCHEMA_VERSION,
        "value_perspective": KATAGO_VALUE_PERSPECTIVE,
        "before": {
            "root_visits": before_root_visits,
            "minimum_reliable_visits": _minimum_reliable_visits(
                before_root_visits
            ),
            "recommended": _candidate_evidence(
                recommended, before_root_visits
            ),
            "actual": _candidate_evidence(
                actual, before_root_visits, missing_move=actual_move
            ),
            "candidates": [
                _candidate_evidence(candidate, before_root_visits)
                for candidate in ranked_before[:EXPLANATION_EVIDENCE_TOP_K]
            ],
        },
        "after": {
            "root_visits": after_root_visits,
            "minimum_reliable_visits": _minimum_reliable_visits(
                after_root_visits
            ),
            "opponent_best_response": _candidate_evidence(
                opponent_best_response, after_root_visits
            ),
        },
    }


def build_move_analyses(
    all_moves: list[list[str]],
    position_results: dict[int, dict[str, Any]],
    *,
    thresholds: ImportanceThresholds = IMPORTANCE_THRESHOLDS,
    board_size: int = 19,
) -> list[dict[str, Any]]:
    """Build one factual record per played move from before/after analyses."""

    expected_turns = set(range(len(all_moves) + 1))
    missing = sorted(expected_turns.difference(position_results))
    if missing:
        raise ValueError(f"KataGo 分析結果缺少手數: {missing[:8]}")

    records: list[dict[str, Any]] = []
    for move_number, (player, actual_move) in enumerate(all_moves, start=1):
        before = position_results[move_number - 1]
        after = position_results[move_number]
        before_root = before.get("rootInfo")
        after_root = after.get("rootInfo")
        if not isinstance(before_root, dict) or not isinstance(after_root, dict):
            raise ValueError(f"第 {move_number} 手缺少 rootInfo")

        black_wr_before = _as_float(before_root, "winrate")
        black_wr_after = _as_float(after_root, "winrate")
        black_score_before = _as_float(before_root, "scoreLead")
        black_score_after = _as_float(after_root, "scoreLead")

        mover_wr_before = _mover_value(
            black_wr_before, player, probability=True
        )
        mover_wr_after = _mover_value(black_wr_after, player, probability=True)
        mover_score_before = _mover_value(
            black_score_before, player, probability=False
        )
        mover_score_after = _mover_value(
            black_score_after, player, probability=False
        )

        observed_wr_loss = max(0.0, mover_wr_before - mover_wr_after)
        observed_score_loss = max(0.0, mover_score_before - mover_score_after)

        raw_move_infos = before.get("moveInfos")
        move_infos = (
            [item for item in raw_move_infos if isinstance(item, dict)]
            if isinstance(raw_move_infos, list)
            else []
        )
        best_info = move_infos[0] if move_infos else {}
        actual_info = _find_actual_move_info(move_infos, actual_move)
        best_move = best_info.get("move")

        raw_pv = best_info.get("pv")
        pv = (
            [
                str(move).upper()
                for move in raw_pv[:EXPLANATION_EVIDENCE_PV_MAX_MOVES]
            ]
            if isinstance(raw_pv, list)
            else []
        )
        best_candidate_visits = _optional_int(best_info, "visits") or 0

        search_wr_loss = 0.0
        search_score_loss = 0.0
        actual_candidate_visits = (
            (_optional_int(actual_info, "visits") or 0)
            if actual_info is not None
            else 0
        )
        root_visits = _root_visits(before_root)
        minimum_reliable_visits = _minimum_reliable_visits(root_visits)
        search_comparison_reliable = (
            actual_info is not None
            and bool(best_info)
            and actual_candidate_visits >= minimum_reliable_visits
            and _optional_float(best_info, "winrate") is not None
            and _optional_float(actual_info, "winrate") is not None
            and _optional_float(best_info, "scoreLead") is not None
            and _optional_float(actual_info, "scoreLead") is not None
        )
        if search_comparison_reliable:
            best_wr = _mover_value(
                _as_float(best_info, "winrate"), player, probability=True
            )
            actual_wr = _mover_value(
                _as_float(actual_info, "winrate"), player, probability=True
            )
            best_score = _mover_value(
                _as_float(best_info, "scoreLead"), player, probability=False
            )
            actual_score = _mover_value(
                _as_float(actual_info, "scoreLead"), player, probability=False
            )
            search_wr_loss = max(0.0, best_wr - actual_wr)
            search_score_loss = max(0.0, best_score - actual_score)

        pv_reliable = (
            isinstance(best_move, str)
            and bool(pv)
            and pv[0] == best_move.upper()
            and all(_is_valid_gtp_move(move) for move in pv)
            and best_candidate_visits >= minimum_reliable_visits
        )

        winrate_loss = max(observed_wr_loss, search_wr_loss)
        score_loss = max(observed_score_loss, search_score_loss)
        importance = classify_importance(
            winrate_loss, score_loss, thresholds=thresholds
        )
        crossed_even = (mover_wr_before >= 0.5) != (mover_wr_after >= 0.5)
        explanation_evidence = _build_explanation_evidence(
            before,
            after,
            before_root,
            after_root,
            actual_move,
        )
        explanation_features = build_explanation_features(
            explanation_evidence,
            all_moves,
            move_number,
            board_size=board_size,
        )
        explanation_classification = classify_explanation(
            explanation_evidence,
            explanation_features,
        )

        record = {
                "move_number": move_number,
                "player": player,
                "actual_move": actual_move,
                "best_move": best_move,
                "best_pv": pv,
                "best_candidate_visits": best_candidate_visits,
                "best_black_winrate": _optional_float(best_info, "winrate"),
                "best_black_score_lead": _optional_float(best_info, "scoreLead"),
                "pv_reliable": pv_reliable,
                # moveInfos comes from the position before the played move.
                "pv_base_move": move_number - 1,
                "pv_first_player": player,
                "black_winrate_before": black_wr_before,
                "black_winrate_after": black_wr_after,
                "mover_winrate_before": mover_wr_before,
                "mover_winrate_after": mover_wr_after,
                "winrate_change": mover_wr_after - mover_wr_before,
                "winrate_loss": winrate_loss,
                "observed_winrate_loss": observed_wr_loss,
                "search_winrate_loss": search_wr_loss,
                "black_score_before": black_score_before,
                "black_score_after": black_score_after,
                "mover_score_before": mover_score_before,
                "mover_score_after": mover_score_after,
                "score_change": mover_score_after - mover_score_before,
                "score_loss": score_loss,
                "observed_score_loss": observed_score_loss,
                "search_score_loss": search_score_loss,
                "actual_move_searched": actual_info is not None,
                "actual_candidate_visits": actual_candidate_visits,
                "search_comparison_reliable": search_comparison_reliable,
                "importance": importance,
                "crossed_even": crossed_even,
                "visits_before": before_root.get("visits"),
                "visits_after": after_root.get("visits"),
                "explanation_evidence": explanation_evidence,
                "explanation_features": explanation_features,
                "explanation_classification": explanation_classification,
            }
        record["structured_explanation"] = build_structured_explanation(record)
        records.append(record)
    return records


def thresholds_as_dict(
    thresholds: ImportanceThresholds = IMPORTANCE_THRESHOLDS,
) -> dict[str, float]:
    return {
        key: float(value)
        for key, value in thresholds.__dict__.items()
    }
