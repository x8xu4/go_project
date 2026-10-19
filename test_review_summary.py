import copy
import unittest

from review_selection import build_game_review
from review_summary import (
    ReviewSummaryLimitation,
    build_review_summary,
    build_structured_review_summary,
    render_auto_review_summary,
    render_detailed_review_summary,
)
from test_review_selection import review_record


def make_review(records, *, total_moves=100):
    return build_game_review(records, total_moves=total_moves)


def summary_for(records, *, total_moves=100):
    return build_review_summary(make_review(records, total_moves=total_moves))


class ReviewSummaryTests(unittest.TestCase):
    def test_zero_highlights(self):
        summary = summary_for([])
        self.assertEqual(summary["overview"]["highlight_count"], 0)
        self.assertIsNone(summary["priority"]["primary_move"])
        self.assertIn(
            ReviewSummaryLimitation.NO_HIGHLIGHTS,
            summary["limitations"],
        )
        self.assertEqual(
            summary["rendered"]["auto"],
            "目前沒有選出足夠明確的主要復盤重點。",
        )

    def test_one_highlight_has_natural_grammar(self):
        summary = summary_for([review_record(40)])
        auto = summary["rendered"]["auto"]
        detailed = summary["rendered"]["detailed"]
        self.assertIn("1 個主要復盤重點", auto)
        self.assertNotIn("其中", auto)
        self.assertNotIn("其中", detailed)
        self.assertIn("limited_highlights", summary["limitations"])

    def test_two_highlights(self):
        summary = summary_for([review_record(20), review_record(60)])
        self.assertEqual(summary["overview"]["highlight_count"], 2)
        self.assertEqual(summary["review_order"], [20, 60])
        self.assertIn("2 個主要復盤重點", summary["rendered"]["auto"])

    def test_five_highlights(self):
        records = [review_record(move) for move in (10, 30, 50, 70, 90)]
        summary = summary_for(records)
        self.assertEqual(summary["overview"]["highlight_count"], 5)
        self.assertEqual(summary["review_order"], [10, 30, 50, 70, 90])

    def test_eight_highlights(self):
        records = [
            review_record(move, "decisive", winrate_loss=0.50)
            for move in (10, 30, 50, 70, 90, 110, 130, 150)
        ]
        summary = summary_for(records, total_moves=160)
        self.assertEqual(summary["overview"]["highlight_count"], 8)
        self.assertEqual(len(summary["review_order"]), 8)

    def test_primary_move_uses_severity_not_earliest_move(self):
        records = [
            review_record(10, "important", winrate_loss=0.15),
            review_record(50, "decisive", winrate_loss=0.45),
        ]
        summary = summary_for(records)
        self.assertEqual(summary["priority"]["primary_move"], 50)
        self.assertIn("第 50 手開始", summary["rendered"]["auto"])

    def test_review_order_remains_chronological(self):
        records = [
            review_record(80, "important", winrate_loss=0.13),
            review_record(20, "decisive", winrate_loss=0.50),
            review_record(50, "important", winrate_loss=0.20),
        ]
        summary = summary_for(records)
        self.assertEqual(summary["review_order"], [20, 50, 80])

    def test_largest_observed_winrate_change(self):
        records = [
            review_record(20, observed_winrate_loss=0.13),
            review_record(60, observed_winrate_loss=0.25),
        ]
        summary = summary_for(records)
        self.assertEqual(
            summary["largest_observed_changes"]["winrate"]["move_number"],
            60,
        )
        self.assertAlmostEqual(
            summary["largest_observed_changes"]["winrate"]["observed_loss"],
            0.25,
        )

    def test_largest_observed_score_change(self):
        records = [
            review_record(20, score_loss=8.0, observed_score_loss=8.0),
            review_record(60, score_loss=10.0, observed_score_loss=10.0),
        ]
        summary = summary_for(records)
        self.assertEqual(
            summary["largest_observed_changes"]["score"]["move_number"],
            60,
        )

    def test_winrate_and_score_largest_can_differ(self):
        records = [
            review_record(
                20,
                "decisive",
                winrate_loss=0.45,
                score_loss=2.0,
                observed_winrate_loss=0.45,
                observed_score_loss=2.0,
            ),
            review_record(
                60,
                "decisive",
                winrate_loss=0.23,
                score_loss=18.0,
                observed_winrate_loss=0.20,
                observed_score_loss=18.0,
            ),
        ]
        summary = summary_for(records)
        self.assertEqual(
            summary["largest_observed_changes"]["winrate"]["move_number"],
            20,
        )
        self.assertEqual(
            summary["largest_observed_changes"]["score"]["move_number"],
            60,
        )

    def test_missing_winrate_is_safe(self):
        review = make_review([review_record(20)])
        basis = review["highlights"][0]["selection"]["severity_basis"]
        basis["observed_winrate_loss"] = None
        summary = build_review_summary(review)
        self.assertIsNone(summary["largest_observed_changes"]["winrate"])
        self.assertIsNotNone(summary["largest_observed_changes"]["score"])

    def test_missing_score_is_safe(self):
        review = make_review([review_record(20)])
        basis = review["highlights"][0]["selection"]["severity_basis"]
        basis["observed_score_loss"] = None
        summary = build_review_summary(review)
        self.assertIsNone(summary["largest_observed_changes"]["score"])
        self.assertIsNotNone(summary["largest_observed_changes"]["winrate"])

    def test_phase_distribution_is_descriptive(self):
        records = [review_record(10), review_record(50), review_record(90)]
        summary = summary_for(records, total_moves=90)
        self.assertEqual(
            summary["phase_distribution"],
            {"opening": 1, "middle": 1, "endgame": 1, "unknown": 0},
        )

    def test_summary_has_no_classifier_dependency(self):
        review = make_review([review_record(20, classification="local_sequence")])
        summary = build_review_summary(review)
        self.assertEqual(summary["overview"]["highlight_count"], 1)

    def test_classifier_absent_is_safe(self):
        review = make_review([review_record(20, classification=None)])
        self.assertEqual(
            build_review_summary(review)["priority"]["primary_move"], 20
        )

    def test_classifier_uncertain_is_safe(self):
        review = make_review([review_record(20, classification="uncertain")])
        self.assertEqual(
            build_review_summary(review)["priority"]["primary_move"], 20
        )

    def test_renderers_do_not_expose_go_categories(self):
        summary = summary_for([review_record(20)])
        text = summary["rendered"]["auto"] + summary["rendered"]["detailed"]
        self.assertNotIn("local_sequence", text)
        self.assertNotIn("global_direction", text)
        self.assertNotIn("uncertain", text)

    def test_renderers_do_not_claim_tenuki(self):
        summary = summary_for([review_record(20)])
        self.assertNotIn("脫先", str(summary["rendered"]))

    def test_renderers_do_not_claim_urgent(self):
        summary = summary_for([review_record(20)])
        self.assertNotIn("急場", str(summary["rendered"]))

    def test_renderers_do_not_claim_attack_or_defense(self):
        summary = summary_for([review_record(20)])
        text = str(summary["rendered"])
        self.assertNotIn("攻擊", text)
        self.assertNotIn("防守", text)

    def test_candidate_gap_is_not_used_as_observed_loss(self):
        record = review_record(
            20,
            winrate_loss=0.20,
            observed_winrate_loss=0.03,
        )
        summary = summary_for([record])
        largest = summary["largest_observed_changes"]["winrate"]
        self.assertAlmostEqual(largest["observed_loss"], 0.03)
        detailed = summary["rendered"]["detailed"]
        self.assertIn("3.0 個百分點", detailed)
        self.assertNotIn("20.0 個百分點", detailed)

    def test_auto_summary_is_concise(self):
        records = [review_record(move) for move in (10, 30, 50, 70, 90)]
        auto = summary_for(records)["rendered"]["auto"]
        self.assertLessEqual(len(auto.splitlines()), 3)

    def test_detailed_summary_is_evidence_grounded(self):
        summary = summary_for([review_record(20), review_record(60)])
        detailed = summary["rendered"]["detailed"]
        self.assertIn("客觀評估變化", detailed)
        self.assertIn("勝率估計下降幅度最大", detailed)
        self.assertIn("不對整盤棋推測", detailed)

    def test_summary_does_not_supplement_highlights(self):
        review = make_review([review_record(20), review_record(60)])
        summary = build_review_summary(review)
        self.assertEqual(summary["overview"]["highlight_count"], 2)
        self.assertEqual(summary["review_order"], [20, 60])

    def test_input_review_is_not_mutated(self):
        review = make_review([review_record(20), review_record(60)])
        original = copy.deepcopy(review)
        build_review_summary(review)
        self.assertEqual(review, original)

    def test_identical_input_is_deterministic(self):
        review = make_review([review_record(20), review_record(60)])
        self.assertEqual(build_review_summary(review), build_review_summary(review))

    def test_game_review_shape_remains_backward_compatible(self):
        review = make_review([review_record(20)])
        existing_keys = set(review)
        review["review_summary"] = build_review_summary(review)
        self.assertTrue(existing_keys.issubset(review))
        self.assertIn("highlights", review)
        self.assertIn("suppressed", review)
        self.assertIn("review_summary", review)

    def test_phase4b_highlights_remain_unchanged(self):
        review = make_review([review_record(20), review_record(60)])
        original_highlights = copy.deepcopy(review["highlights"])
        build_structured_review_summary(review)
        render_auto_review_summary(build_structured_review_summary(review))
        render_detailed_review_summary(build_structured_review_summary(review))
        self.assertEqual(review["highlights"], original_highlights)


if __name__ == "__main__":
    unittest.main()
