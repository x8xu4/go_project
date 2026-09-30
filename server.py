import subprocess
import json
import os
import threading
import uuid
import time
import shutil
import random
import atexit
import queue
from collections import deque
from dataclasses import dataclass, field
from flask import Flask, request, jsonify
from flask_cors import CORS
from sgfmill import sgf
from sgf_utils import (
    get_capture_counts,
    get_initial_stones_from_game,
    get_moves_from_game,
)
from logos_engine import LogosEngine
from analysis_logic import (
    IMPORTANCE_THRESHOLDS,
    build_move_analyses,
    thresholds_as_dict,
)

app = Flask(__name__)
CORS(app)

engine = LogosEngine(corpus_path='logosgo_corpus_full.csv')

KATAGO_EXEC = "katago"
MODEL_FILE = "/Users/ouo1010/Desktop/go_project/model.bin.gz"
CONFIG_FILE = "/Users/ouo1010/Desktop/go_project/analysis.cfg"

# A slow search is allowed to run indefinitely while KataGo keeps sending
# reportDuringSearch heartbeats. Only complete inactivity is treated as a hang.
KATAGO_HEARTBEAT_SECONDS = 5.0
KATAGO_IDLE_TIMEOUT_SECONDS = 90.0
WHOLE_GAME_MAX_VISITS = 100
WHOLE_GAME_PRIORITY = 0
POSITION_MAX_VISITS = 500
POSITION_PRIORITY = 10
POSITION_ANALYSIS_THREADS = 1
POSITION_SEARCH_THREADS = 16


class KataGoError(RuntimeError):
    pass


class AnalysisCancelled(RuntimeError):
    pass


class AnalysisPreempted(RuntimeError):
    pass


