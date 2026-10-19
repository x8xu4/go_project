"""Evidence-grounded structured explanations and deterministic renderers.

This V1 layer intentionally does not consume explanation classification. It
distinguishes observed before/after changes from direct candidate comparisons,
describes deterministic Phase 2 geometry, and abstains from unsupported
Go-principle claims.
"""

from __future__ import annotations

import math
from typing import Any

from directional_explanation import (
    DirectionalFactId,
    build_directional_evidence,
    region_label_zh,
)


STRUCTURED_EXPLANATION_SCHEMA_VERSION = 1


class LimitationId:
    ACTUAL_CANDIDATE_MISSING = "actual_candidate_missing"
    ACTUAL_CANDIDATE_UNRELIABLE = "actual_candidate_unreliable"
    RECOMMENDED_CANDIDATE_MISSING = "recommended_candidate_missing"
    RECOMMENDED_CANDIDATE_UNRELIABLE = "recommended_candidate_unreliable"
    DIRECT_COMPARISON_UNAVAILABLE = "direct_comparison_unavailable"
    RECOMMENDED_PV_UNAVAILABLE = "recommended_pv_unavailable"
    SPECIFIC_GO_REASON_NOT_ESTABLISHED = (
        "specific_go_reason_not_established"
    )


class FactId:
    OBSERVED_WINRATE_CHANGE = "observed_winrate_change"
    OBSERVED_SCORE_CHANGE = "observed_score_change"
    RELIABLE_RECOMMENDATION = "reliable_recommendation"
    DIRECT_CANDIDATE_COMPARISON = "direct_candidate_comparison"
    RECOMMENDED_VARIATION_AVAILABLE = "recommended_variation_available"


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _finite_number(value: Any) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _nonnegative_int(value: Any) -> int | None:
    number = _finite_number(value)
    if number is None:
        return None
    integer = int(number)
    return integer if integer >= 0 else None


