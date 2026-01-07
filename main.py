import subprocess
import json
import time
import numpy as np
import matplotlib.pyplot as plt
import math
import sys

# 引入你的 SGF 工具
from sgf_utils import get_moves_from_sgf

from logos_engine import LogosEngine

# === 在這裡加入字體設定 ===
plt.rcParams['font.sans-serif'] = ['Arial Unicode MS'] 
plt.rcParams['axes.unicode_minus'] = False
# ========================

# ====================================================
# --- 設定區 (請根據你的環境修改) ---
# ====================================================
KATAGO_EXEC = "katago"   
MODEL_FILE = "model.bin.gz"  
CONFIG_FILE = "analysis.cfg" 

# [設定]
SGF_FILE = "game-3.sgf"    
TARGET_STEP = 45           # 單手分析模式：想分析第幾手？

# ----------------------------------------------------
# 1. 基礎工具與提子邏輯
# ----------------------------------------------------
def parse_coord(coord_str):
    if coord_str == 'pass' or not coord_str: return None
    letters = 'ABCDEFGHJKLMNOPQRST'
    x = letters.find(coord_str[0].upper())
    y = int(coord_str[1:]) - 1
    return x, y

def calculate_distance(coord1, coord2):
    """計算兩個座標之間的歐幾里得距離"""
    p1 = parse_coord(coord1)
    p2 = parse_coord(coord2)
    if not p1 or not p2: return 999.0 
    return math.sqrt((p1[0] - p2[0])**2 + (p1[1] - p2[1])**2)

def find_all_groups(board, board_size=19):
    """ 掃描目前棋盤上的所有棋塊及其氣數 """
    visited = set()
    groups = []
    for (x, y), player in board.items():
        if (x, y) not in visited:
            group_stones = []
            queue = [(x, y)]
            visited.add((x, y))
            liberties = set()
            
            while queue:
                curr_x, curr_y = queue.pop(0)
                group_stones.append((curr_x, curr_y))
                for dx, dy in [(0,1), (0,-1), (1,0), (-1,0)]:
                    nx, ny = curr_x+dx, curr_y+dy
                    if 0 <= nx < board_size and 0 <= ny < board_size:
                        if (nx, ny) in board:
                            if board[(nx, ny)] == player and (nx, ny) not in visited:
                                visited.add((nx, ny))
                                queue.append((nx, ny))
                        else:
                            liberties.add((nx, ny))
            groups.append({'player': player, 'stones': group_stones, 'lib_count': len(liberties)})
    return groups

def update_board_state(moves, board_size=19):
    """ 模擬每一手棋，處理提子邏輯並回傳最終盤面棋子 """
    current_board = {} 
    
    for player, coord in moves:
        pos = parse_coord(coord)
        if pos is None: continue 
        
        current_board[pos] = player
        
        opponent = 'W' if player == 'B' else 'B'
        groups = find_all_groups(current_board, board_size)
        
        for g in groups:
            if g['player'] == opponent and g['lib_count'] == 0:
                for sx, sy in g['stones']:
                    if (sx, sy) in current_board:
                        del current_board[(sx, sy)]
        
        groups = find_all_groups(current_board, board_size)
        for g in groups:
            if g['player'] == player and g['lib_count'] == 0:
                for sx, sy in g['stones']:
                    if (sx, sy) in current_board:
                        del current_board[(sx, sy)]

    letters = 'ABCDEFGHJKLMNOPQRST'
    final_list = []
    for (x, y), p in current_board.items():
        final_list.append([p, f"{letters[x]}{y+1}"])
    return final_list

