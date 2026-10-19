import copy
import unittest

from analysis_logic import build_move_analyses
from review_selection import build_game_review
from review_summary import build_structured_review_summary
from structured_explanation import (
    render_auto_commentary,
    render_detailed_commentary,
)


def position(winrate, score, recommended_wr, recommended_score, actual_wr, actual_score):
    return {
        "rootInfo": {
            "winrate": winrate,
            "scoreLead": score,
            "visits": 100,
        },
        "moveInfos": [
            {
                "move": "D16",
                "order": 0,
                "visits": 60,
                "prior": 0.4,
                "winrate": recommended_wr,
                "scoreLead": recommended_score,
                "pv": ["D16", "E16", "D15"],
            },
            {
                "move": "Q4",
                "order": 1,
                "visits": 20,
                "prior": 0.2,
                "winrate": actual_wr,
                "scoreLead": actual_score,
                "pv": ["Q4", "R4", "Q3"],
            },
        ],
    }


def mirrored_records():
    black_positions = {
        0: position(0.70, 4.0, 0.74, 5.0, 0.64, 3.0),
        1: position(0.55, 2.0, 0.58, 2.5, 0.54, 1.5),
    }
    white_positions = {
        0: position(0.30, -4.0, 0.26, -5.0, 0.36, -3.0),
        1: position(0.45, -2.0, 0.42, -2.5, 0.46, -1.5),
    }
    black = build_move_analyses([["B", "Q4"]], black_positions)[0]
    white = build_move_analyses([["W", "Q4"]], white_positions)[0]
    return black, white


def normalize_player_text(text):
    return text.replace("黑棋", "落子方").replace("白棋", "落子方")


