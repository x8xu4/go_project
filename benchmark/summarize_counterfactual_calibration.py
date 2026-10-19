"""Summarize isolated Phase 3B calibration and stability artifacts."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from counterfactual_prototype import (
    aggregate_stability_runs,
    calibration_table_row,
)


DEFAULT_CALIBRATION = Path(__file__).with_name(
    "counterfactual_calibration_100.json"
)
DEFAULT_STABILITY = Path(__file__).with_name(
    "counterfactual_stability_200.json"
)
DEFAULT_REPORT = Path(__file__).with_name(
    "counterfactual_calibration_report.json"
)
DEFAULT_TABLE = Path(__file__).with_name(
    "counterfactual_calibration_table.csv"
)


def _mean(values: list[float]) -> float | None:
    return statistics.mean(values) if values else None


def _quality_summary(cases: list[dict[str, Any]]) -> dict[str, Any]:
    quality = [case["actual_candidate_quality"] for case in cases]
    found = [item for item in quality if item.get("actual_found") is True]
    reliable = [item for item in quality if item.get("actual_reliable") is True]

    def values(key: str) -> list[float]:
        return [
            float(item[key])
            for item in quality
            if isinstance(item.get(key), (int, float))
        ]

    return {
        "case_count": len(quality),
        "actual_found_count": len(found),
        "actual_reliable_count": len(reliable),
        "actual_orders": values("actual_order"),
        "actual_visits": values("actual_visits"),
        "actual_visit_shares": values("actual_visit_share"),
        "initial_winrate_gaps": values("initial_winrate_gap"),
        "initial_score_gaps": values("initial_score_gap"),
    }


def _feature_counts(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for label in sorted({row["expected_case_type"] for row in rows}):
        subset = [row for row in rows if row["expected_case_type"] == label]
        result[label] = {
            "case_count": len(subset),
            "actual_reply_near_recommendation_count": sum(
                row["actual_reply_near_recommendation"] is True
                for row in subset
            ),
            "positive_first_winrate_gap_count": sum(
                isinstance(row["first_move_gap_winrate"], (int, float))
                and row["first_move_gap_winrate"] > 0
                for row in subset
            ),
            "positive_post_winrate_gap_count": sum(
                isinstance(row["post_reply_gap_winrate"], (int, float))
                and row["post_reply_gap_winrate"] > 0
                for row in subset
            ),
            "positive_gap_change_winrate_count": sum(
                isinstance(row["gap_change_winrate"], (int, float))
                and row["gap_change_winrate"] > 0
                for row in subset
            ),
        }
    return result


def _stability_summary(
    stability_by_case: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    summaries = list(stability_by_case.values())

    def count(branch: str, key: str) -> int:
        return sum(item[branch].get(key) is True for item in summaries)

    return {
        "case_count": len(summaries),
        "recommended_reply_exact_stable_count": count(
            "recommended_reply", "exact_move_stable"
        ),
        "recommended_reply_region_stable_count": count(
            "recommended_reply", "region_stable"
        ),
        "actual_reply_exact_stable_count": count(
            "actual_reply", "exact_move_stable"
        ),
        "actual_reply_region_stable_count": count(
            "actual_reply", "region_stable"
        ),
    }


def _cost_summary(calibration: dict[str, Any]) -> dict[str, Any]:
    branch_times = [
        float(runtime)
        for case in calibration["cases"]
        for runtime in case["experiment"]["branch_runtime_seconds"].values()
    ]
    average_branch = statistics.mean(branch_times)
    average_trigger = average_branch * 2
    return {
        "warm_100_visit_branch_seconds_mean": average_branch,
        "warm_100_visit_branch_seconds_median": statistics.median(branch_times),
        "warm_100_visit_branch_seconds_min": min(branch_times),
        "warm_100_visit_branch_seconds_max": max(branch_times),
        "estimated_seconds_per_triggered_move": average_trigger,
        "estimated_extra_seconds": {
            str(count): average_trigger * count for count in (3, 5, 8)
        },
        "query_count_per_triggered_move": 2,
    }


def _csv_row(row: dict[str, Any]) -> dict[str, Any]:
    result = {key: value for key, value in row.items() if key != "stability"}
    stability = row.get("stability")
    if not isinstance(stability, dict):
        result.update(
            {
                "stability_runs": None,
                "recommended_reply_exact_stable": None,
                "recommended_reply_region_stable": None,
                "actual_reply_exact_stable": None,
                "actual_reply_region_stable": None,
            }
        )
        return result
    result.update(
        {
            "stability_runs": stability["usable_run_count"],
            "recommended_reply_exact_stable": stability[
                "recommended_reply"
            ]["exact_move_stable"],
            "recommended_reply_region_stable": stability[
                "recommended_reply"
            ]["region_stable"],
            "actual_reply_exact_stable": stability["actual_reply"][
                "exact_move_stable"
            ],
            "actual_reply_region_stable": stability["actual_reply"][
                "region_stable"
            ],
        }
    )
    for metric, summary in stability["metrics"].items():
        result[f"{metric}_range"] = summary["range"]
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--calibration", type=Path, default=DEFAULT_CALIBRATION)
    parser.add_argument("--stability", type=Path, default=DEFAULT_STABILITY)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--table", type=Path, default=DEFAULT_TABLE)
    args = parser.parse_args()

    calibration = json.loads(args.calibration.read_text(encoding="utf-8"))
    stability = json.loads(args.stability.read_text(encoding="utf-8"))
    calibration_by_id = {
        item["case"]["id"]: item for item in calibration["cases"]
    }
    stability_by_id = {
        item["case"]["id"]: item for item in stability["cases"]
    }

    aggregate_by_id = {
        case_id: aggregate_stability_runs(
            [
                calibration_by_id[case_id]["counterfactual_evidence"],
                result["counterfactual_evidence"],
            ]
        )
        for case_id, result in stability_by_id.items()
    }
    rows = [
        calibration_table_row(
            item,
            aggregate_by_id.get(item["case"]["id"]),
        )
        for item in calibration["cases"]
    ]
    report = {
        "schema_version": 1,
        "case_counts": dict(
            Counter(row["expected_case_type"] for row in rows)
        ),
        "calibration_100": {
            "case_count": calibration["case_count"],
            "query_count": calibration["total_query_count"],
            "case_runtime_seconds": calibration[
                "total_case_runtime_seconds"
            ],
            "wall_clock_seconds": calibration["wall_clock_seconds"],
        },
        "stability_200": {
            "method": "one 200-visit rerun after the 100-visit screen",
            "case_count": stability["case_count"],
            "query_count": stability["total_query_count"],
            "case_runtime_seconds": stability[
                "total_case_runtime_seconds"
            ],
            "wall_clock_seconds": stability["wall_clock_seconds"],
            "selected_case_ids": list(stability_by_id),
        },
        "quality_distribution": _quality_summary(calibration["cases"]),
        "feature_counts_by_label": _feature_counts(rows),
        "stability_summary": _stability_summary(aggregate_by_id),
        "stability_by_case": aggregate_by_id,
        "production_cost_estimate": _cost_summary(calibration),
        "table": rows,
    }
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    csv_rows = [_csv_row(row) for row in rows]
    fieldnames: list[str] = []
    for row in csv_rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with args.table.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(csv_rows)
    print(f"wrote {args.report}")
    print(f"wrote {args.table}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
