"""Validate Black/White perspective parity from saved artifacts only.

No KataGo process is started. Raw candidate values remain BLACK perspective;
the report checks mover-normalized analysis, review, and rendered text.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from analysis_logic import build_move_analyses
from directional_explanation import DirectionalFactId
from review_selection import build_game_review
from review_summary import build_structured_review_summary
from sgf_utils import get_moves_from_sgf
from structured_explanation import (
    build_structured_explanation,
    render_auto_commentary,
    render_detailed_commentary,
)


RECORDS_PATH = (
    PROJECT_ROOT / "benchmark/classifier_validation/validation_records.json"
)
QUALITY_LABELS_PATH = (
    PROJECT_ROOT / "benchmark/directional_commentary_manual_labels.json"
)
PERSPECTIVE_LABELS_PATH = (
    PROJECT_ROOT / "benchmark/perspective_parity_manual_labels.json"
)
GOLDEN_PATH = PROJECT_ROOT / "testdata/structured_explanation_golden.json"
OUTPUT_PATH = PROJECT_ROOT / "benchmark/perspective_parity_validation.json"

RELATIONSHIP_FACTS = {
    DirectionalFactId.SAME_DIRECTION,
    DirectionalFactId.DIFFERENT_DIRECTION,
}
PV_FACTS = {DirectionalFactId.RECOMMENDED_PV_STAYS_LOCAL}
CANDIDATE_FACTS = {
    DirectionalFactId.CANDIDATES_CONCENTRATED,
    DirectionalFactId.CANDIDATES_DISTRIBUTED,
}

SAMPLE_KEYS = {
    ("棋譜/[朴廷桓]vs[安成浚]1765452105010001779.sgf", 139),
    ("棋譜/[朴廷桓]vs[安成浚]1765452105010001779.sgf", 173),
    ("棋譜/[朴廷桓]vs[许皓鋐]1766559064010001206.sgf", 77),
    ("棋譜/[朴进率]vs[朴廷桓]1766236878010001427.sgf", 119),
    ("棋譜/[朴廷桓]vs[安成浚]1765452105010001779.sgf", 132),
    ("棋譜/[朴廷桓]vs[安成浚]1765452105010001779.sgf", 160),
    ("棋譜/[朴廷桓]vs[朴河旼]1767960653010001940.sgf", 66),
    ("棋譜/[朴廷桓]vs[许皓鋐]1766559064010001206.sgf", 138),
}


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _load_labels(path: Path, key: str) -> dict[tuple[str, int], dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        (item["sgf"], item["move_number"]): item
        for item in payload.get(key, [])
        if isinstance(item, dict)
        and isinstance(item.get("sgf"), str)
        and isinstance(item.get("move_number"), int)
    }


def _fact_ids(structured: dict[str, Any]) -> set[str]:
    facts = _mapping(structured.get("directional_evidence")).get("facts")
    return {
        item.get("id")
        for item in facts if isinstance(item, dict) and isinstance(item.get("id"), str)
    } if isinstance(facts, list) else set()


def _row(sgf: str, record: dict[str, Any]) -> dict[str, Any]:
    structured = record["structured_explanation"]
    severity = _mapping(structured.get("severity"))
    observed = _mapping(severity.get("observed"))
    recommendation = _mapping(structured.get("recommendation"))
    direct = _mapping(structured.get("direct_comparison"))
    direction = _mapping(structured.get("directional_evidence"))
    ids = _fact_ids(structured)
    return {
        "sgf": sgf,
        "move_number": record.get("move_number"),
        "player": record.get("player"),
        "actual_move": record.get("actual_move"),
        "recommended_move": recommendation.get("move"),
        "importance": record.get("importance"),
        "mover_winrate_before": observed.get("mover_winrate_before"),
        "mover_winrate_after": observed.get("mover_winrate_after"),
        "observed_winrate_loss": observed.get("winrate_loss"),
        "mover_score_before": observed.get("mover_score_before"),
        "mover_score_after": observed.get("mover_score_after"),
        "observed_score_loss": observed.get("score_loss"),
        "recommendation_reliable": recommendation.get("reliable") is True,
        "direct_comparison_available": direct.get("usable") is True,
        "direct_winrate_gap": direct.get("winrate_gap"),
        "direct_score_gap": direct.get("score_gap"),
        "directional_evidence_available": direction.get("available") is True,
        "actual_recommendation_region_fact": bool(ids & RELATIONSHIP_FACTS),
        "pv_directional_fact": bool(ids & PV_FACTS),
        "candidate_distribution_fact": bool(ids & CANDIDATE_FACTS),
        "variation_available": recommendation.get("variation_available") is True,
        "positive_directional_fact_ids": sorted(ids),
        "auto": render_auto_commentary(structured),
        "detailed": render_detailed_commentary(structured),
    }


def _aggregate(rows: list[dict[str, Any]], player: str) -> dict[str, Any]:
    selected = [row for row in rows if row["player"] == player]
    total = len(selected)

    def metric(key: str) -> dict[str, Any]:
        count = sum(row.get(key) is True for row in selected)
        return {
            "count": count,
            "percentage": round(count * 100.0 / total, 1) if total else 0.0,
        }

    return {
        "total_highlights": total,
        "important_count": sum(row["importance"] == "important" for row in selected),
        "decisive_count": sum(row["importance"] == "decisive" for row in selected),
        "reliable_recommendation": metric("recommendation_reliable"),
        "direct_comparison_available": metric("direct_comparison_available"),
        "directional_evidence_available": metric("directional_evidence_available"),
        "actual_recommendation_region_fact": metric("actual_recommendation_region_fact"),
        "pv_directional_fact": metric("pv_directional_fact"),
        "candidate_distribution_fact": metric("candidate_distribution_fact"),
        "variation_available": metric("variation_available"),
        "objective_and_limitation_only": {
            "count": sum(not row["directional_evidence_available"] for row in selected),
            "percentage": round(
                sum(not row["directional_evidence_available"] for row in selected)
                * 100.0
                / total,
                1,
            ) if total else 0.0,
        },
        "auto_available": metric("auto_available"),
        "detailed_available": metric("detailed_available"),
    }


def _position(winrate, score, recommended_wr, recommended_score, actual_wr, actual_score):
    return {
        "rootInfo": {"winrate": winrate, "scoreLead": score, "visits": 100},
        "moveInfos": [
            {"move": "D16", "order": 0, "visits": 60, "prior": 0.4,
             "winrate": recommended_wr, "scoreLead": recommended_score,
             "pv": ["D16", "E16", "D15"]},
            {"move": "Q4", "order": 1, "visits": 20, "prior": 0.2,
             "winrate": actual_wr, "scoreLead": actual_score,
             "pv": ["Q4", "R4", "Q3"]},
        ],
    }


def _synthetic_pair() -> dict[str, Any]:
    black = build_move_analyses(
        [["B", "Q4"]],
        {
            0: _position(0.70, 4.0, 0.74, 5.0, 0.64, 3.0),
            1: _position(0.55, 2.0, 0.58, 2.5, 0.54, 1.5),
        },
    )[0]
    white = build_move_analyses(
        [["W", "Q4"]],
        {
            0: _position(0.30, -4.0, 0.26, -5.0, 0.36, -3.0),
            1: _position(0.45, -2.0, 0.42, -2.5, 0.46, -1.5),
        },
    )[0]

    def summary(record: dict[str, Any]) -> dict[str, Any]:
        structured = record["structured_explanation"]
        direct = structured["direct_comparison"]
        review = build_game_review([copy.deepcopy(record)], total_moves=1)
        review_summary = build_structured_review_summary(review)
        return {
            "player": record["player"],
            "raw_black_winrate_before": record["black_winrate_before"],
            "raw_black_score_before": record["black_score_before"],
            "mover_winrate_before": record["mover_winrate_before"],
            "mover_winrate_after": record["mover_winrate_after"],
            "mover_score_before": record["mover_score_before"],
            "mover_score_after": record["mover_score_after"],
            "observed_winrate_loss": record["observed_winrate_loss"],
            "observed_score_loss": record["observed_score_loss"],
            "candidate_winrate_gap": direct["winrate_gap"],
            "candidate_score_gap": direct["score_gap"],
            "importance": record["importance"],
            "recommended_move": record["best_move"],
            "directional_evidence": structured["directional_evidence"],
            "review_selected_moves": [item["move_number"] for item in review["highlights"]],
            "review_primary_move": review_summary["priority"]["primary_move"],
            "auto": render_auto_commentary(structured),
            "detailed": render_detailed_commentary(structured),
        }

    black_summary = summary(black)
    white_summary = summary(white)
    return {
        "black": black_summary,
        "white": white_summary,
        "invariants": {
            "mover_values_equal": all(
                black_summary[key] == white_summary[key]
                for key in (
                    "mover_winrate_before", "mover_winrate_after",
                    "mover_score_before", "mover_score_after",
                )
            ),
            "observed_losses_equal": all(
                black_summary[key] == white_summary[key]
                for key in ("observed_winrate_loss", "observed_score_loss")
            ),
            "candidate_gaps_equal": all(
                black_summary[key] == white_summary[key]
                for key in ("candidate_winrate_gap", "candidate_score_gap")
            ),
            "importance_equal": black_summary["importance"] == white_summary["importance"],
            "geometry_equal": black_summary["directional_evidence"] == white_summary["directional_evidence"],
            "review_selection_equal": black_summary["review_selected_moves"] == white_summary["review_selected_moves"],
            "review_summary_equal": black_summary["review_primary_move"] == white_summary["review_primary_move"],
        },
    }


def _known_move_130(perspective_labels: dict[tuple[str, int], dict[str, Any]]) -> dict[str, Any]:
    payload = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    case = next(item for item in payload["cases"] if item["id"] == "actual_missing")
    record = copy.deepcopy(case["record"])
    record["structured_explanation"] = build_structured_explanation(record)
    row = _row("historical M6/E14 move-130 golden case", record)
    row["perspective_review"] = perspective_labels.get(
        ("historical M6/E14 move-130 golden case", 130)
    )
    return row


def build_report() -> dict[str, Any]:
    records_payload = json.loads(RECORDS_PATH.read_text(encoding="utf-8"))
    quality_labels = _load_labels(QUALITY_LABELS_PATH, "reviews")
    perspective_labels = _load_labels(PERSPECTIVE_LABELS_PATH, "reviews")
    grouped: dict[str, list[dict[str, Any]]] = {}
    for raw in records_payload.get("records", []):
        if not isinstance(raw, dict):
            continue
        record = copy.deepcopy(raw)
        sgf = _mapping(record.get("validation_source")).get("sgf")
        if not isinstance(sgf, str):
            continue
        record["structured_explanation"] = build_structured_explanation(record)
        grouped.setdefault(sgf, []).append(record)

    rows = []
    for sgf in sorted(grouped):
        records = grouped[sgf]
        review = build_game_review(
            records,
            total_moves=len(get_moves_from_sgf(PROJECT_ROOT / sgf)),
        )
        by_move = {record["move_number"]: record for record in records}
        for highlight in review["highlights"]:
            row = _row(sgf, by_move[highlight["move_number"]])
            row["auto_available"] = bool(row["auto"])
            row["detailed_available"] = bool(row["detailed"])
            quality = quality_labels.get((sgf, row["move_number"]))
            if quality:
                row["quality_review"] = {
                    "grade": quality.get("grade"),
                    "note": quality.get("note"),
                }
            rows.append(row)

    samples = {"B": [], "W": []}
    for row in rows:
        key = (row["sgf"], row["move_number"])
        if key not in SAMPLE_KEYS:
            continue
        sample = copy.deepcopy(row)
        sample["perspective_review"] = perspective_labels.get(key)
        samples[row["player"]].append(sample)

    quality_by_color = {}
    for player in ("B", "W"):
        counts = Counter(
            row.get("quality_review", {}).get("grade")
            for row in rows if row["player"] == player
        )
        quality_by_color[player] = {
            grade: counts.get(grade, 0) for grade in ("A", "B", "C", "D")
        }
    perspective_counts = {}
    for player in ("B", "W"):
        counts = Counter(
            _mapping(sample.get("perspective_review")).get("perspective")
            for sample in samples[player]
        )
        perspective_counts[player] = {
            label: counts.get(label, 0)
            for label in ("correct", "suspicious", "incorrect")
        }

    synthetic = _synthetic_pair()
    incorrect = sum(
        counts["incorrect"] for counts in perspective_counts.values()
    )
    invariant_failures = [
        key for key, passed in synthetic["invariants"].items() if not passed
    ]
    return {
        "schema_version": 1,
        "source": str(RECORDS_PATH.relative_to(PROJECT_ROOT)),
        "katago_rerun": False,
        "black_metrics": _aggregate(rows, "B"),
        "white_metrics": _aggregate(rows, "W"),
        "sampled_black_cases": samples["B"],
        "sampled_white_cases": samples["W"],
        "known_move_130_white": _known_move_130(perspective_labels),
        "synthetic_parity": synthetic,
        "manual_quality_by_color": quality_by_color,
        "perspective_correctness_by_color": perspective_counts,
        "detected_asymmetries": (
            [{"type": "synthetic_invariant_failure", "items": invariant_failures}]
            if invariant_failures
            else []
        ),
        "incorrect_perspective_case_count": incorrect,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()
    report = build_report()
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "black_metrics": report["black_metrics"],
        "white_metrics": report["white_metrics"],
        "perspective_correctness": report["perspective_correctness_by_color"],
        "detected_asymmetries": report["detected_asymmetries"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
