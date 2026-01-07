import os
import json
import subprocess
import signal
import sys
from logos_engine import LogosEngine
from sgf_utils import get_moves_from_sgf

class KataGoTester:
    def __init__(self, katago_path, config_path, model_path):
        self.katago_path = katago_path
        self.config_path = config_path
        self.model_path = model_path
        
        # 啟動 KataGo
        self.proc = subprocess.Popen(
            [self.katago_path, "analysis", "-config", self.config_path, "-model", self.model_path],
            stdin=subprocess.PIPE, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE, 
            encoding="utf-8",
            bufsize=1
        )
        self.logos = LogosEngine()

    def run_test(self, file_path, start_step=20, end_step=30):
        """
        start_step: 從第幾手開始 (1-based)
        end_step: 到第幾手結束
        """
        if not os.path.exists(file_path):
            print(f"❌ 找不到檔案: {file_path}")
            return

        try:
            moves_raw = get_moves_from_sgf(file_path)
            # 將 sgf_utils 的格式轉為數字座標
            formatted_moves = []
            cols = "ABCDEFGHJKLMNOPQRST"
            for m in moves_raw:
                color, c_str = m[0], m[1]
                x = cols.find(c_str[0].upper())
                y = int(c_str[1:]) - 1
                formatted_moves.append([color, x, y, c_str])
        except Exception as e:
            print(f"❌ 解析失敗: {e}")
            return

        # 設定結束手數
        total_moves = len(formatted_moves)
        if end_step is None or end_step > total_moves:
            end_step = total_moves

        print(f"--- 🚀 老狗分析中 (設定範圍: 第 {start_step} ~ {end_step} 手) ---")
        print("💡 提示: 按下 Ctrl+C 可隨時停止分析")

        history = []
        last_wr, last_score = 0.5, 0.0

        try:
            for i in range(end_step):
                m = formatted_moves[i]
                color, x, y, c_str = m[0], m[1], m[2], m[3]
                
                # 更新歷史紀錄 (KataGo 分析需要完整的前序棋譜)
                current_history = [[m[0], m[3]] for m in formatted_moves[:i+1]]

                # 只有在指定範圍內才進行分析與輸出
                if (i + 1) >= start_step:
                    query = {
                        "id": f"test_{i}",
                        "moves": current_history,
                        "rules": "chinese",
                        "boardXSize": 19, "boardYSize": 19,
                        "includeOwnership": True
                    }

                    print(f"正在分析第 {i+1} 手 ({color} {c_str})...", end="\r")
                    self.proc.stdin.write(json.dumps(query) + "\n")
                    self.proc.stdin.flush()
                    
                    line = self.proc.stdout.readline()
                    if not line: break
                    
                    response = json.loads(line)
                    root_info = response.get('rootInfo', response.get('moveInfos', [{}])[0])
                    
                    curr_wr = root_info.get('winrate', 0.5)
                    curr_score = root_info.get('scoreLead', 0.0)

                    analysis_data = {
                        'x': x, 'y': y,
                        'winrate': curr_wr,
                        'winrate_change': curr_wr - last_wr,
                        'score_lead': curr_score,
                        'score_lead_change': curr_score - last_score,
                        'dist': self.calculate_dist(x, y, history),
                        'is_tenuki': self.calculate_dist(x, y, history) > 10,
                        'ownership': response.get('ownership', [0]*361)[x + y*19],
                        'is_ai_first_choice': True 
                    }

                    commentary = self.logos.generate_commentary(analysis_data)
                    print(f"\n第 {i+1} 手 [{color}]: 黑方勝率 {curr_wr:.1%} | 目數差 {curr_score:+.1f}")
                    print(f"🐶 老狗：{commentary}\n")

                    last_wr, last_score = curr_wr, curr_score
                
                # 即使不分析，也要把座標存入 history 以供後續計算距離
                history.append((x, y))

        except KeyboardInterrupt:
            print("\n\n🛑 已收到停止指令，正在關閉引擎...")
        finally:
            self.close()

    def calculate_dist(self, x, y, history):
        if not history: return 100
        lx, ly = history[-1]
        return abs(x - lx) + abs(y - ly)

    def close(self):
        if hasattr(self, 'proc') and self.proc:
            self.proc.stdin.close()
            self.proc.terminate()
            print("👋 引擎已安全退出。")

if __name__ == "__main__":
    base_path = os.path.dirname(os.path.abspath(__file__))
    tester = KataGoTester(
        katago_path="/opt/homebrew/bin/katago",
        config_path=os.path.join(base_path, "analysis.cfg"), 
        model_path=os.path.join(base_path, "model.bin.gz")
    )
    
    # --- 💡 在這裡設定你想看的手數範圍 ---
    # 例如想看第 20 手到第 30 手：
    tester.run_test(os.path.join(base_path, "game-2.sgf"), start_step=20, end_step=30)