def _move(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip().upper()


def _mover_value(
    black_value: float | None,
    player: str | None,
    *,
    probability: bool,
) -> float | None:
    if black_value is None or player not in {"B", "W"}:
        return None
    if player == "B":
        return black_value
    return 1.0 - black_value if probability else -black_value


def _observed_loss(
    explicit: Any,
    before: float | None,
    after: float | None,
) -> float | None:
    value = _finite_number(explicit)
    if value is not None:
        return max(0.0, value)
    if before is None or after is None:
        return None
    return max(0.0, before - after)


def _candidate_from_legacy(
    record: dict[str, Any],
    *,
    recommended: bool,
) -> dict[str, Any]:
    if recommended:
        move = _move(record.get("best_move"))
        reliable = record.get("pv_reliable") is True
        return {
            "found": move is not None,
            "move": move,
            "order": 0 if move is not None else None,
            "reliable": reliable,
            "winrate_black": _finite_number(
                record.get("best_black_winrate")
            ),
            "score_lead_black": _finite_number(
                record.get("best_black_score_lead")
            ),
        }
    return {
        "found": record.get("actual_move_searched") is True,
        "move": _move(record.get("actual_move")),
        "order": None,
        "reliable": record.get("search_comparison_reliable") is True,
        "winrate_black": None,
        "score_lead_black": None,
    }


def _candidate(
    before_evidence: dict[str, Any],
    record: dict[str, Any],
    key: str,
) -> dict[str, Any]:
    if key in before_evidence:
        raw = before_evidence.get(key)
        return raw if isinstance(raw, dict) else {}
    return _candidate_from_legacy(record, recommended=key == "recommended")


def _bounded_pv(record: dict[str, Any]) -> list[str]:
    raw = record.get("best_pv")
    if not isinstance(raw, list):
        return []
    return [move for item in raw if (move := _move(item)) is not None]


def build_structured_explanation(record: Any) -> dict[str, Any]:
    """Build a JSON-safe V1 explanation without using classifier output."""

    record = _mapping(record)
    player = record.get("player") if record.get("player") in {"B", "W"} else None
    actual_move = _move(record.get("actual_move"))
    evidence = _mapping(record.get("explanation_evidence"))
    before_evidence = _mapping(evidence.get("before"))
    actual = _candidate(before_evidence, record, "actual")
    recommended = _candidate(before_evidence, record, "recommended")

    mover_wr_before = _finite_number(record.get("mover_winrate_before"))
    mover_wr_after = _finite_number(record.get("mover_winrate_after"))
    mover_score_before = _finite_number(record.get("mover_score_before"))
    mover_score_after = _finite_number(record.get("mover_score_after"))
    observed_wr_loss = _observed_loss(
        record.get("observed_winrate_loss"),
        mover_wr_before,
        mover_wr_after,
    )
    observed_score_loss = _observed_loss(
        record.get("observed_score_loss"),
        mover_score_before,
        mover_score_after,
    )

    recommended_found = recommended.get("found") is True
    recommended_reliable = recommended.get("reliable") is True
    actual_found = actual.get("found") is True
    actual_reliable = actual.get("reliable") is True
    recommendation_move = _move(recommended.get("move")) or _move(
        record.get("best_move")
    )

    recommended_wr = _mover_value(
        _finite_number(recommended.get("winrate_black")),
        player,
        probability=True,
    )
    actual_wr = _mover_value(
        _finite_number(actual.get("winrate_black")),
        player,
        probability=True,
    )
    recommended_score = _mover_value(
        _finite_number(recommended.get("score_lead_black")),
        player,
        probability=False,
    )
    actual_score = _mover_value(
        _finite_number(actual.get("score_lead_black")),
        player,
        probability=False,
    )
    values_available = all(
        value is not None
        for value in (
            recommended_wr,
            actual_wr,
            recommended_score,
            actual_score,
        )
    )
    direct_usable = (
        recommended_found
        and recommended_reliable
        and actual_found
        and actual_reliable
        and values_available
    )
    direct_wr_gap = (
        recommended_wr - actual_wr if direct_usable else None
    )
    direct_score_gap = (
        recommended_score - actual_score if direct_usable else None
    )

    pv = _bounded_pv(record)
    variation_available = (
        recommended_found
        and recommended_reliable
        and record.get("pv_reliable") is True
        and bool(pv)
        and recommendation_move is not None
        and pv[0] == recommendation_move
    )

    limitations: list[str] = []
    facts: list[str] = []
    if observed_wr_loss is not None:
        facts.append(FactId.OBSERVED_WINRATE_CHANGE)
    if observed_score_loss is not None:
        facts.append(FactId.OBSERVED_SCORE_CHANGE)
    if not recommended_found:
        limitations.append(LimitationId.RECOMMENDED_CANDIDATE_MISSING)
    elif not recommended_reliable:
        limitations.append(LimitationId.RECOMMENDED_CANDIDATE_UNRELIABLE)
    else:
        facts.append(FactId.RELIABLE_RECOMMENDATION)
    if not actual_found:
        limitations.append(LimitationId.ACTUAL_CANDIDATE_MISSING)
    elif not actual_reliable:
        limitations.append(LimitationId.ACTUAL_CANDIDATE_UNRELIABLE)
    if direct_usable:
        facts.append(FactId.DIRECT_CANDIDATE_COMPARISON)
    else:
        limitations.append(LimitationId.DIRECT_COMPARISON_UNAVAILABLE)
    if variation_available:
        facts.append(FactId.RECOMMENDED_VARIATION_AVAILABLE)
    else:
        limitations.append(LimitationId.RECOMMENDED_PV_UNAVAILABLE)
    limitations.append(LimitationId.SPECIFIC_GO_REASON_NOT_ESTABLISHED)

    if direct_usable:
        level = "direct_comparison"
    elif recommended_found and recommended_reliable:
        level = "recommendation_only"
    else:
        level = "limited"

    directional_evidence = build_directional_evidence(
        record,
        recommendation_found=recommended_found,
        recommendation_reliable=recommended_reliable,
        variation_available=variation_available,
    )

    return {
        "schema_version": STRUCTURED_EXPLANATION_SCHEMA_VERSION,
        "move": {
            "number": _nonnegative_int(record.get("move_number")),
            "player": player,
            "actual": actual_move,
        },
        "severity": {
            "importance": record.get("importance")
            if isinstance(record.get("importance"), str)
            else "ordinary",
            "observed": {
                "mover_winrate_before": mover_wr_before,
                "mover_winrate_after": mover_wr_after,
                "winrate_loss": observed_wr_loss,
                "mover_score_before": mover_score_before,
                "mover_score_after": mover_score_after,
                "score_loss": observed_score_loss,
            },
            "combined_importance_basis": {
                "winrate_loss": _finite_number(record.get("winrate_loss")),
                "score_loss": _finite_number(record.get("score_loss")),
            },
        },
        "recommendation": {
            "move": recommendation_move,
            "found": recommended_found,
            "reliable": recommended_reliable,
            "pv": pv if variation_available else [],
            "pv_reliable": variation_available,
            "variation_available": variation_available,
        },
        "direct_comparison": {
            "usable": direct_usable,
            "actual_found": actual_found,
            "actual_reliable": actual_reliable,
            "actual_order": _nonnegative_int(actual.get("order")),
            "recommended_found": recommended_found,
            "recommended_reliable": recommended_reliable,
            "recommended_order": _nonnegative_int(recommended.get("order")),
            "winrate_gap": direct_wr_gap,
            "score_gap": direct_score_gap,
        },
        "directional_evidence": directional_evidence,
        "interpretation": {
            "level": level,
            "facts": facts,
            "limitations": limitations,
        },
    }


def _player_name(player: Any) -> str:
    if player == "B":
        return "黑棋"
    if player == "W":
        return "白棋"
    return "落子方"


def _importance_opening(importance: Any, move_number: Any) -> str:
    number = move_number if isinstance(move_number, int) else 0
    if importance == "decisive":
        return f"第 {number} 手造成明顯局勢變化。"
    if importance == "important":
        return f"第 {number} 手值得注意。"
    if importance == "notice":
        return f"第 {number} 手出現一定的局勢變化。"
    return f"第 {number} 手。"


def _rounded_positive(value: Any, *, scale: float = 1.0) -> float | None:
    number = _finite_number(value)
    if number is None:
        return None
    displayed = round(max(0.0, number) * scale, 1)
    return displayed if displayed > 0.0 else None


def _observed_loss_sentence(
    player_name: str,
    actual_move: str,
    observed: dict[str, Any],
) -> str:
    wr_loss = _rounded_positive(observed.get("winrate_loss"), scale=100.0)
    score_loss = _rounded_positive(observed.get("score_loss"))
    parts = []
    if wr_loss is not None:
        parts.append(f"勝率估計下降約 {wr_loss:.1f} 個百分點")
    if score_loss is not None:
        parts.append(f"目數評估約下降 {score_loss:.1f} 目")
    if parts:
        return f"{player_name}實戰 {actual_move} 後，" + "，".join(parts) + "。"
    has_before_after = any(
        _finite_number(observed.get(key)) is not None
        for key in (
            "mover_winrate_before",
            "mover_winrate_after",
            "mover_score_before",
            "mover_score_after",
        )
    )
    if not has_before_after:
        return f"{player_name}實戰下在 {actual_move}；目前資料不足以描述前後變化。"
    return f"{player_name}實戰下在 {actual_move}；前後局面評估沒有顯示明確下降。"


def _score_state(value: Any) -> str | None:
    score = _finite_number(value)
    if score is None:
        return None
    rounded = round(score, 1)
    if rounded > 0.0:
        return f"領先約 {rounded:.1f} 目"
    if rounded < 0.0:
        return f"落後約 {abs(rounded):.1f} 目"
    return "接近持平"


def _region_phrase(region: Any) -> str | None:
    return region_label_zh(region)


def _region_area_phrase(region: Any) -> str | None:
    label = _region_phrase(region)
    if label is None:
        return None
    if region in {"top", "left", "right", "bottom"}:
        return f"{label}一帶"
    return f"{label}附近"


def _directional_fact_sentences(directional: Any) -> list[str]:
    directional = _mapping(directional)
    actual = _mapping(directional.get("actual"))
    recommendation = _mapping(directional.get("recommendation"))
    actual_move = _move(actual.get("move")) or "實戰著"
    recommended_move = _move(recommendation.get("move")) or "推薦著"
    raw_facts = directional.get("facts")
    facts = raw_facts if isinstance(raw_facts, list) else []
    sentences: list[str] = []
    for raw_fact in facts:
        fact = _mapping(raw_fact)
        fact_id = fact.get("id")
        if fact_id == DirectionalFactId.SAME_DIRECTION:
            region = _region_phrase(fact.get("recommended_region"))
            if region:
                sentences.append(
                    f"實戰 {actual_move} 與推薦 {recommended_move} 都位於{region}，"
                    "兩者的大方向相近。"
                )
        elif fact_id == DirectionalFactId.DIFFERENT_DIRECTION:
            actual_region = _region_phrase(fact.get("actual_region"))
            recommended_region = _region_phrase(fact.get("recommended_region"))
            if actual_region and recommended_region:
                sentences.append(
                    f"從盤面方向來看，實戰 {actual_move} 位於{actual_region}，"
                    f"推薦 {recommended_move} 位於{recommended_region}，"
                    "兩者選擇的方向明顯不同。"
                )
        elif fact_id == DirectionalFactId.RECOMMENDED_PV_STAYS_LOCAL:
            area = _region_area_phrase(fact.get("region"))
            if area:
                sentences.append(
                    f"推薦後的主要變化也持續集中在{area}，"
                    "顯示這一帶是這條推薦變化的主要焦點。"
                )
        elif fact_id == DirectionalFactId.CANDIDATES_CONCENTRATED:
            region = _region_phrase(fact.get("region"))
            if region:
                sentences.append(
                    f"較佳候選多集中在{region}，"
                    "KataGo 對這個方向的偏好較一致。"
                )
        elif fact_id == DirectionalFactId.CANDIDATES_DISTRIBUTED:
            sentences.append(
                "較佳候選分布在不同區域，沒有呈現單一而明確的落子方向。"
            )
    return sentences


def render_auto_commentary(structured: Any) -> str:
    """Render concise deterministic commentary from structured evidence."""

    structured = _mapping(structured)
    move = _mapping(structured.get("move"))
    severity = _mapping(structured.get("severity"))
    observed = _mapping(severity.get("observed"))
    recommendation = _mapping(structured.get("recommendation"))
    directional = _mapping(structured.get("directional_evidence"))
    player_name = _player_name(move.get("player"))
    actual_move = _move(move.get("actual")) or "未知位置"
    lines = [
        _importance_opening(severity.get("importance"), move.get("number")),
        _observed_loss_sentence(player_name, actual_move, observed),
    ]
    recommended_move = _move(recommendation.get("move"))
    if recommendation.get("reliable") is True and recommended_move:
        if recommended_move == actual_move:
            lines.append("實戰著也是 KataGo 落子前的一選。")
        else:
            lines.append(f"KataGo 在落子前較推薦 {recommended_move}。")
    directional_sentences = _directional_fact_sentences(directional)
    if directional_sentences:
        if len(lines) >= 3:
            lines[-1] = lines[-1] + directional_sentences[0]
        else:
            lines.append(directional_sentences[0])
    return "\n".join(lines)


def render_detailed_commentary(structured: Any) -> str:
    """Render detailed deterministic commentary without Go-principle guesses."""

    structured = _mapping(structured)
    move = _mapping(structured.get("move"))
    severity = _mapping(structured.get("severity"))
    observed = _mapping(severity.get("observed"))
    recommendation = _mapping(structured.get("recommendation"))
    direct = _mapping(structured.get("direct_comparison"))
    directional = _mapping(structured.get("directional_evidence"))
    interpretation = _mapping(structured.get("interpretation"))
    limitations = interpretation.get("limitations")
    limitations = limitations if isinstance(limitations, list) else []

    player_name = _player_name(move.get("player"))
    actual_move = _move(move.get("actual")) or "未知位置"
    number = move.get("number") if isinstance(move.get("number"), int) else 0
    paragraphs = [f"第 {number} 手，{player_name}實戰下在 {actual_move}。"]

    before_wr = _finite_number(observed.get("mover_winrate_before"))
    after_wr = _finite_number(observed.get("mover_winrate_after"))
    wr_loss = _rounded_positive(observed.get("winrate_loss"), scale=100.0)
    before_score = _score_state(observed.get("mover_score_before"))
    after_score = _score_state(observed.get("mover_score_after"))
    score_loss = _rounded_positive(observed.get("score_loss"))
    observed_parts = []
    if before_wr is not None and after_wr is not None:
        wr_text = (
            f"勝率由約 {before_wr * 100:.1f}% 變為 {after_wr * 100:.1f}%"
        )
        if wr_loss is not None:
            wr_text += f"，估計下降約 {wr_loss:.1f} 個百分點"
        observed_parts.append(wr_text)
    if before_score is not None and after_score is not None:
        score_text = f"目數評估由{before_score}變為{after_score}"
        if score_loss is not None:
            score_text += f"，估計下降約 {score_loss:.1f} 目"
        observed_parts.append(score_text)
    if observed_parts:
        paragraphs.append("；".join(observed_parts) + "。")
    else:
        paragraphs.append("本次資料不足以完整描述落子前後的局面變化。")

    recommended_move = _move(recommendation.get("move"))
    if recommendation.get("reliable") is True and recommended_move:
        if recommended_move == actual_move:
            paragraphs.append("實戰著也是 KataGo 落子前的一選。")
        else:
            paragraphs.append(f"KataGo 在落子前較推薦 {recommended_move}。")
            if direct.get("usable") is True:
                paragraphs.append(
                    f"在同一次搜尋中，KataGo 也充分考慮了實戰 {actual_move}，"
                    f"搜尋排序較偏好 {recommended_move}。"
                )
                wr_gap = _rounded_positive(
                    direct.get("winrate_gap"), scale=100.0
                )
                score_gap = _rounded_positive(direct.get("score_gap"))
                gap_parts = []
                if wr_gap is not None:
                    gap_parts.append(f"勝率評估相差約 {wr_gap:.1f} 個百分點")
                if score_gap is not None:
                    gap_parts.append(f"目數評估相差約 {score_gap:.1f} 目")
                if gap_parts:
                    paragraphs.append("，".join(gap_parts) + "。")
    else:
        paragraphs.append("本次搜尋沒有足夠可靠的推薦候選。")

    directional_sentences = _directional_fact_sentences(directional)
    paragraphs.extend(directional_sentences)

    if recommendation.get("variation_available") is True:
        paragraphs.append(
            "KataGo 的推薦變化已保留，可使用「查看推薦變化圖」在棋盤上查看。"
        )
    if (
        recommended_move
        and recommended_move != actual_move
        and direct.get("usable") is not True
    ):
        paragraphs.append(
            f"目前無法可靠地直接比較實戰 {actual_move} 與推薦 "
            f"{recommended_move} 本身的評價差距。"
        )
    if LimitationId.SPECIFIC_GO_REASON_NOT_ESTABLISHED in limitations:
        paragraphs.append(
            "至於這個差異背後的具體棋理，目前證據不足以可靠區分，"
            "因此不再進一步猜測。"
        )
    return "\n\n".join(paragraphs)