# ----------------------------------------------------
# 2. 繪圖核心 (支援變化圖 & 勝率曲線)
# ----------------------------------------------------
def plot_ownership(ownership_data, moves, highlight_coords=None, marker_label="AI", title_suffix="", board_size=19, pv_sequence=None):
    display_stones = update_board_state(moves, board_size)
    
    ownership_matrix = np.array(ownership_data).reshape(board_size, board_size)
    ownership_matrix = np.flipud(ownership_matrix)
    
    plt.imshow(ownership_matrix, cmap='RdBu', vmin=-1, vmax=1, alpha=0.9, origin='lower') 
    
    for i in range(board_size):
        lw = 2.5 if i == 0 or i == board_size - 1 else 1.0
        plt.plot([0, board_size-1], [i, i], color='black', linewidth=lw)
        plt.plot([i, i], [0, board_size-1], color='black', linewidth=lw)
    plt.plot([0, 0], [0, board_size-1], color='black', linewidth=2.5)
    plt.plot([board_size-1, board_size-1], [0, board_size-1], color='black', linewidth=2.5)

    ax = plt.gca()
    for spine in ax.spines.values(): spine.set_visible(False)
    plt.xlim(-0.5, board_size - 0.5) 
    plt.ylim(-0.5, board_size - 0.5) 
    
    star_points = [3, 9, 15] 
    for x in star_points:
        for y in star_points:
            plt.plot(x, y, 'o', color='black', markersize=6)
    
    for player, coord in display_stones:
        x, y = parse_coord(coord)
        color = 'black' if player == 'B' else 'white'
        edge_color = 'white' if player == 'B' else 'black' 
        plt.plot(x, y, 'o', color=color, markersize=12, markeredgecolor=edge_color, zorder=3)
    
    if pv_sequence:
        last_player, _ = moves[-1]
        pv_player = 'W' if last_player == 'B' else 'B'
        for i, coord in enumerate(pv_sequence):
            if i >= 8: break 
            x, y = parse_coord(coord)
            if x is None: continue
            current_color = 'black' if pv_player == 'B' else 'white'
            text_color = 'white' if pv_player == 'B' else 'black'
            plt.plot(x, y, 'o', color=current_color, markersize=11, alpha=0.5, zorder=4)
            plt.text(x, y, str(i + 1), color=text_color, fontsize=8, ha='center', va='center', fontweight='bold', zorder=5)
            pv_player = 'W' if pv_player == 'B' else 'B'

    if highlight_coords and highlight_coords != 'pass':
        x, y = parse_coord(highlight_coords)       
        plt.plot(x, y, 'o', color='lime', markersize=20, markeredgecolor='black', alpha=0.8, zorder=4)
        plt.text(x - 0.4, y - 0.35, marker_label, color='black', fontsize=11, fontweight='bold', zorder=5)

    ticks = np.arange(board_size)
    letters = 'ABCDEFGHJKLMNOPQRST'
    plt.xticks(ticks, list(letters))
    plt.yticks(ticks, ticks + 1) 
    plt.title(title_suffix)
    plt.gca().set_aspect('equal', adjustable='box') 

def plot_full_game_graph(move_numbers, winrates, sgf_path):
    """ 【新增】畫出整盤棋的勝率曲線圖 """
    plt.figure(figsize=(12, 6))
    
    # 畫出曲線
    plt.plot(move_numbers, winrates, color='black', linewidth=1.5, label='黑棋勝率')
    
    # 填充顏色 (50% 以上藍色，以下紅色)
    # plt.fill_between(move_numbers, winrates, 0.5, where=(np.array(winrates) >= 0.5), interpolate=True, color='blue', alpha=0.1)
    # plt.fill_between(move_numbers, winrates, 0.5, where=(np.array(winrates) <= 0.5), interpolate=True, color='red', alpha=0.1)
    
    plt.axhline(y=0.5, color='gray', linestyle='--', alpha=0.8)
    
    plt.title(f"整盤棋勝率波動圖 ({sgf_path})", fontsize=14)
    plt.xlabel("手數", fontsize=12)
    plt.ylabel("黑棋勝率", fontsize=12)
    plt.ylim(-0.05, 1.05)
    plt.yticks(np.arange(0, 1.1, 0.1), [f"{x:.0%}" for x in np.arange(0, 1.1, 0.1)])
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.show()