class KataGoClient:
    """共用一個 KataGo analysis 行程，並依 query id 分派回應。"""

    def __init__(
        self,
        executable,
        model_file,
        config_file,
        *,
        label="shared",
        override_config=None,
    ):
        self.executable = executable
        self.model_file = model_file
        self.config_file = config_file
        self.label = label
        self.override_config = override_config
        self._process = None
        self._start_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._pending = {}
        self._stderr_tail = deque(maxlen=30)

    @property
    def available(self):
        return (
            shutil.which(self.executable) is not None
            and os.path.isfile(self.model_file)
            and os.path.isfile(self.config_file)
        )

    def _ensure_started(self):
        with self._start_lock:
            if self._process is not None and self._process.poll() is None:
                return self._process
            if not self.available:
                raise KataGoError("找不到 KataGo 執行檔、模型或設定檔")

            cmd = [
                self.executable,
                "analysis",
                "-model",
                self.model_file,
                "-config",
                self.config_file,
            ]
            if self.override_config:
                cmd.extend(["-override-config", self.override_config])
            print(f"啟動 {self.label} KataGo: {cmd}")
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            self._process = process
            threading.Thread(
                target=self._read_stdout, args=(process,), daemon=True
            ).start()
            threading.Thread(
                target=self._read_stderr, args=(process,), daemon=True
            ).start()
            return process

    def _read_stdout(self, process):
        try:
            for line in process.stdout:
                try:
                    response = json.loads(line)
                except json.JSONDecodeError as exc:
                    print(f"KataGo 回傳非 JSON 資料: {exc}: {line[:200]!r}")
                    continue

                query_id = response.get("id")
                if "warning" in response:
                    print(f"KataGo 警告 ({query_id}): {response['warning']}")
                    continue
                if query_id is None:
                    print(f"KataGo 回傳缺少 id: {response}")
                    continue

                with self._pending_lock:
                    response_queue = self._pending.get(query_id)
                if response_queue is not None:
                    response_queue.put(response)
        finally:
            return_code = process.poll()
            detail = self.diagnostics()
            self._fail_pending(
                f"KataGo 行程已結束 (code={return_code})"
                + (f": {detail}" if detail else "")
            )
            with self._start_lock:
                if self._process is process:
                    self._process = None

    def _read_stderr(self, process):
        for line in process.stderr:
            message = line.rstrip()
            if message:
                self._stderr_tail.append(message)
                print(f"[KataGo] {message}")

    def _fail_pending(self, message):
        with self._pending_lock:
            pending = list(self._pending.values())
        for response_queue in pending:
            response_queue.put({"error": message})

    def diagnostics(self):
        return " | ".join(list(self._stderr_tail)[-5:])

    def _write_payload(self, process, payload):
        with self._write_lock:
            if process.poll() is not None or process.stdin is None:
                raise KataGoError("程式尚未就緒或已停止")
            process.stdin.write(json.dumps(payload) + "\n")
            process.stdin.flush()

    def terminate(self, query_id):
        process = self._ensure_started()
        self._write_payload(
            process,
            {
                "id": f"terminate-{uuid.uuid4()}",
                "action": "terminate",
                "terminateId": query_id,
            },
        )

    def query(
        self,
        payload,
        *,
        idle_timeout=KATAGO_IDLE_TIMEOUT_SECONDS,
        cancel_event=None,
    ):
        process = self._ensure_started()
        query_id = payload.get("id")
        if not query_id:
            raise ValueError("KataGo query 必須包含 id")

        response_queue = queue.Queue()
        with self._pending_lock:
            if query_id in self._pending:
                raise ValueError(f"重複的 KataGo query id: {query_id}")
            self._pending[query_id] = response_queue

        try:
            self._write_payload(process, payload)
            last_activity = time.monotonic()
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    self.terminate(query_id)
                    raise AnalysisCancelled("分析已取消")
                if process.poll() is not None:
                    raise KataGoError(f"KataGo 程式已結束 (code={process.poll()})")
                try:
                    response = response_queue.get(timeout=1.0)
                except queue.Empty:
                    if time.monotonic() - last_activity > idle_timeout:
                        self.terminate(query_id)
                        raise KataGoError(
                            f"KataGo 已 {idle_timeout:.0f} 秒無任何回應，判定為無回應"
                        )
                    continue
                last_activity = time.monotonic()
                if "error" in response:
                    raise KataGoError(str(response["error"]))
                if not response.get("isDuringSearch", False):
                    return response
        except (BrokenPipeError, OSError) as exc:
            raise KataGoError(f"無法傳送資料給 KataGo: {exc}") from exc
        finally:
            with self._pending_lock:
                self._pending.pop(query_id, None)

    def query_many(
        self,
        payload,
        expected_turns,
        on_final_result,
        *,
        idle_timeout=KATAGO_IDLE_TIMEOUT_SECONDS,
        cancel_event=None,
        preempt_event=None,
    ):
        """Wait for one final response per analyzeTurns entry, with idle watchdog."""
        process = self._ensure_started()
        query_id = payload.get("id")
        if not query_id:
            raise ValueError("KataGo query 必須包含 id")
        expected_turns = set(expected_turns)
        response_queue = queue.Queue()
        with self._pending_lock:
            if query_id in self._pending:
                raise ValueError(f"重複的 KataGo query id: {query_id}")
            self._pending[query_id] = response_queue

        completed = set()
        termination_sent = False
        try:
            self._write_payload(process, payload)
            last_activity = time.monotonic()
            while completed != expected_turns:
                if cancel_event is not None and cancel_event.is_set():
                    if not termination_sent:
                        self.terminate(query_id)
                        termination_sent = True
                    raise AnalysisCancelled("分析已取消")
                if preempt_event is not None and preempt_event.is_set():
                    if not termination_sent:
                        self.terminate(query_id)
                        termination_sent = True
                    raise AnalysisPreempted("背景分析暫時讓出資源")
                if process.poll() is not None:
                    raise KataGoError(f"KataGo 程式已結束 (code={process.poll()})")
                try:
                    response = response_queue.get(timeout=1.0)
                except queue.Empty:
                    if time.monotonic() - last_activity > idle_timeout:
                        self.terminate(query_id)
                        raise KataGoError(
                            f"KataGo 已 {idle_timeout:.0f} 秒無任何回應，判定為無回應"
                        )
                    continue
                last_activity = time.monotonic()
                if "error" in response:
                    raise KataGoError(str(response["error"]))
                if response.get("isDuringSearch", False):
                    continue
                turn_number = response.get("turnNumber")
                if not isinstance(turn_number, int) or turn_number not in expected_turns:
                    raise KataGoError(
                        f"KataGo 回傳非預期 turnNumber: {turn_number!r}"
                    )
                if response.get("noResults"):
                    raise KataGoError(f"第 {turn_number} 手沒有分析結果")
                if turn_number in completed:
                    continue
                completed.add(turn_number)
                on_final_result(turn_number, response)
            return completed
        except (BrokenPipeError, OSError) as exc:
            raise KataGoError(f"無法傳送資料給 KataGo: {exc}") from exc
        finally:
            with self._pending_lock:
                self._pending.pop(query_id, None)

    def close(self):
        with self._start_lock:
            process = self._process
            self._process = None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


