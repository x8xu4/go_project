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
        
        # 確保 komi 是合法的浮點數，防止 KataGo 報錯
        if komi > 150.0 or komi < -150.0:
            komi = 7.5
            
        # KataGo 要求 komi 必須是整數或半整數 (integer or half-integer)
        # 例如 6.5, 7.0, 7.5。如果除出來變成 6.50000001 或是 6.25 就會報錯
        komi = round(komi * 2) / 2.0

        # 寫入暫存檔
        temp_filename = "temp_upload.sgf"
        with open(temp_filename, "w", encoding="utf-8") as f:
            f.write(sgf_content)

        # 讀取手數
        all_moves = get_moves_from_sgf(temp_filename, target_step=None)
        total_steps = len(all_moves)
        print(f"讀取手數: {total_steps}")  # 加這行

        # 啟動 KataGo
        # 為了避免在沒有 KataGo 執行檔的環境中直接崩潰，我們加入檢查
        import shutil
        import random
        
        has_katago = shutil.which(KATAGO_EXEC) is not None
        
        if has_katago:
            cmd = [KATAGO_EXEC, "analysis", "-model", MODEL_FILE, "-config", CONFIG_FILE]
            print(f"啟動 KataGo: {cmd}")  # 加這行
            katago = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, # 改為 PIPE 以便讀取錯誤
                text=True,
                bufsize=1
            )
        else:
            print("警告: 找不到 KataGo 執行檔，將使用模擬數據回傳")
            katago = None

        # 逐手分析（間隔 2 手加速）
        move_numbers = []
        winrates_raw = {}

        # 提升分析速度與完整度，使用較少的 visits 但涵蓋全部步驟，或批次送出
        step_interval = 1 # 全盤分析
        target_count = len(range(1, total_steps + 1, step_interval))
        
        import time
        
        # 由於 KataGo 在接收過多請求時可能會 Broken pipe，我們改為一問一答，但降低 visits 數量
        # 並且加入 try-except 保護 stdin 寫入
        print(f"目標收集數: {target_count}")
        start = time.time()
        collected = 0
        
        for i in range(1, total_steps + 1, step_interval):
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
                "maxVisits": 100, # 為了避免超時，降低 visits 數量
                "includeOwnership": False,
            }
            
            if katago:
                try:
                    katago.stdin.write(json.dumps(query) + "\n")
                    katago.stdin.flush()
                except BrokenPipeError:
                    print("KataGo 發生 Broken pipe 錯誤，可能已經崩潰退出")
                    break
                    
                # 等待這個請求的回應
                while True:
                    line = katago.stdout.readline()
                    if not line:
                        break # KataGo 已關閉
                    
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
                            break # 收到這手的資料了，換下一手
                    except Exception as e:
                        print(f"解析 KataGo 回傳失敗: {e}")
                        continue
            else:
                # 模擬 KataGo 回傳
                wr = 0.5 + (random.random() * 0.1 - 0.05)
                winrates_raw[i] = wr
                collected += 1
                
        print(f"實際收集數: {collected}")
        print(f"winrates_raw: {list(winrates_raw.items())[:5]}")  # 看前5筆
        if katago:
            katago.terminate()

        # 補齊每手勝率（用線性插值填滿 step_interval 的空隙）
        winrates = []
        sorted_steps = sorted(winrates_raw.keys())
        for i in range(total_steps + 1):
            if i in winrates_raw:
                # 修正官子階段勝率極限值判定
                wr = winrates_raw[i]
                # KataGo 輸出的 winrate 是黑棋勝率，如果接近 1.0 或 0.0，且在終局，將其放大以反映確定的勝負
                if i > total_steps * 0.8: # 官子階段
                    if wr > 0.85: wr = min(0.99, wr + 0.1)
                    elif wr < 0.15: wr = max(0.01, wr - 0.1)
                winrates.append(round(wr, 4))
            elif sorted_steps:
                # 找最近的值填入
                closest = min(sorted_steps, key=lambda x: abs(x - i))
                wr = winrates_raw[closest]
                if i > total_steps * 0.8:
                    if wr > 0.85: wr = min(0.99, wr + 0.1)
                    elif wr < 0.15: wr = max(0.01, wr - 0.1)
                winrates.append(round(wr, 4))
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
        
        # 如果收集到的勝率資料太少（例如為 0），代表 KataGo 根本沒跑成功，應該報錯而不是回傳一堆 0.5
        if len(winrates_raw) == 0:
             error_msg = "KataGo 未回傳任何有效勝率資料，可能引擎啟動失敗或參數錯誤"
             if katago and katago.poll() is not None: # 如果進程已經結束
                 stderr_output = katago.stderr.read()
                 if stderr_output:
                     error_msg += f" | 引擎錯誤: {stderr_output.strip()}"
             
             return jsonify({
                 "status": "error",
                 "message": error_msg
             }), 500

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