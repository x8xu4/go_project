import subprocess
import json
import os
import threading
import uuid
import time
import shutil
import random
from flask import Flask, request, jsonify
from flask_cors import CORS
from sgfmill import sgf
from sgf_utils import get_moves_from_sgf
from logos_engine import LogosEngine

app = Flask(__name__)
CORS(app)

engine = LogosEngine(corpus_path='logosgo_corpus_full.csv')

KATAGO_EXEC = "katago"
MODEL_FILE = "/Users/ouo1010/Desktop/go_project/model.bin.gz"
CONFIG_FILE = "/Users/ouo1010/Desktop/go_project/analysis.cfg"

# 全域分析狀態（取消機制）
current_analysis_id = None
analysis_lock = threading.Lock()


@app.route('/analyze_sgf', methods=['POST'])
def analyze_sgf():
    global current_analysis_id

    # 產生此次分析的唯一 ID，並取消舊的
    my_id = str(uuid.uuid4())
    with analysis_lock:
        current_analysis_id = my_id
    print(f"新分析開始: {my_id[:8]}")

    katago = None  # 確保 finally 能正確關閉

    try:
        data = request.json
        sgf_content = data.get('sgf_content')
        if not sgf_content:
            return jsonify({"error": "No SGF content provided"}), 400

        # 自動抓取貼目
        game = sgf.Sgf_game.from_bytes(sgf_content.encode('utf-8'))
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

        # 寫入暫存檔
        temp_filename = "temp_upload.sgf"
        with open(temp_filename, "w", encoding="utf-8") as f:
            f.write(sgf_content)

        # 讀取手數
        all_moves = get_moves_from_sgf(temp_filename, target_step=None)
        total_steps = len(all_moves)
        print(f"讀取手數: {total_steps}")

        # 啟動 KataGo
        has_katago = shutil.which(KATAGO_EXEC) is not None

        if has_katago:
            cmd = [KATAGO_EXEC, "analysis", "-model", MODEL_FILE, "-config", CONFIG_FILE]
            print(f"啟動 KataGo: {cmd}")
            katago = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1
            )
        else:
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
                    if katago:
                        katago.terminate()
                    return jsonify({"status": "cancelled", "message": "新棋譜已匯入"}), 409

            if time.time() - start > 300:
                print("分析超時，提早結束")
                break

            current_moves = all_moves[:i]
            query_id = f"Step_{i}"
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

            if katago:
                try:
                    katago.stdin.write(json.dumps(query) + "\n")
                    katago.stdin.flush()
                except BrokenPipeError:
                    print("KataGo 發生 Broken pipe 錯誤，可能已經崩潰退出")
                    break

                # 等待這手的回應
                while True:
                    line = katago.stdout.readline()
                    if not line:
                        break

                    try:
                        res = json.loads(line)
                        if 'warning' in res:
                            continue

                        qid = res.get('id', '')
                        if qid == query_id:
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
                            elif 'error' in res:
                                print(f"KataGo 報錯: {res['error']}")
                            break
                    except Exception as e:
                        print(f"解析 KataGo 回傳失敗: {e}")
                        continue
            else:
                wr = 0.5 + (random.random() * 0.1 - 0.05)
                winrates_raw[i] = wr
                collected += 1

        print(f"實際收集數: {collected}")
        print(f"winrates_raw 前5筆: {list(winrates_raw.items())[:5]}")

        if katago:
            katago.terminate()

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
            if katago and katago.poll() is not None:
                stderr_output = katago.stderr.read()
                if stderr_output:
                    error_msg += f" | 引擎錯誤: {stderr_output.strip()}"
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
        if katago:
            katago.terminate()
        return jsonify({"status": "error", "message": str(e)}), 500


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