katago_client = KataGoClient(
    KATAGO_EXEC,
    MODEL_FILE,
    CONFIG_FILE,
    label="背景 16×4",
)
position_katago_client = KataGoClient(
    KATAGO_EXEC,
    MODEL_FILE,
    CONFIG_FILE,
    label="前景 1×16",
    override_config=(
        f"numAnalysisThreads={POSITION_ANALYSIS_THREADS},"
        f"numSearchThreadsPerAnalysisThread={POSITION_SEARCH_THREADS}"
    ),
)
atexit.register(katago_client.close)
atexit.register(position_katago_client.close)

# 全域分析狀態（取消機制）
current_analysis_id = None
analysis_lock = threading.Lock()


@dataclass
class AnalysisJob:
    job_id: str
    sgf_content: str
    total_moves: int
    status: str = "queued"
    completed_moves: int = 0
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    eta_seconds: float | None = None
    error: str | None = None
    result: dict | None = None
    position_results: dict = field(default_factory=dict)
    commentary_cache: dict = field(default_factory=dict)
    eta_history: list = field(default_factory=list)
    cancel_event: threading.Event = field(default_factory=threading.Event)
    done_event: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)
    _last_completion_at: float | None = None
    _recent_intervals: deque = field(default_factory=lambda: deque(maxlen=20))
    _ewma_interval: float | None = None

    def start(self):
        with self.lock:
            self.status = "running"
            self.started_at = time.time()
            self._last_completion_at = time.monotonic()

    def record_position(self, turn_number, response):
        now = time.monotonic()
        with self.lock:
            self.position_results[turn_number] = response
            if turn_number > 0:
                self.completed_moves += 1

            if self._last_completion_at is not None:
                interval = max(0.0, now - self._last_completion_at)
                self._recent_intervals.append(interval)
                self._ewma_interval = (
                    interval
                    if self._ewma_interval is None
                    else 0.25 * interval + 0.75 * self._ewma_interval
                )
            self._last_completion_at = now

            completed_positions = len(self.position_results)
            # analyzeTurns 會並行完成局面，單個回傳間隔容易呈現
            # 「一批很快、下一批較慢」。樣本足夠後，以整體吞吐量
            # 為主、rolling/EWMA 為輔，並限制單次跳動。
            if completed_positions >= 8 and self._recent_intervals:
                ordered = sorted(self._recent_intervals)
                if len(ordered) >= 6:
                    ordered = ordered[1:-1]
                rolling = sum(ordered) / len(ordered)
                recent_rate = (
                    0.6 * self._ewma_interval + 0.4 * rolling
                    if self._ewma_interval is not None
                    else rolling
                )
                overall_rate = self.elapsed_seconds_locked() / completed_positions
                seconds_per_position = 0.8 * overall_rate + 0.2 * recent_rate
                remaining_positions = max(
                    0, (self.total_moves + 1) - completed_positions
                )
                raw_eta = seconds_per_position * remaining_positions
                if self.eta_seconds is None:
                    self.eta_seconds = raw_eta
                else:
                    lower = self.eta_seconds * 0.85
                    upper = self.eta_seconds * 1.10
                    self.eta_seconds = min(upper, max(lower, raw_eta))
                self.eta_history.append(
                    {
                        "completed": self.completed_moves,
                        "eta_seconds": self.eta_seconds,
                        "elapsed_seconds": self.elapsed_seconds_locked(),
                    }
                )

    def elapsed_seconds_locked(self):
        if self.started_at is None:
            return 0.0
        end = self.finished_at or time.time()
        return max(0.0, end - self.started_at)

    def finish(self, status, *, result=None, error=None):
        with self.lock:
            self.status = status
            self.result = result
            self.error = error
            self.finished_at = time.time()
            self.eta_seconds = 0.0 if status == "completed" else None
        self.done_event.set()

    def snapshot(self, include_result=False):
        with self.lock:
            payload = {
                "job_id": self.job_id,
                "status": self.status,
                "completed_moves": self.completed_moves,
                "total_moves": self.total_moves,
                "progress": (
                    self.completed_moves / self.total_moves
                    if self.total_moves
                    else 1.0
                ),
                "eta_seconds": self.eta_seconds,
                "elapsed_seconds": self.elapsed_seconds_locked(),
                "error": self.error,
            }
            if include_result and self.status == "completed":
                payload["result"] = self.result
            return payload


