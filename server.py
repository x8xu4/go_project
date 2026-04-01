import subprocess
import json
import os
from flask import Flask, request, jsonify
from flask_cors import CORS
from sgfmill import sgf
from sgf_utils import get_moves_from_sgf
from logos_engine import LogosEngine

app = Flask(__name__)
CORS(app)  # 允許 Flutter Web 跨網域存取

engine = LogosEngine(corpus_path='logosgo_corpus_full.csv')

# --- 設定 KataGo 路徑  ---
KATAGO_EXEC = "katago"   
MODEL_FILE = "model.bin.gz"  
CONFIG_FILE = "analysis.cfg" 

@app.route('/analyze_sgf', methods=['POST'])
def analyze_sgf():
    try:
        data = request.json
        sgf_content = data.get('sgf_content')
        if not sgf_content:
            return jsonify({"error": "No SGF content provided"}), 400
        
        # --- 自動抓取貼目 ---
        game = sgf.Sgf_game.from_bytes(sgf_content.encode('utf-8'))
        # 讀取 KM，如果找不到就預設 7.5
        raw_komi = game.root.get("KM") if game.root.has_property("KM") else 75
        # 野狐等平台會把 6.5 存成 65 或 650，需要除以 10
        if raw_komi > 150:
            komi = raw_komi / 100
        elif raw_komi > 15:
            komi = raw_komi / 10
        else:
            komi = float(raw_komi)
        # 根據貼目推測規則 (選配)
        rule_set = "chinese" if komi == 7.5 else "korean"

        # 寫入暫存檔
        temp_filename = "temp_upload.sgf"
        with open(temp_filename, "w", encoding="utf-8") as f:
            f.write(sgf_content)

        # 讀取手數
        all_moves = get_moves_from_sgf(temp_filename, target_step=None)
        total_steps = len(all_moves)
        print(f"讀取手數: {total_steps}")  # 加這行

        # 啟動 KataGo
        cmd = [KATAGO_EXEC, "analysis", "-model", MODEL_FILE, "-config", CONFIG_FILE]
        print(f"啟動 KataGo: {cmd}")  # 加這行
        katago = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1
        )

        # 逐手分析（間隔 2 手加速）
        move_numbers = []
        winrates_raw = {}

        step_interval = 2
        target_count = len(range(1, total_steps + 1, step_interval))
        for i in range(1, total_steps + 1, step_interval):
            current_moves = all_moves[:i]
            query_id = f"Step_{i}"
            query = {
                "id": query_id,
                "moves": current_moves,
                "rules": "chinese",
                "komi": float(komi),
                "boardXSize": 19,
                "boardYSize": 19,
                "maxVisits": 100,
                "includeOwnership": False,
            }
            katago.stdin.write(json.dumps(query) + "\n")
            katago.stdin.flush()

        # 收集結果
        print(f"目標收集數: {target_count}")
        import time
        start = time.time()
        collected = 0

        while collected < target_count and time.time() - start < 300:
            line = katago.stdout.readline()
            if not line:
                continue
            print(f"KataGo 回傳: {line[:100]}")  
            if collected >= target_count * 0.8:
                break
            try:
                res = json.loads(line)
                if 'warning' in res:  # 跳過 warning 訊息
                    continue
                qid = res.get('id', '')
                if qid.startswith('Step_'):
                    step_num = int(qid.split('_')[1])
                    if 'rootInfo' in res:
                        wr = res['rootInfo']['winrate']
                        winrates_raw[step_num] = wr
                        collected += 1
                        print(f"收到 Step_{step_num} rootInfo 勝率: {wr:.3f} 已收{collected}/{target_count}")
                    elif 'moveInfos' in res and len(res['moveInfos']) > 0:
                        wr = res['moveInfos'][0].get('winrate', 0.5)
                        winrates_raw[step_num] = wr
                        collected += 1
                        rint(f"收到 Step_{step_num} moveInfos 勝率: {wr:.3f} 已收{collected}/{target_count}")
                    else:
                        print(f"Step_{step_num} 沒有勝率資料，keys: {list(res.keys())}")
            except:
                continue
        print(f"實際收集數: {collected}")
        print(f"winrates_raw: {list(winrates_raw.items())[:5]}")  # 看前5筆
        katago.terminate()

        # 補齊每手勝率（用線性插值填滿 step_interval 的空隙）
        winrates = []
        sorted_steps = sorted(winrates_raw.keys())
        for i in range(total_steps + 1):
            if i in winrates_raw:
                winrates.append(round(winrates_raw[i], 4))
            elif sorted_steps:
                # 找最近的值填入
                closest = min(sorted_steps, key=lambda x: abs(x - i))
                winrates.append(round(winrates_raw[closest], 4))
            else:
                winrates.append(0.5)

        # 找敗著（勝率變動超過 15%）
        blunders = []
        for i in range(1, len(winrates)):
            diff = winrates[i] - winrates[i-1]
            # 黑棋勝率下降（白棋失誤）或黑棋勝率上升超過門檻（黑棋失誤）
            if diff > 0.15:  # 黑棋勝率上升 → 白棋在第i-1手失誤
                blunders.append(i - 1)
            elif diff < -0.15:  # 黑棋勝率下降 → 黑棋在第i手失誤
                blunders.append(i)
        print(f"最終 winrates 長度: {len(winrates)}, winrates_raw 筆數: {len(winrates_raw)}")
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
    
@app.route('/get_commentary', methods=['POST'])
def get_commentary():
    try:
        data = request.json
        # 這些 move_data 是從 Flutter 傳過來的當前手數資訊
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
        
        # 呼叫 logos_engine.py 裡的邏輯
        tag = engine.judge_tag(move_data)
        commentary = engine.generate_commentary(move_data)
        
        return jsonify({
            "tag": tag,
            "commentary": commentary
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
if __name__ == '__main__':
    # 執行伺服器在 5001 端口
    app.run(host='0.0.0.0', port=5001, debug=True)

"""
cd ~/Desktop/go_project
python3 server.py
"""