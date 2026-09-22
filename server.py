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
from flask import Flask, request, jsonify
from flask_cors import CORS
from sgfmill import sgf
from sgf_utils import (
    get_capture_counts,
    get_initial_stones_from_game,
    get_moves_from_game,
)
from logos_engine import LogosEngine

app = Flask(__name__)
CORS(app)

engine = LogosEngine(corpus_path='logosgo_corpus_full.csv')

KATAGO_EXEC = "katago"
MODEL_FILE = "/Users/ouo1010/Desktop/go_project/model.bin.gz"
CONFIG_FILE = "/Users/ouo1010/Desktop/go_project/analysis.cfg"


class KataGoError(RuntimeError):
    pass


class KataGoClient:
    """共用一個 KataGo analysis 行程，並依 query id 分派回應。"""

    def __init__(self, executable, model_file, config_file):
        self.executable = executable
        self.model_file = model_file
        self.config_file = config_file
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
            print(f"啟動共用 KataGo: {cmd}")
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

    def query(self, payload, timeout=60):
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
            with self._write_lock:
                if process.poll() is not None or process.stdin is None:
                    raise KataGoError("KataGo 尚未就緒或已停止")
                process.stdin.write(json.dumps(payload) + "\n")
                process.stdin.flush()

            deadline = time.monotonic() + timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise KataGoError(f"KataGo 分析逾時（{timeout} 秒）")
                try:
                    response = response_queue.get(timeout=remaining)
                except queue.Empty as exc:
                    raise KataGoError(f"KataGo 分析逾時（{timeout} 秒）") from exc
                if "error" in response:
                    raise KataGoError(str(response["error"]))
                if not response.get("isDuringSearch", False):
                    return response
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


katago_client = KataGoClient(KATAGO_EXEC, MODEL_FILE, CONFIG_FILE)
atexit.register(katago_client.close)

# 全域分析狀態（取消機制）
current_analysis_id = None
analysis_lock = threading.Lock()


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

        start = time.time()
        collected = 0
        winrates_raw = {}

        for i in range(1, total_steps + 1, step_interval):

            # ★ 取消檢查：每手分析前確認是否仍是最新請求
            with analysis_lock:
                if current_analysis_id != my_id:
                    print(f"偵測到新棋譜，中止分析 {my_id[:8]}")
                    return jsonify({"status": "cancelled", "message": "新棋譜已匯入"}), 409

            if time.time() - start > 300:
                print("分析超時，提早結束")
                break

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
            }
            if initial_stones:
                query["initialStones"] = initial_stones

            if has_katago:
                try:
                    res = katago_client.query(query, timeout=45)
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
        query = {
            "id": query_id,
            "moves": moves,
            "rules": rule_set,
            "komi": float(komi),
            "boardXSize": 19,
            "boardYSize": 19,
            "maxVisits": 500,
            "includeOwnership": True,
            "includeOwnershipStdev": True,
        }
        if initial_stones:
            query["initialStones"] = initial_stones
        print(
            f"開始形勢判斷 {query_id[:17]}: "
            f"實戰 {move_count} 手、試下 {len(moves) - move_count} 手"
        )
        response = katago_client.query(query, timeout=45)

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
    except ValueError as exc:
        print(f"形勢判斷請求格式錯誤: {exc}")
        return jsonify({"status": "error", "message": str(exc)}), 400
    except KataGoError as exc:
        diagnostics = katago_client.diagnostics()
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