analysis_jobs = {}
analysis_jobs_lock = threading.Lock()
active_analysis_job_id = None


@dataclass
class PositionRequest:
    """Tracks the newest foreground request for one Flutter client."""

    query_id: str
    request_id: str
    cancel_event: threading.Event = field(default_factory=threading.Event)


position_requests = {}
position_requests_lock = threading.Lock()
position_request_active = threading.Event()
background_query_paused = threading.Event()
background_query_paused.set()
background_lane_lock = threading.Lock()


def _begin_position_request(client_id, request_id, query_id):
    request_state = PositionRequest(query_id=query_id, request_id=request_id)
    with position_requests_lock:
        previous = position_requests.get(client_id)
        if previous is not None:
            # Only supersede an older foreground request from the same app.
            # The whole-game query has a different cancellation event and id.
            previous.cancel_event.set()
        position_requests[client_id] = request_state
        position_request_active.set()
    return request_state


def _finish_position_request(client_id, query_id):
    with position_requests_lock:
        current = position_requests.get(client_id)
        removed_current = False
        if current is not None and current.query_id == query_id:
            position_requests.pop(client_id, None)
            removed_current = True
        if removed_current and not position_requests:
            # Release Metal/model resources before allowing the batch lane to
            # restart, so the two differently tuned processes never coexist.
            position_katago_client.close()
            position_request_active.clear()


def _get_analysis_job(job_id):
    with analysis_jobs_lock:
        return analysis_jobs.get(job_id)


def _register_analysis_job(sgf_content):
    global active_analysis_job_id
    game, all_moves, _, _ = _parse_sgf(sgf_content)
    del game
    job = AnalysisJob(str(uuid.uuid4()), sgf_content, len(all_moves))
    with analysis_jobs_lock:
        previous = analysis_jobs.get(active_analysis_job_id)
        if previous is not None and previous.status in ("queued", "running"):
            previous.cancel_event.set()
        analysis_jobs[job.job_id] = job
        active_analysis_job_id = job.job_id
        completed = [
            item
            for item in analysis_jobs.values()
            if item.status in ("completed", "failed", "cancelled")
        ]
        for old in sorted(completed, key=lambda item: item.created_at)[:-8]:
            analysis_jobs.pop(old.job_id, None)
    threading.Thread(target=_run_analysis_job, args=(job,), daemon=True).start()
    return job


def _analyze_remaining_positions(
    job,
    all_moves,
    turns,
    komi,
    rule_set,
    initial_stones,
):
    print(f"背景分析開始 {job.job_id[:8]}: {len(all_moves)} 手")
    while True:
        if job.cancel_event.is_set():
            raise AnalysisCancelled("分析已取消")
        while position_request_active.is_set():
            if job.cancel_event.wait(timeout=0.2):
                raise AnalysisCancelled("分析已取消")

        with job.lock:
            completed_turns = set(job.position_results)
        remaining_turns = [turn for turn in turns if turn not in completed_turns]
        if not remaining_turns:
            return

        query_id = f"whole-game-{job.job_id}-{uuid.uuid4()}"
        query = {
            "id": query_id,
            "moves": all_moves,
            "analyzeTurns": remaining_turns,
            "rules": rule_set,
            "komi": float(komi),
            "boardXSize": 19,
            "boardYSize": 19,
            "maxVisits": WHOLE_GAME_MAX_VISITS,
            "analysisPVLen": 8,
            "includeOwnership": False,
            "reportDuringSearchEvery": KATAGO_HEARTBEAT_SECONDS,
            "priority": WHOLE_GAME_PRIORITY,
        }
        if initial_stones:
            query["initialStones"] = initial_stones

        background_query_paused.clear()
        try:
            katago_client.query_many(
                query,
                remaining_turns,
                job.record_position,
                cancel_event=job.cancel_event,
                preempt_event=position_request_active,
            )
        except AnalysisPreempted:
            print(
                f"背景分析讓路 {job.job_id[:8]}: "
                f"已保留 {len(job.position_results)}/{len(turns)} 個局面"
            )
        finally:
            background_query_paused.set()