class PerspectiveParityTests(unittest.TestCase):
    def setUp(self):
        self.black, self.white = mirrored_records()

    def test_root_winrate_and_score_are_mover_normalized(self):
        self.assertAlmostEqual(self.black["mover_winrate_before"], 0.70)
        self.assertAlmostEqual(self.white["mover_winrate_before"], 0.70)
        self.assertAlmostEqual(self.black["mover_winrate_after"], 0.55)
        self.assertAlmostEqual(self.white["mover_winrate_after"], 0.55)
        self.assertAlmostEqual(self.black["mover_score_before"], 4.0)
        self.assertAlmostEqual(self.white["mover_score_before"], 4.0)
        self.assertAlmostEqual(self.black["mover_score_after"], 2.0)
        self.assertAlmostEqual(self.white["mover_score_after"], 2.0)

    def test_observed_losses_are_equal_and_positive(self):
        for key, expected in (
            ("observed_winrate_loss", 0.15),
            ("observed_score_loss", 2.0),
        ):
            self.assertAlmostEqual(self.black[key], expected)
            self.assertAlmostEqual(self.white[key], expected)
            self.assertGreater(self.black[key], 0)
            self.assertGreater(self.white[key], 0)

    def test_candidate_gaps_are_equal_and_positive(self):
        self.assertAlmostEqual(self.black["search_winrate_loss"], 0.10)
        self.assertAlmostEqual(self.white["search_winrate_loss"], 0.10)
        self.assertAlmostEqual(self.black["search_score_loss"], 2.0)
        self.assertAlmostEqual(self.white["search_score_loss"], 2.0)

    def test_raw_candidate_evidence_remains_black_perspective(self):
        black_before = self.black["explanation_evidence"]["before"]
        white_before = self.white["explanation_evidence"]["before"]
        self.assertAlmostEqual(black_before["recommended"]["winrate_black"], 0.74)
        self.assertAlmostEqual(white_before["recommended"]["winrate_black"], 0.26)
        self.assertAlmostEqual(black_before["recommended"]["score_lead_black"], 5.0)
        self.assertAlmostEqual(white_before["recommended"]["score_lead_black"], -5.0)

    def test_recommendation_selection_uses_katago_order_for_both_colors(self):
        self.assertEqual(self.black["best_move"], "D16")
        self.assertEqual(self.white["best_move"], "D16")
        self.assertEqual(
            self.black["explanation_evidence"]["before"]["recommended"]["order"],
            0,
        )
        self.assertEqual(
            self.white["explanation_evidence"]["before"]["recommended"]["order"],
            0,
        )

    def test_importance_is_color_neutral(self):
        self.assertEqual(self.black["importance"], "important")
        self.assertEqual(self.white["importance"], "important")
        self.assertEqual(self.black["importance"], self.white["importance"])
        self.assertAlmostEqual(self.black["winrate_loss"], self.white["winrate_loss"])
        self.assertAlmostEqual(self.black["score_loss"], self.white["score_loss"])

    def test_structured_direct_comparison_is_color_neutral(self):
        black = self.black["structured_explanation"]
        white = self.white["structured_explanation"]
        self.assertTrue(black["direct_comparison"]["usable"])
        self.assertTrue(white["direct_comparison"]["usable"])
        self.assertAlmostEqual(black["direct_comparison"]["winrate_gap"], 0.10)
        self.assertAlmostEqual(white["direct_comparison"]["winrate_gap"], 0.10)
        self.assertAlmostEqual(black["direct_comparison"]["score_gap"], 2.0)
        self.assertAlmostEqual(white["direct_comparison"]["score_gap"], 2.0)

    def test_observed_loss_and_candidate_gap_remain_distinct_for_both(self):
        for item in (self.black, self.white):
            structured = item["structured_explanation"]
            self.assertAlmostEqual(
                structured["severity"]["observed"]["winrate_loss"], 0.15
            )
            self.assertAlmostEqual(
                structured["direct_comparison"]["winrate_gap"], 0.10
            )

    def test_auto_text_is_semantically_mirrored(self):
        black_text = render_auto_commentary(self.black["structured_explanation"])
        white_text = render_auto_commentary(self.white["structured_explanation"])
        self.assertIn("黑棋實戰 Q4", black_text)
        self.assertIn("白棋實戰 Q4", white_text)
        self.assertEqual(
            normalize_player_text(black_text), normalize_player_text(white_text)
        )

    def test_detailed_text_is_semantically_mirrored(self):
        black_text = render_detailed_commentary(self.black["structured_explanation"])
        white_text = render_detailed_commentary(self.white["structured_explanation"])
        self.assertIn("勝率由約 70.0% 變為 55.0%", black_text)
        self.assertIn("勝率由約 70.0% 變為 55.0%", white_text)
        self.assertIn("勝率評估相差約 10.0 個百分點", black_text)
        self.assertIn("勝率評估相差約 10.0 個百分點", white_text)
        self.assertEqual(
            normalize_player_text(black_text), normalize_player_text(white_text)
        )

    def test_geometric_directional_facts_are_identical(self):
        black_direction = self.black["structured_explanation"]["directional_evidence"]
        white_direction = self.white["structured_explanation"]["directional_evidence"]
        self.assertEqual(black_direction, white_direction)

    def test_review_selection_is_color_neutral(self):
        black_review = build_game_review([copy.deepcopy(self.black)], total_moves=1)
        white_review = build_game_review([copy.deepcopy(self.white)], total_moves=1)
        self.assertEqual(
            black_review["highlights"][0]["selection"]["severity_basis"],
            white_review["highlights"][0]["selection"]["severity_basis"],
        )
        self.assertEqual(
            black_review["highlights"][0]["move_number"],
            white_review["highlights"][0]["move_number"],
        )

    def test_review_summary_is_color_neutral(self):
        def review_records(record):
            earlier = copy.deepcopy(record)
            later = copy.deepcopy(record)
            for item, move_number in ((earlier, 1), (later, 10)):
                item["move_number"] = move_number
                item["structured_explanation"]["move"]["number"] = move_number

            later["importance"] = "decisive"
            later["observed_winrate_loss"] = 0.30
            later["observed_score_loss"] = 5.0
            later["winrate_loss"] = 0.30
            later["score_loss"] = 5.0
            severity = later["structured_explanation"]["severity"]
            severity["observed"]["winrate_loss"] = 0.30
            severity["observed"]["score_loss"] = 5.0
            severity["combined_importance_basis"]["winrate_loss"] = 0.30
            severity["combined_importance_basis"]["score_loss"] = 5.0
            return [earlier, later]

        black_review = build_game_review(
            review_records(self.black), total_moves=10
        )
        white_review = build_game_review(
            review_records(self.white), total_moves=10
        )
        black_summary = build_structured_review_summary(black_review)
        white_summary = build_structured_review_summary(white_review)
        self.assertEqual(black_summary, white_summary)
        self.assertEqual(black_summary["priority"]["primary_move"], 10)
        self.assertEqual(black_summary["review_order"], [1, 10])
        self.assertEqual(
            black_summary["largest_observed_changes"]["winrate"]["move_number"],
            10,
        )
        self.assertEqual(
            black_summary["largest_observed_changes"]["score"]["move_number"],
            10,
        )


if __name__ == "__main__":
    unittest.main()
