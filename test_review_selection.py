import copy
import unittest

from review_selection import (
    REVIEW_HARD_MAX,
    ReviewSelectionConfig,
    SelectionReason,
    SuppressionReason,
    build_game_review,
)
from structured_explanation import build_structured_explanation


def review_record(
    move_number,
    importance="important",
    *,
    winrate_loss=None,
    score_loss=0.0,
    observed_winrate_loss=None,
    observed_score_loss=None,
    recommendation=True,
    variation=True,
    actual_found=True,
    actual_reliable=True,
    classification="uncertain",
):
    if winrate_loss is None:
        winrate_loss = {
            "ordinary": 0.01,
            "notice": 0.06,
            "important": 0.15,
            "decisive": 0.30,
        }[importance]
    if observed_winrate_loss is None:
        observed_winrate_loss = winrate_loss
    if observed_score_loss is None:
        observed_score_loss = score_loss
    actual_move = "D4"
    recommended_move = "Q16" if recommendation else None
    recommended = {
        "found": recommendation,
        "move": recommended_move,
        "order": 0 if recommendation else None,
        "reliable": recommendation,
        "winrate_black": 0.70 if recommendation else None,
        "score_lead_black": 5.0 if recommendation else None,
    }
    actual = {
        "found": actual_found,
        "move": actual_move,
        "order": 1 if actual_found else None,
        "reliable": actual_found and actual_reliable,
        "winrate_black": 0.50 if actual_found else None,
        "score_lead_black": 3.0 if actual_found else None,
    }
    record = {
        "move_number": move_number,
        "player": "B",
        "actual_move": actual_move,
        "best_move": recommended_move,
        "best_pv": ["Q16", "D16"] if recommendation else [],
        "pv_reliable": recommendation and variation,
        "importance": importance,
        "mover_winrate_before": 0.70,
        "mover_winrate_after": 0.70 - observed_winrate_loss,
        "observed_winrate_loss": observed_winrate_loss,
        "mover_score_before": 5.0,
        "mover_score_after": 5.0 - observed_score_loss,
        "observed_score_loss": observed_score_loss,
        "winrate_loss": winrate_loss,
        "score_loss": score_loss,
        "explanation_evidence": {
            "schema_version": 1,
            "value_perspective": "black",
            "before": {
                "recommended": recommended,
                "actual": actual,
            },
        },
    }
    if classification is not None:
        record["explanation_classification"] = {
            "category": classification,
            "confidence": "low",
        }
    record["structured_explanation"] = build_structured_explanation(record)
    return record


def selected_moves(review):
    return [item["move_number"] for item in review["highlights"]]