# ----------------------------------------------------
# 3. 與 KataGo 通訊
# ----------------------------------------------------
def analyze_move_sequences(katago_process, initial_moves, query_id, visits=500):
    """ 
    修改：增加 visits 參數，讓勝率曲線分析可以跑快一點 (預設 500)
    """
    query = {
        "id": query_id, "moves": initial_moves, "rules": "chinese", "komi": 7.5,
        "boardXSize": 19, "boardYSize": 19, "includeOwnership": True,
        "maxVisits": visits, "maxTime": 10.0     
    }
    try:
        katago_process.stdin.write(json.dumps(query) + "\n")
        katago_process.stdin.flush()
    except BrokenPipeError:
        return None
    
    ans = {'ownership': None, 'moveInfos': None, 'rootInfo': None}
    start_time = time.time()
    while time.time() - start_time < 30.0: # 稍微放寬超時時間
        line = katago_process.stdout.readline()
        if not line: continue
        res = json.loads(line)
        if res.get('id') == query_id:
            if 'ownership' in res: ans['ownership'] = res['ownership']
            if 'moveInfos' in res: ans['moveInfos'] = res['moveInfos']
            if 'rootInfo' in res: ans['rootInfo'] = res['rootInfo']
            if ans['ownership'] and (ans['moveInfos'] or query_id == "Base"): return ans
    return None

# ----------------------------------------------------
# 4. 主執行邏輯 (雙模式)
# ----------------------------------------------------

# 模式 A: 單手深度分析 (你原本的功能)
def run_single_move_analysis(sgf_path, target_step):
    print(f"🚀 [模式 A] 啟動 KataGo 單手分析...")
    try:
        cmd = [KATAGO_EXEC, "analysis", "-model", MODEL_FILE, "-config", CONFIG_FILE]
        katago = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
    except FileNotFoundError:
        print(f"❌ 找不到 KataGo 執行檔！"); return

    print(f"📂 正在讀取棋譜：{sgf_path} ...")
    try:
        moves_data = get_moves_from_sgf(sgf_path, target_step=None)
        required_len = target_step + 1
        if len(moves_data) < required_len:
            print(f"❌ 棋譜長度不足！"); katago.terminate(); return

        base_moves = moves_data[:target_step]     
        real_move_data = moves_data[target_step]  
        real_player, real_coord = real_move_data[0], real_move_data[1]
        print(f"✅ 載入成功。分析第 {target_step+1} 手：{real_player} 下在 {real_coord}")
    except Exception as e:
        print(f"❌ 讀取 SGF 失敗: {e}"); katago.terminate(); return

    print(f"🤖 AI 正在思考 (Visits=500)...")
    base_data = analyze_move_sequences(katago, base_moves, "Base", visits=500)
    if not base_data: print("❌ AI 分析失敗"); katago.terminate(); return
    ai_best_move = base_data['moveInfos'][0]['move']
    
    results = []
    scenarios = [("實戰 (Real)", real_coord), ("AI 推薦", ai_best_move)]
    for label, move_coord in scenarios:
        test_sequence = base_moves + [[real_player, move_coord]]
        resp = analyze_move_sequences(katago, test_sequence, label, visits=500)
        if resp:
            pv = resp['moveInfos'][0].get('pv', [])
            results.append({
                'label': label, 'moves': test_sequence, 'winrate': resp['rootInfo']['winrate'],
                'ownership': resp['ownership'], 'played_point': move_coord, 'pv': pv 
            })

    katago.terminate()

    # 繪圖與報告 (保持不變)
    fig, axes = plt.subplots(1, 2, figsize=(14, 7))
    for i, res in enumerate(results):
        plt.sca(axes[i])
        m_label = "You" if i == 0 and res['played_point'] != ai_best_move else ("Perfect!" if i==0 else "AI")
        plot_ownership(res['ownership'], res['moves'], highlight_coords=res['played_point'], pv_sequence=res.get('pv'), marker_label=m_label, 
                     title_suffix=f"{res['label']}: {res['played_point']}\n(勝率: {res['winrate']:.1%})")
    plt.tight_layout()
    plt.show()
    plt.close('all')

    real_res, ai_res = results[0], results[1]
    loss = ai_res['winrate'] - real_res['winrate']
    dist = calculate_distance(real_res['played_point'], ai_res['played_point'])
    
    print("\n" + "="*70)
    print(f"## 📊 實戰分析報告 (第 {target_step+1} 手)")
    print(f"1. 實戰選點：{real_res['played_point']} (勝率：{real_res['winrate']:.1%})")
    print(f"2. AI 推薦 ：{ai_res['played_point']} (勝率：{ai_res['winrate']:.1%})")
    print(f"📉 勝率變動：{'-' if loss > 0 else '+'}{abs(loss):.1%}")
    print(f"📏 選點距離：{dist:.1f}")
    
    LOSS_THRESHOLD = 0.08
    TENUKI_THRESHOLD = 6.0 
    print(f"\n**【AI 老師講評】**")
    if loss <= -0.01:
        print("🌟 **超越 AI 的妙手！** 這步棋非常精湛。")
    elif loss > LOSS_THRESHOLD:
        if dist > TENUKI_THRESHOLD: print("❌ **脫先不當！** 忽略了局部急所。")
        else: print("❌ **局部失誤！** 手法效率較低。")
    elif loss > 0.03:
        if dist > TENUKI_THRESHOLD: print("⚠️ **勉強的脫先。**")
        else: print("⚠️ **次佳的一手。**")
    else:
        print("✅ **精彩的一手！** 思路正確。")
    print("="*70 + "\n")


