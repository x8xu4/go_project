#!/usr/bin/env python3
"""Benchmark KataGo batch-analysis concurrency without touching project files."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from sgfmill import sgf


ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_DIR = Path(__file__).resolve().parent
CONFIG_SOURCE = ROOT / "analysis.cfg"
MODEL = ROOT / "model.bin.gz"
SGF_PATH = ROOT / "棋譜" / "[朴廷桓]vs[安成浚]1765452105010001779.sgf"
KATAGO = Path(shutil.which("katago") or "")

START_TURN = 128
END_TURN = 191
MAX_VISITS = 100
PV_LENGTH = 8
IDLE_TIMEOUT_SECONDS = 90.0
STARTUP_TIMEOUT_SECONDS = 120.0
COOLDOWN_SECONDS = 10.0

CONFIGURATIONS = (
    ("A_4x16", 4, 16),
    ("B_8x8", 8, 8),
    ("C_16x4", 16, 4),
)

KEY_PROJECT_FILES = (
    ROOT / "analysis.cfg",
    ROOT / "server.py",
    ROOT / "analysis_logic.py",
    ROOT / "flutter_application_1" / "lib" / "main.dart",
    ROOT / "flutter_application_1" / "test" / "widget_test.dart",
    ROOT / "test_analysis_logic.py",
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
    # Kept byte-for-byte equivalent in behavior to server._parse_game_settings.
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
    if not (0 <= START_TURN <= END_TURN <= len(moves)):
        raise RuntimeError("Benchmark turn range is outside the SGF")
    return game, moves, initial_stones


def render_config(name: str, analysis_threads: int, search_threads: int) -> Path:
    source = CONFIG_SOURCE.read_text(encoding="utf-8")
    log_dir = (BENCHMARK_DIR / "katago_logs" / name).resolve()
    log_dir.mkdir(parents=True, exist_ok=True)
    replacements = {
        r"(?m)^logDir\s*=.*$": f"logDir = {log_dir}",
        r"(?m)^numAnalysisThreads\s*=.*$": (
            f"numAnalysisThreads = {analysis_threads}"
        ),
        r"(?m)^numSearchThreadsPerAnalysisThread\s*=.*$": (
            f"numSearchThreadsPerAnalysisThread = {search_threads}"
        ),
    }
    generated = source
    for pattern, replacement in replacements.items():
        generated, count = re.subn(pattern, replacement, generated, count=1)
        if count != 1:
            raise RuntimeError(f"Could not replace config setting: {pattern}")
    config_dir = BENCHMARK_DIR / "configs"
    config_dir.mkdir(parents=True, exist_ok=True)
    destination = config_dir / f"config_{name}.cfg"
    destination.write_text(generated, encoding="utf-8")
    return destination


def build_query(
    config_name: str,
    game: sgf.Sgf_game,
    moves: list[list[str]],
    initial_stones: list[list[str]],
) -> dict:
    komi, rules = parse_komi_and_rules(game)
    turns = list(range(START_TURN, END_TURN + 1))
    query = {
        "id": f"benchmark-{config_name}",
        "moves": moves,
        "analyzeTurns": turns,
        "rules": rules,
        "komi": float(komi),
        "boardXSize": 19,
        "boardYSize": 19,
        "maxVisits": MAX_VISITS,
        "analysisPVLen": PV_LENGTH,
        "includeOwnership": False,
        "reportDuringSearchEvery": 5.0,
        "priority": 0,
    }
    if initial_stones:
        query["initialStones"] = initial_stones
    return query


def start_stderr_reader(process, log_path: Path):
    ready = threading.Event()
    tail: list[str] = []

    def read_stderr():
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


def start_stdout_reader(process):
    lines: queue.Queue[str | None] = queue.Queue()

    def read_stdout():
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
    name: str,
    analysis_threads: int,
    search_threads: int,
    game: sgf.Sgf_game,
    moves: list[list[str]],
    initial_stones: list[list[str]],
) -> dict:
    config_path = render_config(name, analysis_threads, search_threads)
    raw_dir = BENCHMARK_DIR / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = raw_dir / f"{name}.stdout.jsonl"
    stderr_path = raw_dir / f"{name}.stderr.log"
    command = [
        str(KATAGO),
        "analysis",
        "-model",
        str(MODEL),
        "-config",
        str(config_path),
    ]
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    ready, stderr_tail, stderr_thread = start_stderr_reader(process, stderr_path)
    stdout_lines, stdout_thread = start_stdout_reader(process)
    started_wait = time.monotonic()
    while not ready.wait(timeout=0.25):
        if process.poll() is not None:
            raise RuntimeError(
                f"KataGo exited during startup with {process.returncode}: "
                + " | ".join(stderr_tail[-5:])
            )
        if time.monotonic() - started_wait > STARTUP_TIMEOUT_SECONDS:
            stop_owned_process(process)
            raise RuntimeError("KataGo startup timed out")

    query = build_query(name, game, moves, initial_stones)
    expected_turns = set(query["analyzeTurns"])
    completed_turns: set[int] = set()
    actual_visits: list[int] = []
    malformed_responses = 0
    warnings = 0
    during_search_responses = 0
    error_messages: list[str] = []
    timed_out = False
    visibly_stuck = False
    last_activity = time.monotonic()
    started = time.monotonic()
    query_line = json.dumps(query, separators=(",", ":"))
    process.stdin.write(query_line + "\n")
    process.stdin.flush()

    with stdout_path.open("w", encoding="utf-8") as raw_stdout:
        while completed_turns != expected_turns:
            if process.poll() is not None:
                error_messages.append(
                    f"KataGo process exited early with code {process.returncode}"
                )
                break
            try:
                line = stdout_lines.get(timeout=1.0)
            except queue.Empty:
                if time.monotonic() - last_activity > IDLE_TIMEOUT_SECONDS:
                    timed_out = True
                    visibly_stuck = True
                    error_messages.append(
                        f"No KataGo output for {IDLE_TIMEOUT_SECONDS:.0f} seconds"
                    )
                    break
                continue
            if line is None:
                if process.poll() is not None:
                    error_messages.append(
                        f"KataGo stdout EOF with code {process.returncode}"
                    )
                    break
                continue
            last_activity = time.monotonic()
            raw_stdout.write(line)
            raw_stdout.flush()
            try:
                response = json.loads(line)
            except json.JSONDecodeError:
                malformed_responses += 1
                continue
            if "warning" in response:
                warnings += 1
                continue
            if response.get("id") != query["id"]:
                malformed_responses += 1
                continue
            if response.get("isDuringSearch", False):
                during_search_responses += 1
                continue
            if "error" in response:
                error_messages.append(str(response["error"]))
                break
            turn = response.get("turnNumber")
            if not isinstance(turn, int) or turn not in expected_turns:
                malformed_responses += 1
                continue
            if response.get("noResults"):
                error_messages.append(f"turn {turn} returned noResults")
                break
            if turn in completed_turns:
                malformed_responses += 1
                continue
            completed_turns.add(turn)
            root_info = response.get("rootInfo")
            visits = root_info.get("visits") if isinstance(root_info, dict) else None
            if isinstance(visits, int) and visits >= 0:
                actual_visits.append(visits)
            print(
                f"[{name}] {len(completed_turns):2d}/{len(expected_turns)} "
                f"turn={turn}",
                flush=True,
            )

    elapsed = time.monotonic() - started
    process_ended, return_code, stop_method = stop_owned_process(process)
    stderr_thread.join(timeout=2)
    stdout_thread.join(timeout=2)
    positions = len(completed_turns)
    all_visits_available = len(actual_visits) == positions == len(expected_turns)
    total_visits = sum(actual_visits) if all_visits_available else None
    result = {
        "configuration": name,
        "numAnalysisThreads": analysis_threads,
        "numSearchThreadsPerAnalysisThread": search_threads,
        "search_thread_budget": analysis_threads * search_threads,
        "sgf": str(SGF_PATH.relative_to(ROOT)),
        "sgf_total_moves": len(moves),
        "start_turn": START_TURN,
        "end_turn": END_TURN,
        "requested_positions": len(expected_turns),
        "completed_positions": positions,
        "maxVisits": MAX_VISITS,
        "analysisPVLen": PV_LENGTH,
        "includeOwnership": False,
        "wall_clock_seconds": elapsed,
        "seconds_per_position": elapsed / positions if positions else None,
        "positions_per_second": positions / elapsed if elapsed else None,
        "total_actual_visits": total_visits,
        "visits_per_second": (
            total_visits / elapsed if total_visits is not None and elapsed else None
        ),
        "actual_visits_min": min(actual_visits) if actual_visits else None,
        "actual_visits_max": max(actual_visits) if actual_visits else None,
        "actual_visits_mean": (
            sum(actual_visits) / len(actual_visits) if actual_visits else None
        ),
        "timeout": timed_out,
        "katago_errors": error_messages,
        "malformed_responses": malformed_responses,
        "warnings": warnings,
        "during_search_responses": during_search_responses,
        "process_crash": return_code not in (0, None),
        "visibly_stuck": visibly_stuck,
        "process_ended": process_ended,
        "process_return_code": return_code,
        "process_stop_method": stop_method,
        "success": (
            positions == len(expected_turns)
            and not timed_out
            and not error_messages
            and malformed_responses == 0
            and process_ended
        ),
        "config_file": str(config_path.relative_to(ROOT)),
        "stdout_log": str(stdout_path.relative_to(ROOT)),
        "stderr_log": str(stderr_path.relative_to(ROOT)),
    }
    return result


def write_results(payload: dict):
    (BENCHMARK_DIR / "results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--configs",
        nargs="*",
        default=[item[0] for item in CONFIGURATIONS],
        choices=[item[0] for item in CONFIGURATIONS],
    )
    args = parser.parse_args()
    if not KATAGO.is_file():
        raise RuntimeError("katago executable was not found")
    for path in (CONFIG_SOURCE, MODEL, SGF_PATH):
        if not path.is_file():
            raise RuntimeError(f"Required file not found: {path}")

    before_hashes = key_hashes()
    game, moves, initial_stones = load_workload()
    selected = [item for item in CONFIGURATIONS if item[0] in args.configs]
    payload = {
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
            "maxVisits": MAX_VISITS,
            "analysisPVLen": PV_LENGTH,
            "includeOwnership": False,
            "rules": parse_komi_and_rules(game)[1],
            "komi": parse_komi_and_rules(game)[0],
            "full_move_list_supplied": True,
        },
        "project_hashes_before": before_hashes,
        "git_status_at_runner_start": git_status(),
        "results": [],
    }
    write_results(payload)

    try:
        for index, (name, analysis_threads, search_threads) in enumerate(selected):
            print(
                f"Starting {name}: analysis={analysis_threads}, "
                f"search={search_threads}",
                flush=True,
            )
            result = run_one(
                name,
                analysis_threads,
                search_threads,
                game,
                moves,
                initial_stones,
            )
            payload["results"].append(result)
            write_results(payload)
            print(
                f"Finished {name}: {result['wall_clock_seconds']:.3f}s, "
                f"{result['positions_per_second']:.4f} positions/s",
                flush=True,
            )
            if not result["success"]:
                print(f"Stopping after unsuccessful configuration {name}", flush=True)
                break
            if index + 1 < len(selected):
                print(
                    f"Confirmed PID ended; cooling down {COOLDOWN_SECONDS:.0f}s",
                    flush=True,
                )
                time.sleep(COOLDOWN_SECONDS)
    finally:
        after_hashes = key_hashes()
        payload["benchmark_finished_at"] = datetime.now().astimezone().isoformat()
        payload["project_hashes_after"] = after_hashes
        payload["project_files_unchanged"] = before_hashes == after_hashes
        payload["git_status_at_runner_end"] = git_status()
        write_results(payload)

    return 0 if all(item["success"] for item in payload["results"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