class ReviewSelectionTests(unittest.TestCase):
    def test_empty_game(self):
        review = build_game_review([])
        self.assertEqual(review["summary"]["total_moves"], 0)
        self.assertEqual(review["summary"]["candidate_count"], 0)
        self.assertEqual(review["highlights"], [])
        self.assertEqual(review["suppressed"], [])

    def test_no_important_moves(self):
        records = [review_record(1, "ordinary"), review_record(2, "notice")]
        review = build_game_review(records)
        self.assertEqual(review["summary"]["candidate_count"], 0)
        self.assertEqual(selected_moves(review), [])

    def test_one_important_move(self):
        review = build_game_review([review_record(12)])
        self.assertEqual(selected_moves(review), [12])

    def test_fewer_than_target_highlights_are_not_padded(self):
        records = [review_record(10), review_record(30)]
        review = build_game_review(records, total_moves=100)
        self.assertEqual(selected_moves(review), [10, 30])
        self.assertEqual(review["summary"]["selected_count"], 2)

    def test_more_than_max_highlights_are_capped(self):
        records = [
            review_record(move, "decisive", winrate_loss=0.50)
            for move in range(10, 130, 10)
        ]
        review = build_game_review(records, total_moves=130)
        self.assertEqual(len(review["highlights"]), REVIEW_HARD_MAX)
        self.assertTrue(
            any(
                item["reason"] == SuppressionReason.REVIEW_MAXIMUM_CAPACITY
                for item in review["suppressed"]
            )
        )

    def test_hard_max_never_exceeds_eight(self):
        records = [
            review_record(move, "decisive", winrate_loss=0.50)
            for move in range(10, 130, 10)
        ]
        config = ReviewSelectionConfig(target_highlights=20, max_highlights=20)
        review = build_game_review(records, config=config)
        self.assertLessEqual(len(review["highlights"]), 8)
        self.assertEqual(review["summary"]["max_highlights"], 8)

    def test_decisive_outranks_weaker_important(self):
        records = [
            review_record(10, "important", winrate_loss=0.21),
            review_record(30, "decisive", winrate_loss=0.23),
        ]
        config = ReviewSelectionConfig(target_highlights=1, max_highlights=1)
        self.assertEqual(
            selected_moves(build_game_review(records, config=config)), [30]
        )

    def test_deterministic_tie_break_prefers_lower_move_number(self):
        records = [review_record(40), review_record(20)]
        config = ReviewSelectionConfig(target_highlights=1, max_highlights=1)
        self.assertEqual(
            selected_moves(build_game_review(records, config=config)), [20]
        )

    def test_nearby_duplicate_suppression(self):
        records = [review_record(100), review_record(101)]
        review = build_game_review(records)
        self.assertEqual(len(review["highlights"]), 1)
        self.assertEqual(len(review["suppressed"]), 1)
        self.assertEqual(
            review["suppressed"][0]["reason"],
            SuppressionReason.NEARBY_LOWER_SEVERITY,
        )

    def test_stronger_nearby_move_survives(self):
        records = [
            review_record(100, winrate_loss=0.13),
            review_record(102, winrate_loss=0.20),
        ]
        review = build_game_review(records)
        self.assertEqual(selected_moves(review), [102])
        self.assertEqual(review["suppressed"][0]["suppressed_by_move"], 102)

    def test_nearby_two_decisive_can_survive_when_justified(self):
        records = [
            review_record(100, "decisive", winrate_loss=0.50),
            review_record(102, "decisive", winrate_loss=0.42),
        ]
        review = build_game_review(records)
        self.assertEqual(selected_moves(review), [100, 102])
        second = review["highlights"][1]
        self.assertIn(
            SelectionReason.ADDITIONAL_STRONG_DECISIVE,
            second["selection"]["reasons"],
        )

    def test_distant_important_moves_both_survive(self):
        records = [review_record(100), review_record(104)]
        review = build_game_review(records)
        self.assertEqual(selected_moves(review), [100, 104])

    def test_ordinary_move_is_never_selected(self):
        records = [review_record(5, "ordinary"), review_record(10)]
        self.assertEqual(selected_moves(build_game_review(records)), [10])

    def test_notice_fallback_is_explicit_and_only_when_needed(self):
        notices = [review_record(10, "notice"), review_record(30, "notice")]
        self.assertEqual(selected_moves(build_game_review(notices)), [])
        enabled = ReviewSelectionConfig(allow_notice_fallback=True)
        review = build_game_review(notices, config=enabled)
        self.assertEqual(selected_moves(review), [10, 30])
        self.assertTrue(review["summary"]["notice_fallback_used"])

        mixed = notices + [review_record(50, "important")]
        mixed_review = build_game_review(mixed, config=enabled)
        self.assertEqual(selected_moves(mixed_review), [50])
        self.assertFalse(mixed_review["summary"]["notice_fallback_used"])

    def test_actual_candidate_missing_can_still_be_selected(self):
        record = review_record(50, actual_found=False)
        review = build_game_review([record])
        self.assertEqual(selected_moves(review), [50])
        self.assertEqual(
            review["highlights"][0]["explanation"]["interpretation"]["level"],
            "recommendation_only",
        )

    def test_recommendation_missing_can_still_be_selected(self):
        record = review_record(50, recommendation=False, variation=False)
        review = build_game_review([record])
        self.assertEqual(selected_moves(review), [50])
        self.assertFalse(review["highlights"][0]["recommendation_available"])

    def test_variation_availability_is_support_not_severity(self):
        stronger = review_record(20, winrate_loss=0.20, variation=False)
        weaker = review_record(40, winrate_loss=0.13, variation=True)
        config = ReviewSelectionConfig(target_highlights=1, max_highlights=1)
        review = build_game_review([weaker, stronger], config=config)
        self.assertEqual(selected_moves(review), [20])

    def test_classifier_uncertain_can_still_be_selected(self):
        record = review_record(50, classification="uncertain")
        self.assertEqual(selected_moves(build_game_review([record])), [50])

    def test_classification_absent_can_still_be_selected(self):
        record = review_record(50, classification=None)
        self.assertEqual(selected_moves(build_game_review([record])), [50])

    def test_highlights_are_finally_ordered_by_move_number(self):
        records = [
            review_record(80, "important", winrate_loss=0.13),
            review_record(20, "decisive", winrate_loss=0.50),
            review_record(50, "important", winrate_loss=0.20),
        ]
        self.assertEqual(
            selected_moves(build_game_review(records, total_moves=100)),
            [20, 50, 80],
        )

    def test_selection_reasons_are_stable(self):
        review = build_game_review([review_record(50)])
        self.assertEqual(
            review["highlights"][0]["selection"]["reasons"],
            [
                SelectionReason.IMPORTANT_MOVE,
                SelectionReason.LARGE_OBSERVED_CHANGE,
                SelectionReason.RELIABLE_RECOMMENDATION,
                SelectionReason.VARIATION_AVAILABLE,
                SelectionReason.HIGHEST_SEVERITY_IN_CLUSTER,
            ],
        )

    def test_suppression_reason_is_stable(self):
        review = build_game_review(
            [review_record(100, winrate_loss=0.13), review_record(101, winrate_loss=0.20)]
        )
        self.assertEqual(
            review["suppressed"],
            [
                {
                    "move_number": 100,
                    "importance": "important",
                    "suppressed_by_move": 101,
                    "reason": SuppressionReason.NEARBY_LOWER_SEVERITY,
                }
            ],
        )

    def test_input_move_analyses_are_not_mutated(self):
        records = [review_record(20), review_record(40)]
        original = copy.deepcopy(records)
        build_game_review(records)
        self.assertEqual(records, original)

    def test_identical_input_is_deterministic(self):
        records = [review_record(20), review_record(40)]
        self.assertEqual(build_game_review(records), build_game_review(records))

    def test_invalid_structured_explanation_is_transparently_suppressed(self):
        record = review_record(20)
        record["structured_explanation"] = {"schema_version": 1}
        review = build_game_review([record])
        self.assertEqual(selected_moves(review), [])
        self.assertEqual(
            review["suppressed"][0]["reason"],
            SuppressionReason.INVALID_STRUCTURED_EXPLANATION,
        )

    def test_structured_explanation_reference_and_data_are_preserved(self):
        record = review_record(20)
        explanation = record["structured_explanation"]
        review = build_game_review([record])
        selected = review["highlights"][0]["explanation"]
        self.assertIs(selected, explanation)
        self.assertEqual(selected, explanation)


if __name__ == "__main__":
    unittest.main()
