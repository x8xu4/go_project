"""Validate Phase 4C summaries using saved Phase 4B/3C artifacts only."""

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
from review_summary import build_review_summary
from sgf_utils import get_moves_from_sgf
from structured_explanation import build_structured_explanation


DEFAULT_RECORDS = (
    PROJECT_ROOT / "benchmark/classifier_validation/validation_records.json"
)
DEFAULT_PHASE4B_REPORT = PROJECT_ROOT / "benchmark/game_review_validation.json"
DEFAULT_LABELS = PROJECT_ROOT / "benchmark/review_summary_manual_labels.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "benchmark/review_summary_validation.json"


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _load_labels(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        item["sgf"]: {"label": item["label"], "note": item["note"]}
        for item in payload.get("reviews", [])
    }


def build_validation_report(
    records_payload: dict[str, Any],
    phase4b_payload: dict[str, Any],
    labels: dict[str, dict[str, str]],
) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for raw_record in records_payload.get("records", []):
        record = copy.deepcopy(raw_record)
        sgf_path = _mapping(record.get("validation_source")).get("sgf")
        if not isinstance(sgf_path, str):
            continue
        record["structured_explanation"] = build_structured_explanation(record)
        grouped.setdefault(sgf_path, []).append(record)

    previous_selected = {
        game["sgf"]: [item["move_number"] for item in game["selected"]]
        for game in phase4b_payload.get("games", [])
    }
    games = []
    for sgf_path in sorted(grouped):
        total_moves = len(get_moves_from_sgf(PROJECT_ROOT / sgf_path))
        review = build_game_review(grouped[sgf_path], total_moves=total_moves)
        summary = build_review_summary(review)
        selected_moves = [
            highlight["move_number"] for highlight in review["highlights"]
        ]
        unchanged = selected_moves == previous_selected.get(sgf_path)
        if not unchanged:
            raise RuntimeError(f"Phase 4B selection changed for {sgf_path}")
        largest = summary["largest_observed_changes"]
        games.append(
            {
                "sgf": sgf_path,
                "selected_highlight_count": summary["overview"][
                    "highlight_count"
                ],
                "primary_move": summary["priority"]["primary_move"],
                "largest_winrate_change_move": _mapping(
                    largest.get("winrate")
                ).get("move_number"),
                "largest_score_change_move": _mapping(
                    largest.get("score")
                ).get("move_number"),
                "phase_distribution": summary["phase_distribution"],
                "review_order": summary["review_order"],
                "auto_summary": summary["rendered"]["auto"],
                "detailed_summary": summary["rendered"]["detailed"],
                "limitations": summary["limitations"],
                "phase4b_selection_unchanged": unchanged,
                "manual_review": labels.get(
                    sgf_path,
                    {"label": "unreviewed", "note": "尚未人工檢查"},
                ),
            }
        )
    return {
        "schema_version": 1,
        "source": str(DEFAULT_RECORDS.relative_to(PROJECT_ROOT)),
        "phase4b_source": str(
            DEFAULT_PHASE4B_REPORT.relative_to(PROJECT_ROOT)
        ),
        "katago_rerun": False,
        "scope_limitation": phase4b_payload.get("scope_limitation"),
        "game_count": len(games),
        "games": games,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--records", type=Path, default=DEFAULT_RECORDS)
    parser.add_argument(
        "--phase4b-report", type=Path, default=DEFAULT_PHASE4B_REPORT
    )
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = build_validation_report(
        json.loads(args.records.read_text(encoding="utf-8")),
        json.loads(args.phase4b_report.read_text(encoding="utf-8")),
        _load_labels(args.labels),
    )
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    for game in report["games"]:
        print(
            f"{game['sgf']}: primary={game['primary_move']} "
            f"WR={game['largest_winrate_change_move']} "
            f"score={game['largest_score_change_move']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