def _run_analysis_job(job):
    job.start()
    try:
        if not katago_client.available:
            raise KataGoError("找不到 KataGo 執行檔、模型或設定檔")
        game, all_moves, komi, rule_set = _parse_sgf(job.sgf_content)
        initial_stones = get_initial_stones_from_game(game)
        turns = list(range(len(all_moves) + 1))
        with background_lane_lock:
            _analyze_remaining_positions(
                job,
                all_moves,
                turns,
                komi,
                rule_set,
                initial_stones,
            )
        if job.cancel_event.is_set():
            raise AnalysisCancelled("分析已取消")

        move_analyses = build_move_analyses(all_moves, job.position_results)
        for record in move_analyses:
            record["auto_tag"] = engine._importance_title(record)
            record["auto_commentary"] = engine.generate_auto_commentary(record)

        winrates = [
            float(job.position_results[index]["rootInfo"]["winrate"])
            for index in turns
        ]
        scores = [
            float(job.position_results[index]["rootInfo"]["scoreLead"])
            for index in turns
        ]
        importance_counts = {
            level: sum(1 for item in move_analyses if item["importance"] == level)
            for level in ("ordinary", "notice", "important", "decisive")
        }
        important_moves = [
            item["move_number"]
            for item in move_analyses
            if item["importance"] in ("important", "decisive")
        ]
        result = {
            "winrates": winrates,
            "scores": scores,
            "move_analyses": move_analyses,
            "important_moves": important_moves,
            "blunders": important_moves,
            "importance_counts": importance_counts,
            "thresholds": thresholds_as_dict(),
            "move_count": len(all_moves),
            "eta_history": list(job.eta_history),
        }
        job.finish("completed", result=result)
        print(
            f"背景分析完成 {job.job_id[:8]}: {len(all_moves)} 手, "
            f"{job.snapshot()['elapsed_seconds']:.1f} 秒"
        )
    except AnalysisCancelled as exc:
        job.finish("cancelled", error=str(exc))
        print(f"背景分析取消 {job.job_id[:8]}")
    except Exception as exc:
        import traceback

        detail = traceback.format_exc()
        print(f"背景分析失敗 {job.job_id[:8]}: {detail}")
        diagnostics = katago_client.diagnostics()
        message = str(exc) + (f" | KataGo: {diagnostics}" if diagnostics else "")
        job.finish("failed", error=message)


def _parse_game_settings(game):
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
    rule_set = "chinese" if komi == 7.5 else "korean"
    return komi, rule_set


def _parse_sgf(sgf_content):
    game = sgf.Sgf_game.from_bytes(sgf_content.encode("utf-8"))
    komi, rule_set = _parse_game_settings(game)
    return game, get_moves_from_game(game), komi, rule_set


def _validate_extra_moves(raw_moves):
    if raw_moves is None:
        return []
    if not isinstance(raw_moves, list):
        raise ValueError("extra_moves 必須是陣列")

    valid_columns = "ABCDEFGHJKLMNOPQRST"
    validated = []
    for index, move in enumerate(raw_moves):
        if not isinstance(move, list) or len(move) != 2:
            raise ValueError(f"extra_moves[{index}] 格式錯誤")
        player, coordinate = move
        if player not in ("B", "W") or not isinstance(coordinate, str):
            raise ValueError(f"extra_moves[{index}] 的棋色或座標錯誤")
        coordinate = coordinate.upper()
        if coordinate != "PASS":
            if len(coordinate) < 2 or coordinate[0] not in valid_columns:
                raise ValueError(f"extra_moves[{index}] 的座標錯誤")
            try:
                row = int(coordinate[1:])
            except ValueError as exc:
                raise ValueError(f"extra_moves[{index}] 的座標錯誤") from exc
            if not 1 <= row <= 19:
                raise ValueError(f"extra_moves[{index}] 超出 19 路棋盤")
        validated.append([player, coordinate.lower() if coordinate == "PASS" else coordinate])
    return validated


@app.route('/analysis/start', methods=['POST'])
def start_analysis():
    try:
        data = request.get_json(silent=True) or {}
        sgf_content = data.get("sgf_content")
        if not isinstance(sgf_content, str) or not sgf_content.strip():
            return jsonify({"status": "error", "message": "尚未提供 SGF 棋譜"}), 400
        job = _register_analysis_job(sgf_content)
        return jsonify(job.snapshot()), 202
    except Exception as exc:
        import traceback

        print(f"建立分析任務失敗: {traceback.format_exc()}")
        return jsonify({"status": "error", "message": str(exc)}), 400


@app.route('/analysis/<job_id>', methods=['GET'])
def get_analysis_status(job_id):
    job = _get_analysis_job(job_id)
    if job is None:
        return jsonify({"status": "error", "message": "找不到分析任務"}), 404
    return jsonify(job.snapshot(include_result=True))