# 模式 B: 整盤勝率曲線分析 (新增的功能)
def run_full_game_analysis(sgf_path):
    print(f"🚀 [模式 B] 啟動 KataGo 整盤分析...")
    try:
        cmd = [KATAGO_EXEC, "analysis", "-model", MODEL_FILE, "-config", CONFIG_FILE]
        katago = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
    except FileNotFoundError:
        print(f"❌ 找不到 KataGo 執行檔！"); return

    print(f"🎮 開始整盤掃描：{sgf_path}")
    all_moves = get_moves_from_sgf(sgf_path, target_step=None)
    total_steps = len(all_moves)
    
    move_numbers = []
    winrates = []
    
    # 設定掃描間隔 (step=1 每手都跑，step=2 跳著跑比較快)
    step_interval = 2 
    print(f"   總手數：{total_steps}，掃描間隔：{step_interval}，每手 Visits：100 (快速模式)")

    for i in range(1, total_steps + 1, step_interval):
        current_moves = all_moves[:i]
        query_id = f"Step_{i}"
        
        # 使用較低的 visits (100) 以加快速度
        resp = analyze_move_sequences(katago, current_moves, query_id, visits=100)
        
        if resp and resp.get('rootInfo'):
            wr = resp['rootInfo']['winrate']
            move_numbers.append(i)
            winrates.append(wr)
            # 進度條
            print(f"\rAnalyzing... {i}/{total_steps} (Black Win Rate: {wr:.1%})", end="")

    print("\n✅ 分析完成！產生圖表中...")
    katago.terminate()
    
    # 畫圖
    plot_full_game_graph(move_numbers, winrates, sgf_path)
    plt.close('all')


if __name__ == "__main__":
    # 預設值
    current_sgf = SGF_FILE 

    while True:
        print("\n" + "═"*35)
        print(f" 🏯 圍棋 AI 互動分析工具")
        print(f" 📂 目前檔案: {current_sgf}")
        print(" " + "═"*35)
        print(" 1: 變更分析的 SGF 檔案")
        print(" 2: 針對【特定一手】深度分析 (含 PV 圖)")
        print(" 3: 跑【整盤棋】的勝率曲線")
        print(" q: 離開程式")
        print("-" * 35)
        
        choice = input("請選擇功能: ").strip().lower()

        if choice == '1':
            new_file = input("請輸入 SGF 檔名 (例如 game.sgf): ").strip()
            if new_file:
                current_sgf = new_file
                print(f"✅ 已切換檔案為: {current_sgf}")

        elif choice == '2':
            try:
                step_str = input("請輸入要分析的手數 (例如 50): ").strip()
                target_step = int(step_str) - 1 # 轉為程式用的 index
                # 執行單手分析，並傳入參數
                run_single_move_analysis(current_sgf, target_step)
            except ValueError:
                print("❌ 請輸入有效的數字。")

        elif choice == '3':
            # 執行整盤分析，傳入參數
            run_full_game_analysis(current_sgf)

        elif choice == 'q':
            print("感謝使用，再見！")
            break
        else:
            print("\n❌ 輸入錯誤，請重新輸入。")