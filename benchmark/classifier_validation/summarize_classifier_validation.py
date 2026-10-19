"""Produce Phase 3C validation tables without changing classifier behavior."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any


VALIDATION_DIR = Path(__file__).resolve().parent
DEFAULT_RECORDS = VALIDATION_DIR / "validation_records.json"
DEFAULT_LABELS = VALIDATION_DIR / "manual_review_labels.json"
DEFAULT_REPORT = VALIDATION_DIR / "validation_report.json"
DEFAULT_TABLE = VALIDATION_DIR / "validation_table.csv"
DEFAULT_REVIEW = VALIDATION_DIR / "manual_review.csv"
PRODUCT_IMPORTANCE = {"important", "decisive"}


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _count_distribution(
    records: list[dict[str, Any]],
    fields: tuple[str, ...],
) -> list[dict[str, Any]]:
    counts = Counter(
        tuple(
            _mapping(record.get("explanation_classification")).get(field)
            for field in fields
        )
        for record in records
    )
    return [
        {
            **{field: values[index] for index, field in enumerate(fields)},
            "count": count,
            "percentage": count / len(records) if records else 0.0,
        }
        for values, count in sorted(counts.items())
    ]


def _flatten_record(record: dict[str, Any]) -> dict[str, Any]:
    source = _mapping(record.get("validation_source"))
    evidence = _mapping(record.get("explanation_evidence"))
    before = _mapping(evidence.get("before"))
    actual = _mapping(before.get("actual"))
    recommended = _mapping(before.get("recommended"))
    features = _mapping(record.get("explanation_features"))
    comparison = _mapping(features.get("actual_recommended"))
    recommended_pv = _mapping(features.get("recommended_pv"))
    actual_pv = _mapping(features.get("actual_pv"))
    classification = _mapping(record.get("explanation_classification"))
    return {
        "sgf": source.get("sgf"),
        "phase": source.get("phase"),
        "move_number": record.get("move_number"),
        "player": record.get("player"),
        "actual_move": record.get("actual_move"),
        "recommended_move": record.get("best_move"),
        "importance": record.get("importance"),
        "observed_winrate_loss": record.get("observed_winrate_loss"),
        "observed_score_loss": record.get("observed_score_loss"),
        "search_winrate_loss": record.get("search_winrate_loss"),
        "search_score_loss": record.get("search_score_loss"),
        "winrate_loss": record.get("winrate_loss"),
        "score_loss": record.get("score_loss"),
        "actual_candidate_found": actual.get("found"),
        "actual_candidate_reliable": actual.get("reliable"),
        "actual_order": actual.get("order"),
        "actual_visits": actual.get("visits"),
        "recommended_reliable": recommended.get("reliable"),
        "recommended_visits": recommended.get("visits"),
        "minimum_reliable_visits": before.get("minimum_reliable_visits"),
        "actual_recommended_same_region": comparison.get("same_region"),
        "actual_recommended_locality": comparison.get("locality"),
        "actual_recommended_chebyshev": comparison.get(
            "chebyshev_distance"
        ),
        "recommended_pv_usable": recommended_pv.get("usable"),
        "recommended_pv_local": recommended_pv.get("stays_local"),
        "recommended_pv_near_ratio": recommended_pv.get("near_ratio"),
        "actual_pv_usable": actual_pv.get("usable"),
        "actual_pv_local": actual_pv.get("stays_local"),
        "actual_pv_near_ratio": actual_pv.get("near_ratio"),
        "classification_category": classification.get("category"),
        "confidence": classification.get("confidence"),
        "abstained": classification.get("abstained"),
        "supporting_evidence": classification.get("supporting_evidence"),
        "contradictions": classification.get("contradictions"),
        "missing_evidence": classification.get("missing_evidence"),
        "limitations": classification.get("limitations"),
    }


def _reason_frequencies(
    records: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    result = {}
    for field in ("missing_evidence", "contradictions", "limitations"):
        counts = Counter(
            reason
            for record in records
            for reason in _mapping(
                record.get("explanation_classification")
            ).get(field, [])
        )
        result[field] = [
            {
                "reason": reason,
                "count": count,
                "percentage_of_uncertain": count / len(records)
                if records
                else 0.0,
            }
            for reason, count in counts.most_common()
        ]
    return result


def _exclusive_bottlenecks(
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    for record in records:
        classification = _mapping(record.get("explanation_classification"))
        missing = set(classification.get("missing_evidence", []))
        contradictions = set(classification.get("contradictions", []))
        if "actual_candidate_missing" in missing:
            counts["actual_candidate_missing"] += 1
        elif "actual_candidate_unreliable" in missing:
            counts["actual_candidate_unreliable"] += 1
        elif "recommended_candidate_missing" in missing:
            counts["recommended_candidate_missing"] += 1
        elif "recommended_candidate_unreliable" in missing:
            counts["recommended_candidate_unreliable"] += 1
        elif "strong_locality_conflict" in contradictions:
            counts["nonlocal_pv_or_locality_conflict"] += 1
        elif "insufficient_independent_evidence" in missing:
            counts["insufficient_independent_evidence"] += 1
        else:
            counts["other"] += 1
    return [
        {
            "reason_group": reason,
            "count": count,
            "percentage_of_uncertain": count / len(records)
            if records
            else 0.0,
        }
        for reason, count in counts.most_common()
    ]


def _threshold_edges(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    edges = []
    for record in records:
        flat = _flatten_record(record)
        if flat["classification_category"] == "uncertain":
            continue
        reasons = []
        minimum = flat["minimum_reliable_visits"]
        for prefix in ("actual", "recommended"):
            visits = flat[f"{prefix}_visits"]
            if (
                isinstance(visits, int)
                and isinstance(minimum, int)
                and 0 <= visits - minimum <= 2
            ):
                reasons.append(f"{prefix}_visit_margin={visits - minimum}")
        distance = flat["actual_recommended_chebyshev"]
        if distance in (3, 4, 7, 8):
            reasons.append(f"chebyshev_distance={distance}")
        for prefix in ("actual", "recommended"):
            ratio = flat[f"{prefix}_pv_near_ratio"]
            if isinstance(ratio, (int, float)) and 0.70 <= ratio <= 0.75:
                reasons.append(f"{prefix}_pv_near_ratio={ratio:.3f}")
        if reasons:
            edges.append(
                {
                    "sgf": flat["sgf"],
                    "move_number": flat["move_number"],
                    "importance": flat["importance"],
                    "category": flat["classification_category"],
                    "confidence": flat["confidence"],
                    "edge_reasons": reasons,
                }
            )
    return edges


def _manual_reviews(
    records: list[dict[str, Any]],
    labels_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    by_key = {
        (
            record["validation_source"]["sgf"],
            record["move_number"],
        ): record
        for record in records
    }
    reviews = []
    for requested in labels_payload["reviews"]:
        key = (requested["sgf"], requested["move_number"])
        record = by_key.get(key)
        if record is None:
            raise ValueError(f"manual review target missing: {key}")
        flat = _flatten_record(record)
        if flat["classification_category"] == "uncertain":
            raise ValueError(f"manual review target abstained: {key}")
        reviews.append(
            {
                **flat,
                "manual_label": requested["label"],
                "manual_note": requested["note"],
            }
        )
    return reviews


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    normalized = []
    for row in rows:
        normalized.append(
            {
                key: json.dumps(value, ensure_ascii=False)
                if isinstance(value, (list, dict))
                else value
                for key, value in row.items()
            }
        )
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(normalized[0]))
        writer.writeheader()
        writer.writerows(normalized)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--records", type=Path, default=DEFAULT_RECORDS)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--table", type=Path, default=DEFAULT_TABLE)
    parser.add_argument("--review", type=Path, default=DEFAULT_REVIEW)
    args = parser.parse_args()

    payload = json.loads(args.records.read_text(encoding="utf-8"))
    labels = json.loads(args.labels.read_text(encoding="utf-8"))
    all_records = payload["records"]
    product_records = [
        record
        for record in all_records
        if record.get("importance") in PRODUCT_IMPORTANCE
    ]
    uncertain = [
        record
        for record in product_records
        if _mapping(record.get("explanation_classification")).get("category")
        == "uncertain"
    ]
    classified = len(product_records) - len(uncertain)
    table = [_flatten_record(record) for record in product_records]
    reviews = _manual_reviews(all_records, labels)
    report = {
        "schema_version": 1,
        "sgf_count": payload["sgf_count"],
        "analyzed_move_count": len(all_records),
        "important_decisive_count": len(product_records),
        "importance_distribution": dict(
            Counter(record["importance"] for record in all_records)
        ),
        "all_move_classification_distribution": _count_distribution(
            all_records,
            ("category", "confidence"),
        ),
        "product_classification_distribution": _count_distribution(
            product_records,
            ("category", "confidence"),
        ),
        "classified_coverage": classified / len(product_records)
        if product_records
        else 0.0,
        "classified_count": classified,
        "abstained_count": len(uncertain),
        "uncertain_reason_frequency": _reason_frequencies(uncertain),
        "exclusive_coverage_bottlenecks": _exclusive_bottlenecks(uncertain),
        "threshold_edge_cases": _threshold_edges(all_records),
        "manual_review_distribution": dict(
            Counter(review["manual_label"] for review in reviews)
        ),
        "manual_reviews": reviews,
        "sources": payload["sources"],
    }
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_csv(args.table, table)
    _write_csv(args.review, reviews)
    print(f"wrote {args.report}")
    print(f"wrote {args.table}")
    print(f"wrote {args.review}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
