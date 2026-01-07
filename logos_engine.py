import pandas as pd
import numpy as np

class LogosEngine:
    def __init__(self, corpus_path='logosgo_corpus_full.csv'):
        # 載入語料庫與規則
        self.df = pd.read_csv(corpus_path)
        self.df['標籤名稱'] = self.df['標籤名稱'].str.strip()

    def get_line(self, x, y):
        """計算棋子所在的線路 (1-10路)"""
        return min(x + 1, y + 1, 19 - x, 19 - y)

    def judge_tag(self, move_data):
        """
        根據 19 個判定邏輯進行分類
        move_data 預計包含: 
        winrate, winrate_change, score_lead, score_lead_change,
        x, y, dist (距離最近棋子), ownership (該點在落子前的數值),
        is_ko (是否為劫爭), is_sente (是否為先手)
        """
        wr_change = move_data.get('winrate_change', 0)
        score_change = move_data.get('score_lead_change', 0)
        score_lead = move_data.get('score_lead', 0)
        winrate = move_data.get('winrate', 0.5)
        dist = move_data.get('dist', 100)
        line = self.get_line(move_data.get('x', 0), move_data.get('y', 0))
        own = move_data.get('ownership', 0) # 落子前的數值

        # --- 1. 心態/局勢標籤 ---
        if wr_change < -0.1 or score_change < -10:
            return '敗著 / 遺憾手'
        if winrate < 0.3 and abs(wr_change) > 0.05:
            return '勝負手 / 反擊'
        if winrate > 0.75 and score_lead > 5 and wr_change < 0 and wr_change > -0.05:
            return '優勢意識 / 妥協'
        
        # --- 2. 先後手與價值標籤 ---
        if move_data.get('is_sente_loss_huge', False): # 假設後端計算了不應的損失
            return '絕對先手 (Absolute Sente)'
        if move_data.get('is_reverse_sente', False):
            return '逆先手 (Reverse Sente)'
        if move_data.get('is_false_sente', False):
            return '虛張聲勢 (False Sente)'

        # --- 3. 戰術/策略標籤 ---
        if move_data.get('is_ko', False):
            return '消劫' if move_data.get('is_resolve_ko', False) else '劫材製造'
        
        if dist > 5 and line in [3, 4]:
            return '搶佔大場'
        
        if move_data.get('is_tenuki', False):
            return '脫先 (手拔)'
            
        if abs(own) < 0.2:
            return '侵消 / 勢力消長點'
        
        if own < -0.6: # 落在對方深處
            return '打入 / 破空'

        if move_data.get('is_contact', False):
            if move_data.get('is_double_hane', False):
                return '連扳 / 壓迫'
            return '定型 / 封鎖'

        if move_data.get('is_probe', False):
            return '(問)試應手'

        if score_change > 2 and move_data.get('is_ai_first_choice', False):
            return '手筋 / 妙手'

        # 預設標籤
        return '簡明處理'

    def generate_commentary(self, move_data):
        """生成老狗解說"""
        tag = self.judge_tag(move_data)
        
        # 決定情緒狀態
        wr_change = move_data.get('winrate_change', 0)
        winrate = move_data.get('winrate', 0.5)
        score_lead = move_data.get('score_lead', 0)
        
        if abs(wr_change) > 0.1:
            mood = '語料_勝率逆轉'
        elif winrate > 0.7 and score_lead > 8:
            mood = '語料_優勢穩固'
        else:
            mood = '語料_勝率持平'

        try:
            # 獲取對應標籤與情緒的語料
            comment = self.df.loc[self.df['標籤名稱'] == tag, mood].values[0]
            return f"【{tag}】{comment}"
        except Exception:
            return f"這手棋屬於 {tag}，棋局正朝向複雜的方向發展。"