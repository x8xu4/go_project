#!/usr/bin/env python3
"""Compare KataGo 100/75/50-visit batch analysis without changing app files."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import queue
import re
import shutil
import statistics
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from sgfmill import sgf


ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_DIR = Path(__file__).resolve().parent
CONFIG_SOURCE = ROOT / "analysis.cfg"
MODEL = ROOT / "model.bin.gz"
SGF_PATH = ROOT / "棋譜" / "[朴廷桓]vs[安成浚]1765452105010001779.sgf"
KATAGO = Path(shutil.which("katago") or "")
BASELINE_RESULTS = BENCHMARK_DIR / "results.json"
BASELINE_RAW = BENCHMARK_DIR / "raw" / "C_16x4.stdout.jsonl"
OUTPUT_PATH = BENCHMARK_DIR / "visits_results.json"

START_TURN = 128
END_TURN = 191
PV_LENGTH = 8
ANALYSIS_THREADS = 16
SEARCH_THREADS = 4
VISITS_TO_RUN = (75, 50)
IDLE_TIMEOUT_SECONDS = 90.0
STARTUP_TIMEOUT_SECONDS = 120.0
COOLDOWN_SECONDS = 10.0

KEY_PROJECT_FILES = (
    CONFIG_SOURCE,
    ROOT / "server.py",
    ROOT / "analysis_logic.py",
    ROOT / "flutter_application_1" / "lib" / "main.dart",
    MODEL,
    SGF_PATH,
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def key_hashes() -> dict[str, str]:
    return {str(path.relative_to(ROOT)): sha256(path) for path in KEY_PROJECT_FILES}


def git_status() -> str:
    result = subprocess.run(
        ["git", "status", "--short"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def parse_komi_and_rules(game: sgf.Sgf_game) -> tuple[float, str]:
    raw_komi = game.root.get("KM") if game.root.has_property("KM") else 75
    if raw_komi > 150:
        komi = raw_komi / 100
    elif raw_komi > 15:
        komi = raw_komi / 10
    else:
        komi = float(raw_komi)
    if komi > 150.0 or komi < -150.0:
        komi = 7.5
    komi = round(komi * 2) / 2.0
    return komi, "chinese" if komi == 7.5 else "korean"


def load_workload() -> tuple[sgf.Sgf_game, list[list[str]], list[list[str]]]:
    sys.path.insert(0, str(ROOT))
    from sgf_utils import get_initial_stones_from_game, get_moves_from_game

    game = sgf.Sgf_game.from_bytes(SGF_PATH.read_bytes())
    moves = get_moves_from_game(game)
    initial_stones = get_initial_stones_from_game(game)
    if len(moves) != 336:
        raise RuntimeError(f"Expected 336 moves, found {len(moves)}")
    return game, moves, initial_stones


def render_config() -> Path:
    source = CONFIG_SOURCE.read_text(encoding="utf-8")
    log_dir = (BENCHMARK_DIR / "katago_logs" / "visits_16x4").resolve()
    log_dir.mkdir(parents=True, exist_ok=True)
    replacements = {
        r"(?m)^logDir\s*=.*$": f"logDir = {log_dir}",
        r"(?m)^numAnalysisThreads\s*=.*$": (
            f"numAnalysisThreads = {ANALYSIS_THREADS}"
        ),
        r"(?m)^numSearchThreadsPerAnalysisThread\s*=.*$": (
            f"numSearchThreadsPerAnalysisThread = {SEARCH_THREADS}"
        ),
    }
    generated = source
    for pattern, replacement in replacements.items():
        generated, count = re.subn(pattern, replacement, generated, count=1)
        if count != 1:
            raise RuntimeError(f"Could not replace config setting: {pattern}")
    config_dir = BENCHMARK_DIR / "visits_configs"
    config_dir.mkdir(parents=True, exist_ok=True)
    destination = config_dir / "config_16x4.cfg"
    destination.write_text(generated, encoding="utf-8")
    return destination


def build_query(
    visits: int,
    game: sgf.Sgf_game,
    moves: list[list[str]],
    initial_stones: list[list[str]],
) -> dict[str, Any]:
    komi, rules = parse_komi_and_rules(game)
    query: dict[str, Any] = {
        "id": f"benchmark-visits-{visits}",
        "moves": moves,
        "analyzeTurns": list(range(START_TURN, END_TURN + 1)),
        "rules": rules,
        "komi": float(komi),
        "boardXSize": 19,
        "boardYSize": 19,
        "maxVisits": visits,
        "analysisPVLen": PV_LENGTH,
        "includeOwnership": False,
        "reportDuringSearchEvery": 5.0,
        "priority": 0,
    }
    if initial_stones:
        query["initialStones"] = initial_stones
    return query


def start_stderr_reader(process: subprocess.Popen, log_path: Path):
    ready = threading.Event()
    tail: list[str] = []

    def read_stderr() -> None:
        assert process.stderr is not None
        with log_path.open("w", encoding="utf-8") as log:
            for line in process.stderr:
                log.write(line)
                log.flush()
                message = line.rstrip()
                if message:
                    tail.append(message)
                    del tail[:-30]
                if "Started, ready to begin handling requests" in line:
                    ready.set()

    thread = threading.Thread(target=read_stderr, daemon=True)
    thread.start()
    return ready, tail, thread


def start_stdout_reader(process: subprocess.Popen):
    lines: queue.Queue[str | None] = queue.Queue()

    def read_stdout() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            lines.put(line)
        lines.put(None)

    thread = threading.Thread(target=read_stdout, daemon=True)
    thread.start()
    return lines, thread


def stop_owned_process(process: subprocess.Popen) -> tuple[bool, int | None, str]:
    method = "stdin_eof"
    if process.stdin and not process.stdin.closed:
        process.stdin.close()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        method = "sigterm"
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            method = "sigkill"
            process.kill()
            process.wait(timeout=5)
    return process.poll() is not None, process.returncode, method


def run_one(
    visits: int,
    config_path: Path,
    game: sgf.Sgf_game,
    moves: list[list[str]],
    initial_stones: list[list[str]],
) -> tuple[dict[str, Any], dict[int, dict[str, Any]]]:
    raw_dir = BENCHMARK_DIR / "visits_raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = raw_dir / f"visits_{visits}.stdout.jsonl"
    stderr_path = raw_dir / f"visits_{visits}.stderr.log"
    process = subprocess.Popen(
        [
            str(KATAGO),
            "analysis",
            "-model",
            str(MODEL),
            "-config",
            str(config_path),
        ],
        cwd=ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    ready, stderr_tail, stderr_thread = start_stderr_reader(process, stderr_path)
    stdout_lines, stdout_thread = start_stdout_reader(process)
    startup_started = time.monotonic()
    while not ready.wait(timeout=0.25):
        if process.poll() is not None:
            raise RuntimeError(
                f"KataGo exited during startup with {process.returncode}: "
                + " | ".join(stderr_tail[-5:])
            )
        if time.monotonic() - startup_started > STARTUP_TIMEOUT_SECONDS:
            stop_owned_process(process)
            raise RuntimeError("KataGo startup timed out")

    query = build_query(visits, game, moves, initial_stones)
    expected_turns = set(query["analyzeTurns"])
    responses: dict[int, dict[str, Any]] = {}
    actual_visits: list[int] = []
    malformed = 0
    warnings = 0
    during_search = 0
    errors: list[str] = []
    timed_out = False
    last_activity = time.monotonic()
    started = time.monotonic()
    assert process.stdin is not None
    process.stdin.write(json.dumps(query, separators=(",", ":")) + "\n")
    process.stdin.flush()

    with stdout_path.open("w", encoding="utf-8") as raw_stdout:
        while set(responses) != expected_turns:
            if process.poll() is not None:
                errors.append(f"KataGo process exited early with code {process.returncode}")
                break
            try:
                line = stdout_lines.get(timeout=1.0)
            except queue.Empty:
                if time.monotonic() - last_activity > IDLE_TIMEOUT_SECONDS:
                    timed_out = True
                    errors.append(
                        f"No KataGo output for {IDLE_TIMEOUT_SECONDS:.0f} seconds"
                    )
                    break
                continue
            if line is None:
                errors.append(f"KataGo stdout EOF with code {process.poll()}")
                break
            last_activity = time.monotonic()
            raw_stdout.write(line)
            raw_stdout.flush()
            try:
                response = json.loads(line)
            except json.JSONDecodeError:
                malformed += 1
                continue
            if "warning" in response:
                warnings += 1
                continue
            if response.get("id") != query["id"]:
                malformed += 1
                continue
            if response.get("isDuringSearch", False):
                during_search += 1
                continue
            if "error" in response:
                errors.append(str(response["error"]))
                break
            turn = response.get("turnNumber")
            if not isinstance(turn, int) or turn not in expected_turns:
                malformed += 1
                continue
            if response.get("noResults") or turn in responses:
                malformed += 1
                continue
            root = response.get("rootInfo")
            root_visits = root.get("visits") if isinstance(root, dict) else None
            if not isinstance(root_visits, int):
                malformed += 1
                continue
            responses[turn] = response
            actual_visits.append(root_visits)
            print(
                f"[visits={visits}] {len(responses):2d}/{len(expected_turns)} "
                f"turn={turn} actual={root_visits}",
                flush=True,
            )

    elapsed = time.monotonic() - started
    process_ended, return_code, stop_method = stop_owned_process(process)
    stderr_thread.join(timeout=2)
    stdout_thread.join(timeout=2)
    completed = len(responses)
    all_visits_available = len(actual_visits) == completed == len(expected_turns)
    total_visits = sum(actual_visits) if all_visits_available else None
    result = {
        "maxVisits": visits,
        "numAnalysisThreads": ANALYSIS_THREADS,
        "numSearchThreadsPerAnalysisThread": SEARCH_THREADS,
        "requested_positions": len(expected_turns),
        "completed_positions": completed,
        "wall_clock_seconds": elapsed,
        "seconds_per_position": elapsed / completed if completed else None,
        "positions_per_second": completed / elapsed if elapsed else None,
        "total_actual_visits": total_visits,
        "visits_per_second": (
            total_visits / elapsed if total_visits is not None and elapsed else None
        ),
        "actual_visits_min": min(actual_visits) if actual_visits else None,
        "actual_visits_max": max(actual_visits) if actual_visits else None,
        "actual_visits_mean": statistics.mean(actual_visits) if actual_visits else None,
        "timeout": timed_out,
        "katago_errors": errors,
        "malformed_responses": malformed,
        "warnings": warnings,
        "during_search_responses": during_search,
        "process_crash": return_code not in (0, None),
        "process_ended": process_ended,
        "process_return_code": return_code,
        "process_stop_method": stop_method,
        "success": (
            completed == len(expected_turns)
            and not timed_out
            and not errors
            and malformed == 0
            and process_ended
            and return_code == 0
        ),
        "stdout_log": str(stdout_path.relative_to(ROOT)),
        "stderr_log": str(stderr_path.relative_to(ROOT)),
    }
    return result, responses


def load_final_responses(
    path: Path, expected_id: str
) -> dict[int, dict[str, Any]]:
    responses: dict[int, dict[str, Any]] = {}
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            try:
                response = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"Malformed baseline line {line_number}: {exc}") from exc
            if response.get("id") != expected_id or response.get("isDuringSearch", False):
                continue
            if "warning" in response:
                continue
            turn = response.get("turnNumber")
            if isinstance(turn, int) and START_TURN <= turn <= END_TURN:
                if turn in responses:
                    raise RuntimeError(f"Duplicate final baseline turn {turn}")
                responses[turn] = response
    expected = set(range(START_TURN, END_TURN + 1))
    if set(responses) != expected:
        missing = sorted(expected.difference(responses))
        raise RuntimeError(f"Baseline is incomplete; missing turns: {missing}")
    return responses


def load_baseline_performance() -> dict[str, Any]:
    payload = json.loads(BASELINE_RESULTS.read_text(encoding="utf-8"))
    for result in payload.get("results", []):
        if result.get("configuration") == "C_16x4":
            expected = {
                "maxVisits": 100,
                "numAnalysisThreads": ANALYSIS_THREADS,
                "numSearchThreadsPerAnalysisThread": SEARCH_THREADS,
                "start_turn": START_TURN,
                "end_turn": END_TURN,
                "completed_positions": END_TURN - START_TURN + 1,
            }
            mismatches = {
                key: (result.get(key), value)
                for key, value in expected.items()
                if result.get(key) != value
            }
            if mismatches or not result.get("success"):
                raise RuntimeError(f"Existing baseline conditions differ: {mismatches}")
            return dict(result)
    raise RuntimeError("C_16x4 baseline result was not found")


def position_facts(responses: dict[int, dict[str, Any]]) -> dict[int, dict[str, Any]]:
    facts: dict[int, dict[str, Any]] = {}
    for turn, response in sorted(responses.items()):
        root = response.get("rootInfo")
        move_infos = response.get("moveInfos")
        if not isinstance(root, dict) or not isinstance(move_infos, list):
            raise RuntimeError(f"Turn {turn} lacks rootInfo or moveInfos")
        best = move_infos[0] if move_infos and isinstance(move_infos[0], dict) else {}
        pv = best.get("pv")
        facts[turn] = {
            "turn": turn,
            "actual_visits": int(root["visits"]),
            "winrate": float(root["winrate"]),
            "scoreLead": float(root["scoreLead"]),
            "top_recommendation": best.get("move"),
            "pv": [str(value).upper() for value in pv] if isinstance(pv, list) else [],
        }
    return facts


def move_records(
    moves: list[list[str]], responses: dict[int, dict[str, Any]]
) -> list[dict[str, Any]]:
    from analysis_logic import build_move_analyses

    local_moves = moves[START_TURN:END_TURN]
    local_positions = {
        turn - START_TURN: response for turn, response in responses.items()
    }
    records = build_move_analyses(local_moves, local_positions)
    for record in records:
        record["move_number"] += START_TURN
        record["pv_base_move"] += START_TURN
    return records


def stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {"mean": math.nan, "median": math.nan, "max": math.nan}
    return {
        "mean": statistics.mean(values),
        "median": statistics.median(values),
        "max": max(values),
    }


def sign(value: float, epsilon: float = 1e-12) -> int:
    if value > epsilon:
        return 1
    if value < -epsilon:
        return -1
    return 0


def common_prefix_length(left: list[str], right: list[str]) -> int:
    count = 0
    for lhs, rhs in zip(left, right):
        if lhs != rhs:
            break
        count += 1
    return count


def compare_quality(
    baseline_facts: dict[int, dict[str, Any]],
    candidate_facts: dict[int, dict[str, Any]],
    baseline_moves: list[dict[str, Any]],
    candidate_moves: list[dict[str, Any]],
) -> dict[str, Any]:
    turns = sorted(baseline_facts)
    wr_details = [
        {
            "turn": turn,
            "baseline": baseline_facts[turn]["winrate"],
            "candidate": candidate_facts[turn]["winrate"],
            "absolute_difference": abs(
                candidate_facts[turn]["winrate"] - baseline_facts[turn]["winrate"]
            ),
        }
        for turn in turns
    ]
    score_details = [
        {
            "turn": turn,
            "baseline": baseline_facts[turn]["scoreLead"],
            "candidate": candidate_facts[turn]["scoreLead"],
            "absolute_difference": abs(
                candidate_facts[turn]["scoreLead"]
                - baseline_facts[turn]["scoreLead"]
            ),
        }
        for turn in turns
    ]

    swing_details: list[dict[str, Any]] = []
    for move_number in range(START_TURN + 1, END_TURN + 1):
        previous = move_number - 1
        baseline_wr = (
            baseline_facts[move_number]["winrate"]
            - baseline_facts[previous]["winrate"]
        )
        candidate_wr = (
            candidate_facts[move_number]["winrate"]
            - candidate_facts[previous]["winrate"]
        )
        baseline_score = (
            baseline_facts[move_number]["scoreLead"]
            - baseline_facts[previous]["scoreLead"]
        )
        candidate_score = (
            candidate_facts[move_number]["scoreLead"]
            - candidate_facts[previous]["scoreLead"]
        )
        swing_details.append(
            {
                "move_number": move_number,
                "baseline_winrate_swing": baseline_wr,
                "candidate_winrate_swing": candidate_wr,
                "winrate_swing_absolute_difference": abs(candidate_wr - baseline_wr),
                "baseline_score_swing": baseline_score,
                "candidate_score_swing": candidate_score,
                "score_swing_absolute_difference": abs(
                    candidate_score - baseline_score
                ),
                "winrate_direction_same": sign(candidate_wr) == sign(baseline_wr),
                "score_direction_same": sign(candidate_score) == sign(baseline_score),
            }
        )

    important_levels = {"important", "decisive"}
    baseline_important = {
        int(record["move_number"])
        for record in baseline_moves
        if record["importance"] in important_levels
    }
    candidate_important = {
        int(record["move_number"])
        for record in candidate_moves
        if record["importance"] in important_levels
    }
    retained = baseline_important & candidate_important
    union = baseline_important | candidate_important

    def top_score_swings(records: list[dict[str, Any]]) -> list[int]:
        ranked = sorted(
            records,
            key=lambda record: (
                abs(float(record["black_score_after"]) - float(record["black_score_before"])),
                -int(record["move_number"]),
            ),
            reverse=True,
        )
        return [int(record["move_number"]) for record in ranked[:10]]

    baseline_top10 = top_score_swings(baseline_moves)
    candidate_top10 = top_score_swings(candidate_moves)
    top10_overlap = set(baseline_top10) & set(candidate_top10)

    baseline_by_move = {
        int(record["move_number"]): record for record in baseline_moves
    }
    candidate_by_move = {
        int(record["move_number"]): record for record in candidate_moves
    }
    reliable_important = sorted(
        move
        for move in baseline_important
        if baseline_by_move[move].get("pv_reliable")
    )
    recommendation_details = []
    for move in reliable_important:
        baseline_record = baseline_by_move[move]
        candidate_record = candidate_by_move[move]
        baseline_pv = list(baseline_record.get("best_pv") or [])
        candidate_pv = list(candidate_record.get("best_pv") or [])
        recommendation_details.append(
            {
                "move_number": move,
                "baseline_top": baseline_record.get("best_move"),
                "candidate_top": candidate_record.get("best_move"),
                "top_same": baseline_record.get("best_move")
                == candidate_record.get("best_move"),
                "pv_first_same": bool(baseline_pv)
                and bool(candidate_pv)
                and baseline_pv[0] == candidate_pv[0],
                "pv_common_prefix_length": common_prefix_length(
                    baseline_pv, candidate_pv
                ),
                "pv_first_three_same": len(baseline_pv) >= 3
                and len(candidate_pv) >= 3
                and baseline_pv[:3] == candidate_pv[:3],
                "baseline_pv": baseline_pv,
                "candidate_pv": candidate_pv,
            }
        )

    recommendation_count = len(recommendation_details)
    return {
        "winrate_absolute_difference": {
            **stats([item["absolute_difference"] for item in wr_details]),
            "largest": sorted(
                wr_details, key=lambda item: item["absolute_difference"], reverse=True
            )[:5],
        },
        "scoreLead_absolute_difference": {
            **stats([item["absolute_difference"] for item in score_details]),
            "largest": sorted(
                score_details,
                key=lambda item: item["absolute_difference"],
                reverse=True,
            )[:5],
        },
        "swing_difference": {
            "winrate": stats(
                [item["winrate_swing_absolute_difference"] for item in swing_details]
            ),
            "scoreLead": stats(
                [item["score_swing_absolute_difference"] for item in swing_details]
            ),
            "winrate_direction_agreement": statistics.mean(
                [float(item["winrate_direction_same"]) for item in swing_details]
            ),
            "score_direction_agreement": statistics.mean(
                [float(item["score_direction_same"]) for item in swing_details]
            ),
            "largest_winrate": sorted(
                swing_details,
                key=lambda item: item["winrate_swing_absolute_difference"],
                reverse=True,
            )[:5],
            "largest_scoreLead": sorted(
                swing_details,
                key=lambda item: item["score_swing_absolute_difference"],
                reverse=True,
            )[:5],
        },
        "formal_important_move_overlap": {
            "baseline": sorted(baseline_important),
            "candidate": sorted(candidate_important),
            "retained": sorted(retained),
            "missed": sorted(baseline_important - candidate_important),
            "added": sorted(candidate_important - baseline_important),
            "recall": len(retained) / len(baseline_important)
            if baseline_important
            else 1.0,
            "precision": len(retained) / len(candidate_important)
            if candidate_important
            else 1.0,
            "jaccard": len(retained) / len(union) if union else 1.0,
        },
        "top10_absolute_score_swing": {
            "baseline": baseline_top10,
            "candidate": candidate_top10,
            "overlap": sorted(top10_overlap),
            "missing_from_candidate": sorted(
                set(baseline_top10) - set(candidate_top10)
            ),
            "candidate_only": sorted(set(candidate_top10) - set(baseline_top10)),
            "overlap_count": len(top10_overlap),
            "overlap_ratio": len(top10_overlap) / 10,
        },
        "recommendation_stability_on_baseline_reliable_important_moves": {
            "moves": reliable_important,
            "sample_count": recommendation_count,
            "top_recommendation_same_count": sum(
                int(item["top_same"]) for item in recommendation_details
            ),
            "top_recommendation_same_ratio": (
                statistics.mean(
                    [float(item["top_same"]) for item in recommendation_details]
                )
                if recommendation_details
                else None
            ),
            "pv_first_same_ratio": (
                statistics.mean(
                    [float(item["pv_first_same"]) for item in recommendation_details]
                )
                if recommendation_details
                else None
            ),
            "pv_first_three_same_ratio": (
                statistics.mean(
                    [float(item["pv_first_three_same"]) for item in recommendation_details]
                )
                if recommendation_details
                else None
            ),
            "mean_common_prefix_length": (
                statistics.mean(
                    [item["pv_common_prefix_length"] for item in recommendation_details]
                )
                if recommendation_details
                else None
            ),
            "details": recommendation_details,
        },
    }


def compact_move_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keys = (
        "move_number",
        "player",
        "actual_move",
        "best_move",
        "best_pv",
        "pv_reliable",
        "winrate_loss",
        "score_loss",
        "observed_winrate_loss",
        "observed_score_loss",
        "search_winrate_loss",
        "search_score_loss",
        "importance",
        "actual_move_searched",
        "search_comparison_reliable",
    )
    return [{key: record.get(key) for key in keys} for record in records]


def write_output(payload: dict[str, Any]) -> None:
    OUTPUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--visits",
        nargs="*",
        type=int,
        default=list(VISITS_TO_RUN),
        choices=list(VISITS_TO_RUN),
    )
    args = parser.parse_args()
    if not KATAGO.is_file():
        raise RuntimeError("katago executable was not found")
    for path in (CONFIG_SOURCE, MODEL, SGF_PATH, BASELINE_RESULTS, BASELINE_RAW):
        if not path.is_file():
            raise RuntimeError(f"Required file not found: {path}")

    before_hashes = key_hashes()
    game, moves, initial_stones = load_workload()
    config_path = render_config()
    baseline_responses = load_final_responses(BASELINE_RAW, "benchmark-C_16x4")
    baseline_performance = load_baseline_performance()
    baseline_facts = position_facts(baseline_responses)
    baseline_move_records = move_records(moves, baseline_responses)

    from analysis_logic import thresholds_as_dict

    payload: dict[str, Any] = {
        "benchmark_started_at": datetime.now().astimezone().isoformat(),
        "host": {
            "platform": os.uname().sysname,
            "machine": os.uname().machine,
            "katago_executable": str(KATAGO),
            "katago_model": str(MODEL.relative_to(ROOT)),
            "katago_model_sha256": sha256(MODEL),
            "source_config_sha256": sha256(CONFIG_SOURCE),
        },
        "workload": {
            "sgf": str(SGF_PATH.relative_to(ROOT)),
            "sgf_sha256": sha256(SGF_PATH),
            "sgf_total_moves": len(moves),
            "start_turn": START_TURN,
            "end_turn": END_TURN,
            "positions": END_TURN - START_TURN + 1,
            "analyzed_moves_for_swing": [START_TURN + 1, END_TURN],
            "analysisPVLen": PV_LENGTH,
            "includeOwnership": False,
            "rules": parse_komi_and_rules(game)[1],
            "komi": parse_komi_and_rules(game)[0],
            "full_move_list_supplied": True,
            "numAnalysisThreads": ANALYSIS_THREADS,
            "numSearchThreadsPerAnalysisThread": SEARCH_THREADS,
        },
        "formal_importance_thresholds": thresholds_as_dict(),
        "baseline_reused": {
            "maxVisits": 100,
            "raw": str(BASELINE_RAW.relative_to(ROOT)),
            "result": str(BASELINE_RESULTS.relative_to(ROOT)),
            "validated_final_positions": len(baseline_responses),
        },
        "project_hashes_before": before_hashes,
        "git_status_at_runner_start": git_status(),
        "performance": {"100": baseline_performance},
        "positions": {
            "100": [baseline_facts[turn] for turn in sorted(baseline_facts)]
        },
        "move_analyses": {"100": compact_move_records(baseline_move_records)},
        "quality_comparison_to_100": {},
    }
    write_output(payload)

    try:
        for index, visits in enumerate(args.visits):
            print(f"Starting visits={visits} with 16x4", flush=True)
            performance, responses = run_one(
                visits, config_path, game, moves, initial_stones
            )
            payload["performance"][str(visits)] = performance
            if not performance["success"]:
                write_output(payload)
                print(f"Stopping after unsuccessful visits={visits}", flush=True)
                break
            facts = position_facts(responses)
            records = move_records(moves, responses)
            payload["positions"][str(visits)] = [
                facts[turn] for turn in sorted(facts)
            ]
            payload["move_analyses"][str(visits)] = compact_move_records(records)
            payload["quality_comparison_to_100"][str(visits)] = compare_quality(
                baseline_facts, facts, baseline_move_records, records
            )
            write_output(payload)
            print(
                f"Finished visits={visits}: "
                f"{performance['wall_clock_seconds']:.3f}s, "
                f"{performance['positions_per_second']:.4f} positions/s",
                flush=True,
            )
            if index + 1 < len(args.visits):
                print(
                    f"Confirmed process ended; cooling down {COOLDOWN_SECONDS:.0f}s",
                    flush=True,
                )
                time.sleep(COOLDOWN_SECONDS)
    finally:
        after_hashes = key_hashes()
        payload["benchmark_finished_at"] = datetime.now().astimezone().isoformat()
        payload["project_hashes_after"] = after_hashes
        payload["project_files_unchanged"] = before_hashes == after_hashes
        payload["git_status_at_runner_end"] = git_status()
        write_output(payload)

    results = [payload["performance"].get(str(visits)) for visits in args.visits]
    return 0 if all(result and result["success"] for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
