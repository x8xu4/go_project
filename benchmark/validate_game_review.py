"""Validate Phase 4B selection using saved Phase 3C artifacts only.

This script never starts KataGo. Four source games contain sampled
opening/middle/end windows; the reused long-game artifact contains turns
128–190. Results therefore validate selector behavior over real analyzed
positions, not full-game coverage for those historical artifacts.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from review_selection import build_game_review
from sgf_utils import get_moves_from_sgf
from structured_explanation import build_structured_explanation


DEFAULT_RECORDS = (
    PROJECT_ROOT / "benchmark/classifier_validation/validation_records.json"
)
DEFAULT_LABELS = PROJECT_ROOT / "benchmark/game_review_manual_labels.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "benchmark/game_review_validation.json"


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _load_labels(path: Path) -> dict[tuple[str, int], dict[str, str]]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        (item["sgf"], item["move_number"]): {
            "label": item["label"],
            "note": item["note"],
        }
        for item in payload.get("reviews", [])
    }


def _selected_row(
    sgf_path: str,
    highlight: dict[str, Any],
    labels: dict[tuple[str, int], dict[str, str]],
) -> dict[str, Any]:
    severity = _mapping(_mapping(highlight.get("selection")).get("severity_basis"))
    manual = labels.get((sgf_path, highlight["move_number"]))
    return {
        "move_number": highlight["move_number"],
        "importance": highlight["importance"],
        "observed_winrate_loss": severity.get("observed_winrate_loss"),
        "observed_score_loss": severity.get("observed_score_loss"),
        "recommendation_available": highlight["recommendation_available"],
        "variation_available": highlight["variation_available"],
        "selection_reasons": highlight["selection"]["reasons"],
        "manual_review": manual or {
            "label": "unreviewed",
            "note": "尚未人工檢查",
        },
    }


def build_validation_report(
    records_payload: dict[str, Any],
    labels: dict[tuple[str, int], dict[str, str]],
) -> dict[str, Any]:
    sources = {
        source["sgf"]: source for source in records_payload.get("sources", [])
    }
    grouped: dict[str, list[dict[str, Any]]] = {}
    for raw_record in records_payload.get("records", []):
        record = copy.deepcopy(raw_record)
        sgf_path = _mapping(record.get("validation_source")).get("sgf")
        if not isinstance(sgf_path, str):
            continue
        record["structured_explanation"] = build_structured_explanation(record)
        grouped.setdefault(sgf_path, []).append(record)

    games = []
    for sgf_path in sorted(grouped):
        records = grouped[sgf_path]
        total_moves = len(get_moves_from_sgf(PROJECT_ROOT / sgf_path))
        review = build_game_review(records, total_moves=total_moves)
        source = sources.get(sgf_path, {})
        games.append(
            {
                "sgf": sgf_path,
                "source_total_moves": total_moves,
                "analyzed_artifact_moves": len(records),
                "artifact_scope": source.get("source_kind"),
                "important_count": review["summary"]["important_count"],
                "decisive_count": review["summary"]["decisive_count"],
                "candidate_count": review["summary"]["candidate_count"],
                "selected_count": review["summary"]["selected_count"],
                "suppressed_count": review["summary"]["suppressed_count"],
                "selected": [
                    _selected_row(sgf_path, highlight, labels)
                    for highlight in review["highlights"]
                ],
                "suppressed": review["suppressed"],
            }
        )
    return {
        "schema_version": 1,
        "source": str(DEFAULT_RECORDS.relative_to(PROJECT_ROOT)),
        "katago_rerun": False,
        "scope_limitation": (
            "Selection uses saved real-position artifacts. Four games contain "
            "three sampled windows and one long game contains turns 128–190; "
            "these are not newly generated complete-game analyses."
        ),
        "game_count": len(games),
        "games": games,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--records", type=Path, default=DEFAULT_RECORDS)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    records_payload = json.loads(args.records.read_text(encoding="utf-8"))
    report = build_validation_report(
        records_payload,
        _load_labels(args.labels),
    )
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    for game in report["games"]:
        moves = [item["move_number"] for item in game["selected"]]
        print(
            f"{game['sgf']}: candidates={game['candidate_count']} "
            f"selected={moves} suppressed={game['suppressed_count']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
