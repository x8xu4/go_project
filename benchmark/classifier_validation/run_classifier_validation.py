"""Collect a bounded real-SGF sample for Phase 3C classifier validation.

The runner is isolated from production. It reuses the existing 64-position
benchmark artifact and analyzes three fixed ten-move windows in four additional
SGFs. Six preceding moves are included solely to preserve recent-play features.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import server
from analysis_logic import build_move_analyses, thresholds_as_dict
from benchmark.run_counterfactual_calibration import load_cached_records


VALIDATION_DIR = Path(__file__).resolve().parent
RAW_DIR = VALIDATION_DIR / "raw"
DEFAULT_OUTPUT = VALIDATION_DIR / "validation_records.json"
MAX_VISITS = 100
PV_LENGTH = 8
CONTEXT_MOVES = 6
TARGET_MOVES_PER_WINDOW = 10
REUSED_SGF = "棋譜/[朴廷桓]vs[安成浚]1765452105010001779.sgf"
SELECTED_SGFS = (
    "棋譜/[朴进率]vs[朴廷桓]1766236878010001427.sgf",
    "棋譜/[朴廷桓]vs[朴河旼]1767960653010001940.sgf",
    "棋譜/[朴廷桓]vs[芝野虎丸]1762757529010001439.sgf",
    "棋譜/[朴廷桓]vs[许皓鋐]1766559064010001206.sgf",
)


def _slug(path: str) -> str:
    return Path(path).stem.split("]")[-1].strip("vs[") or Path(path).stem


def target_windows(move_count: int) -> list[dict[str, Any]]:
    """Return deterministic opening, middle, and end target windows."""

    starts = (
        ("opening", 10),
        ("middle", max(10, move_count // 2 - 4)),
        ("end", max(10, move_count - 15)),
    )
    windows = []
    for phase, target_start in starts:
        target_end = min(
            move_count,
            target_start + TARGET_MOVES_PER_WINDOW - 1,
        )
        context_start = max(1, target_start - CONTEXT_MOVES)
        windows.append(
            {
                "phase": phase,
                "target_start": target_start,
                "target_end": target_end,
                "context_start": context_start,
                "position_start": context_start - 1,
                "position_end": target_end,
            }
        )
    return windows


def _analyze_turns(windows: list[dict[str, Any]]) -> list[int]:
    turns = {
        turn
        for window in windows
        for turn in range(
            window["position_start"],
            window["position_end"] + 1,
        )
    }
    return sorted(turns)


def _load_or_run_sgf(
    client: server.KataGoClient,
    sgf_path: str,
) -> dict[str, Any]:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    raw_path = RAW_DIR / f"{_slug(sgf_path)}.json"
    if raw_path.exists():
        payload = json.loads(raw_path.read_text(encoding="utf-8"))
        conditions = payload.get("conditions", {})
        expected = {
            "max_visits": MAX_VISITS,
            "analysis_pv_len": PV_LENGTH,
            "include_ownership": False,
            "process_configuration": "16x4",
        }
        if any(conditions.get(key) != value for key, value in expected.items()):
            raise RuntimeError(f"existing raw conditions differ: {raw_path}")
        return payload

    absolute_path = PROJECT_ROOT / sgf_path
    game, moves, komi, rules = server._parse_sgf(
        absolute_path.read_text(encoding="utf-8")
    )
    windows = target_windows(len(moves))
    turns = _analyze_turns(windows)
    responses: dict[int, dict[str, Any]] = {}
    query = {
        "id": f"classifier-validation-{_slug(sgf_path)}",
        "moves": moves,
        "analyzeTurns": turns,
        "rules": rules,
        "komi": float(komi),
        "boardXSize": game.get_size(),
        "boardYSize": game.get_size(),
        "maxVisits": MAX_VISITS,
        "analysisPVLen": PV_LENGTH,
        "includeOwnership": False,
        "reportDuringSearchEvery": server.KATAGO_HEARTBEAT_SECONDS,
        "priority": server.WHOLE_GAME_PRIORITY,
    }
    initial_stones = server.get_initial_stones_from_game(game)
    if initial_stones:
        query["initialStones"] = initial_stones

    started = time.monotonic()
    client.query_many(query, turns, responses.__setitem__)
    runtime = time.monotonic() - started
    payload = {
        "schema_version": 1,
        "sgf": sgf_path,
        "move_count": len(moves),
        "windows": windows,
        "analyze_turns": turns,
        "conditions": {
            "max_visits": MAX_VISITS,
            "analysis_pv_len": PV_LENGTH,
            "include_ownership": False,
            "process_configuration": "16x4",
            "rules": rules,
            "komi": float(komi),
        },
        "runtime_seconds": runtime,
        "responses": {str(turn): response for turn, response in responses.items()},
    }
    raw_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"completed {sgf_path}: {len(turns)} positions, {runtime:.2f}s",
        flush=True,
    )
    return payload


def _records_from_raw(payload: dict[str, Any]) -> list[dict[str, Any]]:
    sgf_path = payload["sgf"]
    game, all_moves, _, _ = server._parse_sgf(
        (PROJECT_ROOT / sgf_path).read_text(encoding="utf-8")
    )
    del game
    responses = {
        int(turn): response for turn, response in payload["responses"].items()
    }
    records: list[dict[str, Any]] = []
    for window in payload["windows"]:
        context_start = window["context_start"]
        target_end = window["target_end"]
        position_start = window["position_start"]
        local_moves = all_moves[context_start - 1 : target_end]
        local_positions = {
            global_turn - position_start: responses[global_turn]
            for global_turn in range(position_start, target_end + 1)
        }
        local_records = build_move_analyses(local_moves, local_positions)
        for record in local_records:
            global_move_number = record["move_number"] + context_start - 1
            if not (
                window["target_start"]
                <= global_move_number
                <= window["target_end"]
            ):
                continue
            record["move_number"] = global_move_number
            record["pv_base_move"] += context_start - 1
            record["validation_source"] = {
                "sgf": sgf_path,
                "phase": window["phase"],
                "reused": False,
            }
            records.append(record)
    return records


def _reused_records() -> list[dict[str, Any]]:
    records = []
    for record in load_cached_records().values():
        record = dict(record)
        record["validation_source"] = {
            "sgf": REUSED_SGF,
            "phase": "middle",
            "reused": True,
            "turn_range": [128, 191],
        }
        records.append(record)
    return records


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    client = server.KataGoClient(
        server.KATAGO_EXEC,
        server.MODEL_FILE,
        server.CONFIG_FILE,
        label="Phase 3C validation 16x4",
    )
    raw_payloads = []
    try:
        for sgf_path in SELECTED_SGFS:
            raw_payloads.append(_load_or_run_sgf(client, sgf_path))
    finally:
        client.close()

    records = _reused_records()
    for payload in raw_payloads:
        records.extend(_records_from_raw(payload))
    records.sort(
        key=lambda record: (
            record["validation_source"]["sgf"],
            record["move_number"],
        )
    )
    output = {
        "schema_version": 1,
        "conditions": {
            "max_visits": MAX_VISITS,
            "analysis_pv_len": PV_LENGTH,
            "include_ownership": False,
            "process_configuration": "16x4",
            "importance_thresholds": thresholds_as_dict(),
        },
        "sgf_count": len(SELECTED_SGFS) + 1,
        "analyzed_move_count": len(records),
        "sources": [
            {
                "sgf": REUSED_SGF,
                "source_kind": "existing_benchmark_artifact",
                "target_move_count": len(_reused_records()),
            },
            *[
                {
                    "sgf": payload["sgf"],
                    "source_kind": "phase3c_sampled_analysis",
                    "move_count": payload["move_count"],
                    "windows": payload["windows"],
                    "analyzed_position_count": len(payload["analyze_turns"]),
                    "target_move_count": sum(
                        window["target_end"] - window["target_start"] + 1
                        for window in payload["windows"]
                    ),
                    "runtime_seconds": payload["runtime_seconds"],
                }
                for payload in raw_payloads
            ],
        ],
        "records": records,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {args.output}: {len(records)} moves", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