@app.route('/analysis/<job_id>/cancel', methods=['POST'])
def cancel_analysis(job_id):
    job = _get_analysis_job(job_id)
    if job is None:
        return jsonify({"status": "error", "message": "找不到分析任務"}), 404
    job.cancel_event.set()
    return jsonify({"status": "cancelling", "job_id": job_id})


@app.route('/analysis/<job_id>/ask', methods=['POST'])
def ask_about_move(job_id):
    job = _get_analysis_job(job_id)
    if job is None:
        return jsonify({"status": "error", "message": "找不到分析任務"}), 404
    if job.status != "completed" or not isinstance(job.result, dict):
        return jsonify({"status": "error", "message": "整盤分析尚未完成"}), 409
    data = request.get_json(silent=True) or {}
    try:
        move_number = int(data.get("move_number"))
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "move_number 格式錯誤"}), 400
    records = job.result.get("move_analyses", [])
    if not 1 <= move_number <= len(records):
        return jsonify({"status": "error", "message": "move_number 超出範圍"}), 400

    with job.lock:
        cached = move_number in job.commentary_cache
        if cached:
            commentary = job.commentary_cache[move_number]
        else:
            commentary = engine.generate_detailed_commentary(records[move_number - 1])
            job.commentary_cache[move_number] = commentary
    return jsonify({
        "status": "success",
        "move_number": move_number,
        "commentary": commentary,
        "cached": cached,
    })


