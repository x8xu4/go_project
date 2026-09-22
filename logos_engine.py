import math

import pandas as pd


GTP_COLUMNS = "ABCDEFGHJKLMNOPQRST"


class LogosEngine:
    """Turn factual KataGo output into conservative teaching text."""

    def __init__(self, corpus_path="logosgo_corpus_full.csv"):
        self.df = pd.read_csv(corpus_path)
        self.df["標籤名稱"] = self.df["標籤名稱"].str.strip()

    def get_line(self, x, y):
        return min(x + 1, y + 1, 19 - x, 19 - y)

    def _move_xy(self, move):
        if not isinstance(move, str) or move.lower() == "pass":
            return None
        move = move.upper()
        if len(move) < 2 or move[0] not in GTP_COLUMNS:
            return None
        try:
            row = int(move[1:])
        except ValueError:
            return None
        if not 1 <= row <= 19:
            return None
        return GTP_COLUMNS.index(move[0]), 19 - row

    def _move_distance(self, first, second):
        a = self._move_xy(first)
        b = self._move_xy(second)
        if a is None or b is None:
            return None
        return abs(a[0] - b[0]) + abs(a[1] - b[1])

    def judge_tag(self, move_data):
        """保留舊 API，但只在資料足夠時套用棋理標籤。"""
        importance = move_data.get("importance")
        if importance == "decisive":
            return "勝負手 / 重大失誤"
        if importance == "important":
            return "重要手"
        if importance == "notice":
            return "值得注意"

        wr_change = float(move_data.get("winrate_change", 0) or 0)
        score_change = float(move_data.get("score_lead_change", 0) or 0)
        if wr_change < -0.1 or score_change < -10:
            return "敗著 / 遺憾手"
        if move_data.get("is_ko", False):
            return "消劫" if move_data.get("is_resolve_ko", False) else "劫材製造"
        if move_data.get("is_contact", False):
            return "定型 / 封鎖"
        if move_data.get("is_tenuki", False):
            return "脫先 (手拔)"

        ownership = move_data.get("ownership")
        if isinstance(ownership, (int, float)):
            if ownership < -0.6:
                return "打入 / 破空"
            if abs(ownership) < 0.2:
                return "侵消 / 勢力消長點"

        dist = move_data.get("dist")
        x = move_data.get("x")
        y = move_data.get("y")
        if all(isinstance(value, (int, float)) for value in (dist, x, y)):
            if dist > 5 and self.get_line(int(x), int(y)) in (3, 4):
                return "搶佔大場"
        return "普通手"

    def _importance_title(self, record):
        importance = record.get("importance", "ordinary")
        if importance == "decisive":
            return "勝負手" if record.get("crossed_even") else "重大失誤"
        if importance == "important":
            return "重要手"
        if importance == "notice":
            return "值得注意"
        return "普通手"

    def generate_auto_commentary(self, record):
        """只對客觀上重要的棋步自動產生較完整說明。"""
        title = self._importance_title(record)
        player_name = "黑方" if record.get("player") == "B" else "白方"
        wr_loss = float(record.get("winrate_loss", 0) or 0) * 100
        score_loss = float(record.get("score_loss", 0) or 0)
        best_move = record.get("best_move")
        actual_move = record.get("actual_move")
        if record.get("importance") == "ordinary":
            return (
                "【普通手】KataGo 未偵測到這手造成顯著局勢變化。"
                "若想了解選點與推薦變化，可按「提問／為什麼？」。"
            )
        change = f"{player_name}約損失 {wr_loss:.1f}% 勝率、{score_loss:.1f} 目"
        if best_move and best_move != actual_move:
            suggestion = f"；分析前的一選是 {best_move}，實戰為 {actual_move}"
        elif best_move == actual_move:
            suggestion = "；實戰命中 KataGo 一選"
        else:
            suggestion = ""
        return f"【{title}】{change}{suggestion}。"

    def generate_detailed_commentary(self, record):
        """按需解說，只使用傳入的 KataGo 事實。"""
        title = self._importance_title(record)
        player_name = "黑方" if record.get("player") == "B" else "白方"
        move_number = int(record.get("move_number", 0) or 0)
        actual_move = record.get("actual_move") or "未知"
        best_move = record.get("best_move")
        before = float(record.get("mover_winrate_before", 0.5) or 0.5) * 100
        after = float(record.get("mover_winrate_after", 0.5) or 0.5) * 100
        wr_loss = float(record.get("winrate_loss", 0) or 0) * 100
        score_loss = float(record.get("score_loss", 0) or 0)
        search_wr_loss = float(record.get("search_winrate_loss", 0) or 0) * 100
        search_score_loss = float(record.get("search_score_loss", 0) or 0)
        paragraphs = [
            f"第 {move_number} 手由{player_name}下在 {actual_move}，分類為「{title}」。",
            (
                f"以落子方視角看，勝率由 {before:.1f}% 變為 {after:.1f}%；"
                f"綜合前後局面與搜尋候選，估計損失 {wr_loss:.1f}% 勝率、"
                f"{score_loss:.1f} 目。"
            ),
        ]
        if best_move == actual_move:
            paragraphs.append(
                "實戰著就是分析前的 KataGo 一選，因此數值變動不代表選點錯誤。"
            )
        elif best_move:
            distance = self._move_distance(actual_move, best_move)
            if distance is not None and distance >= 8:
                comparison = (
                    f"KataGo 較希望改下 {best_move}，兩點相距很遠，表示問題主要是"
                    "全盤方向或脫先時機，而不只是局部次序。"
                )
            else:
                comparison = (
                    f"KataGo 較希望改下 {best_move}；推薦點與實戰點在同一局部附近，"
                    "差異更可能來自局部次序、棋形效率或先後手。"
                )
            paragraphs.append(comparison)
            if record.get("search_comparison_reliable"):
                paragraphs.append(
                    f"在同一次候選搜尋中，一選相對實戰著約多保留 "
                    f"{search_wr_loss:.1f}% 勝率與 {search_score_loss:.1f} 目；"
                    "這是直接候選比較，不是由文字模型猜測。"
                )
            elif record.get("actual_move_searched"):
                paragraphs.append(
                    "KataGo對這一手的評估資料還不夠充分，因此這裡主要根"
                    "據落子前後的勝率與目數變化，判斷這手棋對局勢的影響。"
                )
            else:
                paragraphs.append(
                    "目前無法準確判斷這一手的具體問題，但從落子前後"
                    "的局勢變化，可以看出這手棋造成了一定的損失。"
                )
        else:
            paragraphs.append("本次 KataGo 回傳沒有可用的一選資料，無法做候選著比較。")
        pv = record.get("best_pv")
        if isinstance(pv, list) and pv:
            paragraphs.append(
                "KataGo 推薦變化的開頭是：" + " → ".join(str(move) for move in pv[:6]) + "。"
            )
        if math.isclose(wr_loss, 0.0, abs_tol=0.5) and score_loss < 1.0:
            paragraphs.append(
                "這手的客觀損失很小；若只是想比較不同下法，應把它視為風格與後續"
                "計畫的差異，而不是硬判成好手或壞手。"
            )
        return "\n\n".join(paragraphs)

    def generate_commentary(self, move_data):
        """舊 endpoint 相容。"""
        if "move_number" in move_data:
            return self.generate_auto_commentary(move_data)
        tag = self.judge_tag(move_data)
        wr_change = float(move_data.get("winrate_change", 0) or 0)
        winrate = float(move_data.get("winrate", 0.5) or 0.5)
        score_lead = float(move_data.get("score_lead", 0) or 0)
        if abs(wr_change) > 0.1:
            mood = "語料_勝率逆轉"
        elif winrate > 0.7 and score_lead > 8:
            mood = "語料_優勢穩固"
        else:
            mood = "語料_勝率持平"
        try:
            comment = self.df.loc[self.df["標籤名稱"] == tag, mood].values[0]
            return f"【{tag}】{comment}"
        except Exception:
            return f"【{tag}】目前資料不足以做更具體的棋理判定。"
