"""Validate Phase 5C commentary with saved real analysis artifacts only.

The script never starts KataGo. It rebuilds the frozen Phase 4B selection from
the existing Phase 3C records, then measures positive directional coverage on
the selected highlights.
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

from directional_explanation import DirectionalFactId
from review_selection import build_game_review
from sgf_utils import get_moves_from_sgf
from structured_explanation import (
    build_structured_explanation,
    render_auto_commentary,
    render_detailed_commentary,
)


DEFAULT_RECORDS = (
    PROJECT_ROOT / "benchmark/classifier_validation/validation_records.json"
)
DEFAULT_LABELS = (
    PROJECT_ROOT / "benchmark/directional_commentary_manual_labels.json"
)
DEFAULT_OUTPUT = (
    PROJECT_ROOT / "benchmark/directional_commentary_validation.json"
)
GOLDEN_PATH = PROJECT_ROOT / "testdata/structured_explanation_golden.json"

RELATIONSHIP_FACTS = {
    DirectionalFactId.SAME_DIRECTION,
    DirectionalFactId.DIFFERENT_DIRECTION,
}
PV_FACTS = {DirectionalFactId.RECOMMENDED_PV_STAYS_LOCAL}
CANDIDATE_FACTS = {
    DirectionalFactId.CANDIDATES_CONCENTRATED,
    DirectionalFactId.CANDIDATES_DISTRIBUTED,
}


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _load_labels(path: Path) -> dict[tuple[str, int], dict[str, str]]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    labels = {}
    for item in payload.get("reviews", []):
        if (
            isinstance(item, dict)
            and isinstance(item.get("sgf"), str)
            and isinstance(item.get("move_number"), int)
            and item.get("grade") in {"A", "B", "C", "D"}
        ):
            labels[(item["sgf"], item["move_number"])] = {
                "grade": item["grade"],
                "note": str(item.get("note") or ""),
            }
    return labels


def _fact_ids(structured: dict[str, Any]) -> set[str]:
    directional = _mapping(structured.get("directional_evidence"))
    facts = directional.get("facts")
    if not isinstance(facts, list):
        return set()
    return {
        item.get("id")
        for item in facts
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }


def _known_move_130() -> dict[str, Any]:
    payload = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    case = next(item for item in payload["cases"] if item["id"] == "actual_missing")
    structured = build_structured_explanation(copy.deepcopy(case["record"]))
    return {
        "source": "historical M6/E14 move-130 golden case",
        "note": (
            "The saved Phase 3C Park-vs-An artifact has M11/B7 at move 130; "
            "the requested M6/E14 case is preserved as the historical golden "
            "fixture and is not relabeled as urgent-vs-big."
        ),
        "directional_evidence": structured["directional_evidence"],
        "auto": render_auto_commentary(structured),
        "detailed": render_detailed_commentary(structured),
    }


def build_report(
    records_payload: dict[str, Any],
    labels: dict[tuple[str, int], dict[str, str]],
) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for raw in records_payload.get("records", []):
        if not isinstance(raw, dict):
            continue
        record = copy.deepcopy(raw)
        sgf_path = _mapping(record.get("validation_source")).get("sgf")
        if not isinstance(sgf_path, str):
            continue
        record["structured_explanation"] = build_structured_explanation(record)
        grouped.setdefault(sgf_path, []).append(record)

    rows = []
    games = []
    for sgf_path in sorted(grouped):
        records = grouped[sgf_path]
        total_moves = len(get_moves_from_sgf(PROJECT_ROOT / sgf_path))
        review = build_game_review(records, total_moves=total_moves)
        by_move = {record["move_number"]: record for record in records}
        selected_moves = []
        for highlight in review["highlights"]:
            move_number = highlight["move_number"]
            record = by_move[move_number]
            structured = record["structured_explanation"]
            direction = _mapping(structured.get("directional_evidence"))
            ids = _fact_ids(structured)
            label = labels.get((sgf_path, move_number))
            row = {
                "sgf": sgf_path,
                "move_number": move_number,
                "player": record.get("player"),
                "actual_move": record.get("actual_move"),
                "recommended_move": record.get("best_move"),
                "importance": record.get("importance"),
                "recommendation_reliable": _mapping(
                    structured.get("recommendation")
                ).get("reliable")
                is True,
                "directional_available": direction.get("available") is True,
                "actual_recommendation_fact": bool(ids & RELATIONSHIP_FACTS),
                "pv_directional_fact": bool(ids & PV_FACTS),
                "candidate_distribution_fact": bool(ids & CANDIDATE_FACTS),
                "directional_fact_ids": sorted(ids),
                "auto": render_auto_commentary(structured),
                "detailed": render_detailed_commentary(structured),
                "manual_review": label
                or {"grade": "unreviewed", "note": "尚未人工檢查"},
            }
            rows.append(row)
            selected_moves.append(move_number)
        games.append(
            {
                "sgf": sgf_path,
                "artifact_record_count": len(records),
                "selected_moves": selected_moves,
            }
        )

    manual_counts = Counter(
        row["manual_review"]["grade"]
        for row in rows
        if row["manual_review"]["grade"] in {"A", "B", "C", "D"}
    )
    metrics = {
        "total_highlights": len(rows),
        "reliable_recommendation": sum(
            row["recommendation_reliable"] for row in rows
        ),
        "directional_evidence_available": sum(
            row["directional_available"] for row in rows
        ),
        "actual_vs_recommendation_region_fact": sum(
            row["actual_recommendation_fact"] for row in rows
        ),
        "reliable_pv_directional_fact": sum(
            row["pv_directional_fact"] for row in rows
        ),
        "candidate_distribution_fact": sum(
            row["candidate_distribution_fact"] for row in rows
        ),
        "objective_recommendation_limitation_only": sum(
            not row["directional_available"] for row in rows
        ),
    }
    return {
        "schema_version": 1,
        "source": str(DEFAULT_RECORDS.relative_to(PROJECT_ROOT)),
        "katago_rerun": False,
        "scope": (
            "Frozen Phase 4B selection rebuilt from saved real Phase 3C "
            "analysis artifacts; no new KataGo query was made."
        ),
        "games": games,
        "metrics": metrics,
        "manual_quality_counts": {
            grade: manual_counts.get(grade, 0) for grade in ("A", "B", "C", "D")
        },
        "manual_reviewed_count": sum(manual_counts.values()),
        "highlights": rows,
        "known_move_130": _known_move_130(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--records", type=Path, default=DEFAULT_RECORDS)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    payload = json.loads(args.records.read_text(encoding="utf-8"))
    report = build_report(payload, _load_labels(args.labels))
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report["metrics"], ensure_ascii=False, indent=2))
    print(
        "manual quality:",
        json.dumps(report["manual_quality_counts"], ensure_ascii=False),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