@app.route('/analyze_sgf', methods=['POST'])
def analyze_sgf():
    global current_analysis_id

    # 產生此次分析的唯一 ID，並取消舊的
    my_id = str(uuid.uuid4())
    with analysis_lock:
        current_analysis_id = my_id
    print(f"新分析開始: {my_id[:8]}")

    try:
        data = request.get_json(silent=True) or {}
        sgf_content = data.get('sgf_content')
        if not sgf_content:
            return jsonify({"error": "No SGF content provided"}), 400

        game, all_moves, komi, rule_set = _parse_sgf(sgf_content)
        initial_stones = get_initial_stones_from_game(game)
        total_steps = len(all_moves)
        print(f"讀取手數: {total_steps}")

        has_katago = katago_client.available
        if not has_katago:
            print("警告: 找不到 KataGo 執行檔，將使用模擬數據回傳")

        step_interval = 1
        target_count = len(range(1, total_steps + 1, step_interval))
        print(f"目標收集數: {target_count}")

        collected = 0
        winrates_raw = {}

        for i in range(1, total_steps + 1, step_interval):

            # ★ 取消檢查：每手分析前確認是否仍是最新請求
            with analysis_lock:
                if current_analysis_id != my_id:
                    print(f"偵測到新棋譜，中止分析 {my_id[:8]}")
                    return jsonify({"status": "cancelled", "message": "新棋譜已匯入"}), 409

            current_moves = all_moves[:i]
            query_id = f"game-{my_id}-step-{i}"
            query = {
                "id": query_id,
                "moves": current_moves,
                "rules": rule_set,
                "komi": float(komi),
                "boardXSize": 19,
                "boardYSize": 19,
                "maxVisits": 100,
                "includeOwnership": False,
                "reportDuringSearchEvery": KATAGO_HEARTBEAT_SECONDS,
            }
            if initial_stones:
                query["initialStones"] = initial_stones

            if has_katago:
                try:
                    res = katago_client.query(query)
                    if 'rootInfo' in res:
                        wr = res['rootInfo']['winrate']
                        winrates_raw[i] = wr
                        collected += 1
                        print(f"收到 {query_id} 勝率: {wr:.3f} 已收{collected}/{target_count}")
                    elif 'moveInfos' in res and len(res['moveInfos']) > 0:
                        wr = res['moveInfos'][0].get('winrate', 0.5)
                        winrates_raw[i] = wr
                        collected += 1
                        print(f"收到 {query_id} moveInfos 勝率: {wr:.3f} 已收{collected}/{target_count}")
                except (KataGoError, KeyError, TypeError, ValueError) as exc:
                    print(f"KataGo 分析 {query_id} 失敗: {exc}")
                    break
            else:
                wr = 0.5 + (random.random() * 0.1 - 0.05)
                winrates_raw[i] = wr
                collected += 1

        print(f"實際收集數: {collected}")
        print(f"winrates_raw 前5筆: {list(winrates_raw.items())[:5]}")

        # 補齊每手勝率
        winrates = []
        sorted_steps = sorted(winrates_raw.keys())
        for i in range(total_steps + 1):
            if i in winrates_raw:
                wr = winrates_raw[i]
                if i > total_steps * 0.8:
                    if wr > 0.85: wr = min(0.99, wr + 0.1)
                    elif wr < 0.15: wr = max(0.01, wr - 0.1)
                winrates.append(round(wr, 4))
            elif sorted_steps:
                closest = min(sorted_steps, key=lambda x: abs(x - i))
                wr = winrates_raw[closest]
                if i > total_steps * 0.8:
                    if wr > 0.85: wr = min(0.99, wr + 0.1)
                    elif wr < 0.15: wr = max(0.01, wr - 0.1)
                winrates.append(round(wr, 4))
            else:
                winrates.append(0.5)

        # 找敗著
        blunders = []
        for i in range(1, len(winrates)):
            diff = winrates[i] - winrates[i-1]
            if diff > 0.15:
                blunders.append(i - 1)
            elif diff < -0.15:
                blunders.append(i)

        print(f"最終 winrates 長度: {len(winrates)}, winrates_raw 筆數: {len(winrates_raw)}")

        if len(winrates_raw) == 0:
            error_msg = "KataGo 未回傳任何有效勝率資料，可能引擎啟動失敗或參數錯誤"
            diagnostics = katago_client.diagnostics()
            if diagnostics:
                error_msg += f" | 引擎錯誤: {diagnostics}"
            return jsonify({"status": "error", "message": error_msg}), 500

        return jsonify({
            "status": "success",
            "winrates": winrates,
            "blunders": blunders,
            "move_count": total_steps
        })

    except Exception as e:
        import traceback
        print(f"錯誤: {traceback.format_exc()}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/analyze_position', methods=['POST'])
def analyze_position():
    """分析棋譜目前手數（加上可選試下手順），回傳黑方視角形勢資料。"""
    try:
        data = request.get_json(silent=True) or {}
        sgf_content = data.get("sgf_content")
        if not isinstance(sgf_content, str) or not sgf_content.strip():
            return jsonify({"status": "error", "message": "尚未提供 SGF 棋譜"}), 400

        client_id = data.get("client_id")
        request_id = data.get("client_request_id")
        if not isinstance(client_id, str) or not client_id.strip():
            client_id = "legacy-local-client"
        if not isinstance(request_id, str) or not request_id.strip():
            request_id = str(uuid.uuid4())
        client_id = client_id.strip()
        request_id = request_id.strip()
        if len(client_id) > 128 or len(request_id) > 128:
            return jsonify({
                "status": "error",
                "message": "形勢判斷 request id 過長",
            }), 400

        game, all_moves, komi, rule_set = _parse_sgf(sgf_content)
        try:
            move_count = int(data.get("move_count", len(all_moves)))
        except (TypeError, ValueError):
            return jsonify({"status": "error", "message": "move_count 格式錯誤"}), 400
        if move_count < 0 or move_count > len(all_moves):
            return jsonify({
                "status": "error",
                "message": f"move_count 超出範圍（0～{len(all_moves)}）",
            }), 400

        extra_moves = _validate_extra_moves(data.get("extra_moves"))
        moves = all_moves[:move_count]
        moves.extend(extra_moves)
        initial_stones = get_initial_stones_from_game(game)
        capture_counts = get_capture_counts(
            game,
            move_count=move_count,
            extra_moves=extra_moves,
        )
        query_id = f"position-{uuid.uuid4()}"
        request_state = _begin_position_request(client_id, request_id, query_id)
        query = {
            "id": query_id,
            "moves": moves,
            "rules": rule_set,
            "komi": float(komi),
            "boardXSize": 19,
            "boardYSize": 19,
            "maxVisits": POSITION_MAX_VISITS,
            "includeOwnership": True,
            "includeOwnershipStdev": True,
            "reportDuringSearchEvery": KATAGO_HEARTBEAT_SECONDS,
            "priority": POSITION_PRIORITY,
        }
        if initial_stones:
            query["initialStones"] = initial_stones
        print(
            f"開始形勢判斷 {query_id[:17]}: "
            f"實戰 {move_count} 手、試下 {len(moves) - move_count} 手"
        )
        try:
            if not background_query_paused.wait(timeout=15):
                raise KataGoError("背景分析未能在 15 秒內讓出資源")
            # The foreground lane uses a single-position configuration. Close
            # the now-idle batch process first to avoid two Metal models being
            # resident or searching at the same time on a 16 GB machine.
            katago_client.close()
            response = position_katago_client.query(
                query,
                cancel_event=request_state.cancel_event,
            )
        finally:
            _finish_position_request(client_id, query_id)

        ownership = response.get("ownership")
        ownership_stdev = response.get("ownershipStdev")
        root_info = response.get("rootInfo")
        if not isinstance(ownership, list) or len(ownership) != 19 * 19:
            raise KataGoError(
                f"ownership 格式錯誤，預期 361 筆，實際 "
                f"{len(ownership) if isinstance(ownership, list) else '缺失'}"
            )
        if not isinstance(root_info, dict):
            raise KataGoError("KataGo 回傳缺少 rootInfo")
        if not isinstance(ownership_stdev, list) or len(ownership_stdev) != 19 * 19:
            raise KataGoError(
                f"ownershipStdev 格式錯誤，預期 361 筆，實際 "
                f"{len(ownership_stdev) if isinstance(ownership_stdev, list) else '缺失'}"
            )

        try:
            ownership = [float(value) for value in ownership]
            ownership_stdev = [float(value) for value in ownership_stdev]
            black_winrate = float(root_info["winrate"])
            black_score_lead = float(root_info["scoreLead"])
        except (KeyError, TypeError, ValueError) as exc:
            raise KataGoError(f"KataGo 形勢數值格式錯誤: {exc}") from exc
        if any(value < -1.001 or value > 1.001 for value in ownership):
            raise KataGoError("KataGo ownership 數值超出 -1～1")
        if any(value < 0.0 or value > 1.001 for value in ownership_stdev):
            raise KataGoError("KataGo ownershipStdev 數值超出 0～1")
        if not 0.0 <= black_winrate <= 1.0:
            raise KataGoError("KataGo winrate 數值超出 0～1")

        # ownership 是每個交叉點最終由黑方控制的期望值（-1 白、+1 黑）。
        # 轉成雙方期望控制點數；兩者合計為 19×19。
        black_ownership_points = sum((value + 1.0) / 2.0 for value in ownership)
        white_ownership_points = 19 * 19 - black_ownership_points

        return jsonify({
            "status": "success",
            "client_request_id": request_id,
            "ownership": ownership,
            "ownership_stdev": ownership_stdev,
            # analysis.cfg 固定 reportAnalysisWinratesAs = BLACK，
            # 因此 rootInfo 的 winrate 與 scoreLead 都是黑方視角。
            "perspective": "black",
            "black_score_lead": black_score_lead,
            "black_winrate": black_winrate,
            "white_winrate": 1.0 - black_winrate,
            "black_ownership_points": black_ownership_points,
            "white_ownership_points": white_ownership_points,
            **capture_counts,
            "current_player": root_info.get("currentPlayer"),
            "move_count": len(moves),
            "visits": root_info.get("visits"),
        })
    except AnalysisCancelled as exc:
        print(f"形勢判斷已被較新的請求取代: {exc}")
        return jsonify({
            "status": "cancelled",
            "message": "形勢判斷已被較新的請求取代",
            "client_request_id": request_id if 'request_id' in locals() else None,
        }), 409
    except ValueError as exc:
        print(f"形勢判斷請求格式錯誤: {exc}")
        return jsonify({"status": "error", "message": str(exc)}), 400
    except KataGoError as exc:
        diagnostics = position_katago_client.diagnostics()
        print(f"形勢判斷失敗: {exc}; KataGo: {diagnostics}")
        return jsonify({
            "status": "error",
            "message": str(exc),
            "engine_detail": diagnostics,
        }), 503
    except Exception as exc:
        import traceback
        print(f"形勢判斷未預期錯誤: {traceback.format_exc()}")
        return jsonify({"status": "error", "message": str(exc)}), 500


@app.route('/get_commentary', methods=['POST'])
def get_commentary():
    try:
        data = request.json
        move_data = {
            "winrate": data.get('winrate', 0.5),
            "winrate_change": data.get('winrate_change', 0),
            "score_lead": data.get('score_lead', 0),
            "score_lead_change": data.get('score_lead_change', 0),
            "x": data.get('x', 0),
            "y": data.get('y', 0),
            "dist": data.get('dist', 100),
            "is_ko": data.get('is_ko', False)
        }
        tag = engine.judge_tag(move_data)
        commentary = engine.generate_commentary(move_data)
        return jsonify({
            "tag": tag,
            "commentary": commentary
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)
