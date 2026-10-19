"""Run isolated counterfactual calibration cases without production integration."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import server
from analysis_logic import build_move_analyses
from counterfactual_prototype import (
    build_branch_queries,
    build_counterfactual_evidence,
    normalize_black_values,
    parse_branch_response,
)

CASES_PATH = Path(__file__).with_name("counterfactual_cases.json")
DEFAULT_OUTPUT = Path(__file__).with_name("counterfactual_calibration_100.json")
BENCHMARK_SGF = "棋譜/[朴廷桓]vs[安成浚]1765452105010001779.sgf"


def load_cached_records() -> dict[int, dict[str, Any]]:
    from benchmark.benchmark_visits import (
        BASELINE_RAW,
        load_final_responses,
        load_workload,
        move_records,
    )

    first_line = BASELINE_RAW.read_text(encoding="utf-8").splitlines()[0]
    query_id = json.loads(first_line)["id"]
    _, moves, _ = load_workload()
    responses = load_final_responses(BASELINE_RAW, query_id)
    return {
        record["move_number"]: record
        for record in move_records(moves, responses)
    }


def phase3_and_quality(record: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    evidence = record["explanation_evidence"]
    classification = record["explanation_classification"]
    actual = evidence["before"]["actual"]
    recommended = evidence["before"]["recommended"]
    root_visits = evidence["before"]["root_visits"]
    initial_wr_gap = None
    initial_score_gap = None
    if all(
        isinstance(item, (int, float))
        for item in (
            actual.get("winrate_black"),
            actual.get("score_lead_black"),
            recommended.get("winrate_black"),
            recommended.get("score_lead_black"),
        )
    ):
        actual_values = normalize_black_values(
            float(actual["winrate_black"]),
            float(actual["score_lead_black"]),
            record["player"],
        )
        recommended_values = normalize_black_values(
            float(recommended["winrate_black"]),
            float(recommended["score_lead_black"]),
            record["player"],
        )
        initial_wr_gap = (
            recommended_values["mover_winrate"]
            - actual_values["mover_winrate"]
        )
        initial_score_gap = (
            recommended_values["mover_score_lead"]
            - actual_values["mover_score_lead"]
        )
    actual_visits = actual.get("visits")
    visit_share = (
        actual_visits / root_visits
        if isinstance(actual_visits, int)
        and isinstance(root_visits, int)
        and root_visits > 0
        else None
    )
    return (
        {
            "player": record["player"],
            "actual_move": record["actual_move"],
            "recommended_move": record["best_move"],
            "category": classification["category"],
            "confidence": classification["confidence"],
            "supporting_evidence": classification["supporting_evidence"],
            "contradictions": classification["contradictions"],
            "importance": record["importance"],
            "winrate_loss": record["winrate_loss"],
            "score_loss": record["score_loss"],
        },
        {
            "actual_found": actual.get("found"),
            "actual_reliable": actual.get("reliable"),
            "actual_order": actual.get("order"),
            "actual_visits": actual_visits,
            "actual_prior": actual.get("prior"),
            "recommended_visits": recommended.get("visits"),
            "actual_visit_share": visit_share,
            "initial_winrate_gap": initial_wr_gap,
            "initial_score_gap": initial_score_gap,
            "source_root_visits": root_visits,
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--visits", type=int, default=100)
    parser.add_argument("--case-ids", default="")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    cases_payload = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    cases = cases_payload["cases"]
    requested_ids = {
        item.strip() for item in args.case_ids.split(",") if item.strip()
    }
    if requested_ids:
        cases = [case for case in cases if case["id"] in requested_ids]
        missing_ids = requested_ids.difference(case["id"] for case in cases)
        if missing_ids:
            raise ValueError(f"unknown case ids: {sorted(missing_ids)}")

    cached_records = load_cached_records()
    client = server.KataGoClient(
        server.KATAGO_EXEC,
        server.MODEL_FILE,
        server.CONFIG_FILE,
        label="counterfactual calibration 1x16",
        override_config=(
            f"numAnalysisThreads={server.POSITION_ANALYSIS_THREADS},"
            "numSearchThreadsPerAnalysisThread="
            f"{server.POSITION_SEARCH_THREADS}"
        ),
    )
    output_cases = []
    run_started = time.monotonic()
    try:
        for case_index, case in enumerate(cases, start=1):
            sgf_path = PROJECT_ROOT / case["sgf"]
            game, moves, komi, rules = server._parse_sgf(sgf_path.read_text())
            move_index = case["move_number"] - 1
            player, actual_move = moves[move_index]
            if actual_move.upper() == case["recommended_move"].upper():
                raise ValueError(f"{case['id']} actual equals recommendation")
            base_moves = moves[:move_index]
            initial_stones = server.get_initial_stones_from_game(game)
            queries = build_branch_queries(
                base_moves,
                original_player=player,
                recommended_move=case["recommended_move"],
                actual_move=actual_move,
                rules=rules,
                komi=komi,
                board_size=game.get_size(),
                max_visits=args.visits,
                initial_stones=initial_stones,
                query_id_prefix=f"cal-{args.visits}-{case['id']}",
            )

            query_count = 0
            base_response = None
            base_runtime = None
            if args.visits == 100 and case["sgf"] != BENCHMARK_SGF:
                base_query = {
                    key: value
                    for key, value in queries["actual_branch"].items()
                    if key != "moves"
                }
                base_query["id"] = f"cal-100-{case['id']}-base"
                base_query["moves"] = [list(item) for item in base_moves]
                started = time.monotonic()
                base_response = client.query(base_query)
                base_runtime = time.monotonic() - started
                query_count += 1

            responses = {}
            branch_runtimes = {}
            for name in ("recommended_branch", "actual_branch"):
                started = time.monotonic()
                responses[name] = client.query(queries[name])
                branch_runtimes[name] = time.monotonic() - started
                query_count += 1

            branches = {}
            for name, first_move in (
                ("recommended_branch", case["recommended_move"]),
                ("actual_branch", actual_move),
            ):
                branches[name] = parse_branch_response(
                    name,
                    responses[name],
                    original_player=player,
                    first_move=first_move,
                    base_move_count=len(base_moves),
                    requested_visits=args.visits,
                )
            evidence = build_counterfactual_evidence(
                base_move_count=len(base_moves),
                original_player=player,
                recommended_move=case["recommended_move"],
                actual_move=actual_move,
                recommended_branch=branches["recommended_branch"],
                actual_branch=branches["actual_branch"],
                board_size=game.get_size(),
                requested_visits=args.visits,
            )

            phase3a = None
            quality = None
            if args.visits == 100:
                if case["sgf"] == BENCHMARK_SGF:
                    record = cached_records[case["move_number"]]
                else:
                    record = build_move_analyses(
                        [[player, actual_move]],
                        {0: base_response, 1: responses["actual_branch"]},
                    )[0]
                phase3a, quality = phase3_and_quality(record)

            total_runtime = sum(branch_runtimes.values()) + (base_runtime or 0.0)
            output_cases.append(
                {
                    "case": case,
                    "phase3a": phase3a,
                    "actual_candidate_quality": quality,
                    "experiment": {
                        "visits": args.visits,
                        "query_count": query_count,
                        "base_query_runtime_seconds": base_runtime,
                        "branch_runtime_seconds": branch_runtimes,
                        "total_runtime_seconds": total_runtime,
                        "warm_process": case_index > 1 or base_response is not None,
                        "include_ownership": False,
                        "focus_moves_used": False,
                    },
                    "counterfactual_evidence": evidence,
                }
            )
            print(
                f"[{case_index}/{len(cases)}] {case['id']} "
                f"queries={query_count} time={total_runtime:.2f}s",
                flush=True,
            )
    finally:
        client.close()

    payload = {
        "schema_version": 1,
        "visits": args.visits,
        "process_configuration": "1x16",
        "case_count": len(output_cases),
        "total_query_count": sum(
            item["experiment"]["query_count"] for item in output_cases
        ),
        "total_case_runtime_seconds": sum(
            item["experiment"]["total_runtime_seconds"]
            for item in output_cases
        ),
        "wall_clock_seconds": time.monotonic() - run_started,
        "cases": output_cases,
    }
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
