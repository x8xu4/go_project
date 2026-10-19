import pandas as pd

from structured_explanation import (
    build_structured_explanation,
    render_auto_commentary,
    render_detailed_commentary,
)


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
        """Render concise V1 commentary from structured objective evidence."""
        structured = record.get("structured_explanation")
        if not isinstance(structured, dict):
            structured = build_structured_explanation(record)
        return render_auto_commentary(structured)

    def generate_detailed_commentary(self, record):
        """Render detailed V1 commentary with evidence-grounded direction."""
        structured = record.get("structured_explanation")
        if not isinstance(structured, dict):
            structured = build_structured_explanation(record)
        return render_detailed_commentary(structured)

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
