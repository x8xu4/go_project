"""Run the isolated two-query Phase 3B prototype for the real move 130."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import server
from counterfactual_prototype import (
    build_branch_queries,
    build_counterfactual_evidence,
    parse_branch_response,
)


DEFAULT_SGF = (
    PROJECT_ROOT
    / "棋譜"
    / "[金升宰]vs[朴廷桓]1764341261010001550.sgf"
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sgf", type=Path, default=DEFAULT_SGF)
    parser.add_argument("--move-number", type=int, default=130)
    parser.add_argument("--recommended", default="E14")
    parser.add_argument("--visits", type=int, default=100)
    args = parser.parse_args()

    sgf_content = args.sgf.read_text()
    game, all_moves, komi, rules = server._parse_sgf(sgf_content)
    move_index = args.move_number - 1
    if not 0 <= move_index < len(all_moves):
        raise ValueError("move number is outside the SGF")
    original_player, actual_move = all_moves[move_index]
    base_moves = all_moves[:move_index]
    initial_stones = server.get_initial_stones_from_game(game)
    queries = build_branch_queries(
        base_moves,
        original_player=original_player,
        recommended_move=args.recommended,
        actual_move=actual_move,
        rules=rules,
        komi=komi,
        board_size=game.get_size(),
        max_visits=args.visits,
        initial_stones=initial_stones,
        query_id_prefix=f"counterfactual-move-{args.move_number}",
    )

    client = server.KataGoClient(
        server.KATAGO_EXEC,
        server.MODEL_FILE,
        server.CONFIG_FILE,
        label="counterfactual prototype 1x16",
        override_config=(
            f"numAnalysisThreads={server.POSITION_ANALYSIS_THREADS},"
            "numSearchThreadsPerAnalysisThread="
            f"{server.POSITION_SEARCH_THREADS}"
        ),
    )
    responses = {}
    runtimes = {}
    try:
        for name in ("recommended_branch", "actual_branch"):
            started = time.monotonic()
            responses[name] = client.query(queries[name])
            runtimes[name] = time.monotonic() - started
    finally:
        client.close()

    branches = {}
    for name, first_move in (
        ("recommended_branch", args.recommended),
        ("actual_branch", actual_move),
    ):
        branches[name] = parse_branch_response(
            name,
            responses[name],
            original_player=original_player,
            first_move=first_move,
            base_move_count=len(base_moves),
            requested_visits=args.visits,
        )

    evidence = build_counterfactual_evidence(
        base_move_count=len(base_moves),
        original_player=original_player,
        recommended_move=args.recommended,
        actual_move=actual_move,
        recommended_branch=branches["recommended_branch"],
        actual_branch=branches["actual_branch"],
        board_size=game.get_size(),
        requested_visits=args.visits,
    )
    output = {
        "experiment": {
            "sgf": str(args.sgf),
            "sgf_move_count": len(all_moves),
            "move_number": args.move_number,
            "base_move_count": len(base_moves),
            "actual": [original_player, actual_move],
            "recommended": [original_player, args.recommended.upper()],
            "rules": rules,
            "komi": komi,
            "query_count": 2,
            "visits_per_query": args.visits,
            "analysis_pv_len": queries["recommended_branch"]["analysisPVLen"],
            "include_ownership": False,
            "focus_moves_used": False,
            "runtime_seconds": runtimes,
            "total_runtime_seconds": sum(runtimes.values()),
        },
        "counterfactual_evidence": evidence,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
