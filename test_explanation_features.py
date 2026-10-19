import copy
import unittest

from analysis_logic import build_move_analyses
from explanation_features import (
    EXPLANATION_FEATURES_SCHEMA_VERSION,
    build_explanation_features,
    candidate_distribution,
    classify_locality,
    compare_moves,
    locality_thresholds,
    move_distances,
    opponent_reply_features,
    pv_locality,
    recent_play_features,
    region_of,
)


def evidence_candidate(move, *, pv=None, reliable=True, found=True, order=0):
    return {
        "found": found,
        "move": move,
        "order": order if found else None,
        "visits": 30 if found else None,
        "prior": 0.2 if found else None,
        "winrate_black": 0.6 if found else None,
        "score_lead_black": 2.0 if found else None,
        "pv": list(pv or []),
        "reliable": reliable if found else False,
        "reliability_reason": (
            "sufficient_visits"
            if found and reliable
            else "insufficient_visits" if found else "missing_candidate"
        ),
    }


def phase1_evidence(
    *,
    actual="M6",
    recommended="E14",
    actual_pv=None,
    recommended_pv=None,
    reply="F14",
    candidates=None,
):
    actual_item = evidence_candidate(actual, pv=actual_pv or [actual, "N6"])
    recommended_item = evidence_candidate(
        recommended,
        pv=recommended_pv or [recommended, "F14"],
    )
    reply_item = evidence_candidate(reply, pv=[reply, "E13"])
    return {
        "schema_version": 1,
        "value_perspective": "black",
        "before": {
            "root_visits": 100,
            "minimum_reliable_visits": 5,
            "recommended": recommended_item,
            "actual": actual_item,
            "candidates": candidates
            if candidates is not None
            else [recommended_item, actual_item],
        },
        "after": {
            "root_visits": 100,
            "minimum_reliable_visits": 5,
            "opponent_best_response": reply_item,
        },
    }


class RegionAndDistanceTests(unittest.TestCase):
    def test_19_board_region_mapping(self):
        expected = {
            "A19": "top-left",
            "K19": "top",
            "T19": "top-right",
            "A10": "left",
            "K10": "center",
            "T10": "right",
            "A1": "bottom-left",
            "K1": "bottom",
            "T1": "bottom-right",
        }
        self.assertEqual(
            {move: region_of(move, 19) for move in expected}, expected
        )

    def test_13_board_region_mapping_and_boundaries(self):
        self.assertEqual(region_of("E13", 13), "top-left")
        self.assertEqual(region_of("F13", 13), "top")
        self.assertEqual(region_of("K13", 13), "top-right")
        self.assertEqual(region_of("G7", 13), "center")
        self.assertEqual(region_of("E1", 13), "bottom-left")
        self.assertEqual(region_of("F1", 13), "bottom")

    def test_9_board_region_mapping_and_boundaries(self):
        self.assertEqual(region_of("C9", 9), "top-left")
        self.assertEqual(region_of("D9", 9), "top")
        self.assertEqual(region_of("G9", 9), "top-right")
        self.assertEqual(region_of("E5", 9), "center")
        self.assertEqual(region_of("C1", 9), "bottom-left")
        self.assertEqual(region_of("D1", 9), "bottom")

    def test_same_adjacent_and_board_size_aware_locality(self):
        self.assertEqual(
            move_distances("D4", "D4", 19), {"manhattan": 0, "chebyshev": 0}
        )
        self.assertEqual(
            move_distances("D4", "E5", 19), {"manhattan": 2, "chebyshev": 1}
        )
        self.assertEqual(classify_locality("D4", "E5", 19), "near")
        self.assertEqual(classify_locality("D4", "H4", 19), "medium")
        self.assertEqual(classify_locality("D4", "Q16", 19), "far")
        self.assertEqual(
            locality_thresholds(19),
            {"near_max_chebyshev": 3, "far_min_chebyshev": 8},
        )
        self.assertEqual(
            locality_thresholds(13),
            {"near_max_chebyshev": 2, "far_min_chebyshev": 6},
        )
        self.assertEqual(
            locality_thresholds(9),
            {"near_max_chebyshev": 2, "far_min_chebyshev": 4},
        )

    def test_cross_region_boundary_can_still_be_near(self):
        comparison = compare_moves("G10", "H10", 19)
        self.assertTrue(comparison["usable"])
        self.assertFalse(comparison["same_region"])
        self.assertEqual(comparison["chebyshev_distance"], 1)
        self.assertEqual(comparison["locality"], "near")

    def test_pass_invalid_and_missing_coordinates_are_unusable(self):
        self.assertIsNone(region_of("PASS", 19))
        self.assertIsNone(region_of("I10", 19))
        self.assertIsNone(region_of(None, 19))
        self.assertIsNone(move_distances("PASS", "D4", 19))
        self.assertFalse(compare_moves("PASS", "D4", 19)["usable"])
        self.assertFalse(compare_moves("D4", "Z99", 19)["usable"])


class PvAndReplyTests(unittest.TestCase):
    def test_recommended_pv_can_be_concentrated(self):
        result = pv_locality(
            ["E14", "F14", "E13", "D14", "PASS"], "E14", 19
        )
        self.assertTrue(result["usable"])
        self.assertEqual(result["total_board_moves"], 4)
        self.assertEqual(result["pass_moves"], 1)
        self.assertEqual(result["moves_near_anchor"], 4)
        self.assertEqual(result["near_ratio"], 1.0)
        self.assertTrue(result["stays_local"])
        self.assertEqual(result["dominant_region"], "top-left")

    def test_recommended_pv_can_be_spatially_dispersed(self):
        result = pv_locality(["E14", "T1", "A1", "T19"], "E14", 19)
        self.assertTrue(result["usable"])
        self.assertEqual(result["moves_near_anchor"], 1)
        self.assertEqual(result["near_ratio"], 0.25)
        self.assertFalse(result["stays_local"])
        self.assertIsNone(result["dominant_region"])

    def test_actual_pv_unavailable_is_not_false_locality(self):
        missing = pv_locality(
            [], "M6", 19, candidate_found=False, candidate_reliable=False
        )
        unreliable = pv_locality(
            ["M6", "N6"], "M6", 19, candidate_reliable=False
        )
        self.assertFalse(missing["usable"])
        self.assertEqual(missing["unusable_reason"], "candidate_missing")
        self.assertIsNone(missing["stays_local"])
        self.assertFalse(unreliable["usable"])
        self.assertEqual(unreliable["unusable_reason"], "candidate_unreliable")
        self.assertIsNone(unreliable["stays_local"])

    def test_reliable_actual_pv_can_be_local(self):
        result = pv_locality(["M6", "N6", "M7", "N7"], "M6", 19)
        self.assertTrue(result["usable"])
        self.assertTrue(result["stays_local"])

    def test_opponent_reply_can_return_near_recommendation(self):
        reply = evidence_candidate("F14", pv=["F14", "E13"])
        result = opponent_reply_features(reply, "E14", "M6", 19)
        self.assertTrue(result["usable"])
        self.assertTrue(result["near_original_recommendation"])
        self.assertFalse(result["near_actual_move"])

    def test_opponent_reply_can_remain_near_actual(self):
        reply = evidence_candidate("N6", pv=["N6", "M7"])
        result = opponent_reply_features(reply, "E14", "M6", 19)
        self.assertTrue(result["usable"])
        self.assertFalse(result["near_original_recommendation"])
        self.assertTrue(result["near_actual_move"])

    def test_missing_opponent_reply_is_unusable(self):
        reply = evidence_candidate(None, found=False)
        result = opponent_reply_features(reply, "E14", "M6", 19)
        self.assertFalse(result["usable"])
        self.assertEqual(result["unusable_reason"], "candidate_missing")
        self.assertIsNone(result["near_original_recommendation"])
        self.assertIsNone(result["near_actual_move"])


class ContextAndDistributionTests(unittest.TestCase):
    def setUp(self):
        self.local_history = [
            ["B", "D14"],
            ["W", "E15"],
            ["B", "F14"],
            ["W", "D13"],
            ["B", "E13"],
            ["W", "F13"],
            ["B", "M6"],
        ]

    def test_recent_moves_can_be_concentrated(self):
        result = recent_play_features(
            self.local_history, 7, "M6", "E14", 19
        )
        self.assertTrue(result["usable"])
        self.assertEqual(result["usable_moves"], 6)
        self.assertEqual(result["dominant_region"], "top-left")
        self.assertEqual(result["concentration_ratio"], 1.0)

    def test_recent_moves_can_be_dispersed_without_fake_dominant_region(self):
        history = [
            ["B", "A19"],
            ["W", "K19"],
            ["B", "T19"],
            ["W", "A1"],
            ["B", "K1"],
            ["W", "T1"],
            ["B", "K10"],
        ]
        result = recent_play_features(history, 7, "K10", "D4", 19)
        self.assertTrue(result["usable"])
        self.assertIsNone(result["dominant_region"])
        self.assertIsNone(result["actual_stays_near_recent_play"])
        self.assertIsNone(result["recommended_stays_near_recent_play"])

    def test_actual_can_leave_while_recommendation_stays_near_recent_play(self):
        result = recent_play_features(
            self.local_history, 7, "M6", "E14", 19
        )
        self.assertFalse(result["actual_stays_near_recent_play"])
        self.assertTrue(result["recommended_stays_near_recent_play"])

    def test_candidate_distribution_concentrated_and_ignores_unreliable(self):
        candidates = [
            evidence_candidate("E14"),
            evidence_candidate("F14", order=1),
            evidence_candidate("E13", order=2),
            evidence_candidate("T1", reliable=False, order=3),
        ]
        result = candidate_distribution(candidates, 19)
        self.assertTrue(result["usable"])
        self.assertEqual(result["usable_candidate_count"], 3)
        self.assertEqual(result["ignored_unreliable_candidates"], 1)
        self.assertEqual(result["distinct_regions"], 1)
        self.assertEqual(result["dominant_region"], "top-left")
        self.assertTrue(result["spatially_concentrated"])

    def test_candidate_distribution_can_be_dispersed(self):
        candidates = [
            evidence_candidate("E14"),
            evidence_candidate("M6", order=1),
            evidence_candidate("T1", order=2),
        ]
        result = candidate_distribution(candidates, 19)
        self.assertTrue(result["usable"])
        self.assertEqual(result["distinct_regions"], 3)
        self.assertIsNone(result["dominant_region"])
        self.assertFalse(result["spatially_concentrated"])

    def test_empty_candidates_are_unusable_not_false(self):
        result = candidate_distribution([], 19)
        self.assertFalse(result["usable"])
        self.assertEqual(result["unusable_reason"], "insufficient_reliable_candidates")
        self.assertIsNone(result["spatially_concentrated"])

    def test_feature_extraction_does_not_mutate_phase1_evidence(self):
        evidence = phase1_evidence()
        original = copy.deepcopy(evidence)
        build_explanation_features(evidence, self.local_history, 7)
        self.assertEqual(evidence, original)


class Phase2IntegrationTests(unittest.TestCase):
    def test_130_style_fixture_produces_spatial_facts_only(self):
        history = [
            ["B", "D14"],
            ["W", "E15"],
            ["B", "F14"],
            ["W", "D13"],
            ["B", "E13"],
            ["W", "F13"],
            ["B", "M6"],
        ]
        evidence = phase1_evidence(
            actual="M6",
            recommended="E14",
            actual_pv=["M6", "N6", "M7", "N7"],
            recommended_pv=["E14", "F14", "E13", "D14"],
            reply="F14",
        )
        features = build_explanation_features(evidence, history, 7)

        self.assertEqual(features["schema_version"], 1)
        self.assertEqual(features["actual_region"], "bottom")
        self.assertEqual(features["recommended_region"], "top-left")
        self.assertFalse(features["actual_recommended"]["same_region"])
        self.assertEqual(features["actual_recommended"]["locality"], "far")
        self.assertTrue(features["recommended_pv"]["stays_local"])
        self.assertTrue(features["actual_pv"]["stays_local"])
        self.assertTrue(
            features["opponent_reply"]["near_original_recommendation"]
        )
        self.assertFalse(features["recent_play"]["actual_stays_near_recent_play"])
        self.assertTrue(
            features["recent_play"]["recommended_stays_near_recent_play"]
        )
        forbidden = {"category", "confidence", "principle", "explanation"}
        self.assertTrue(forbidden.isdisjoint(features))

    def test_build_move_analyses_adds_features_without_changing_evidence(self):
        before = {
            "rootInfo": {"winrate": 0.6, "scoreLead": 2.0, "visits": 100},
            "moveInfos": [
                {
                    "move": "D4",
                    "order": 0,
                    "visits": 80,
                    "prior": 0.5,
                    "winrate": 0.6,
                    "scoreLead": 2.0,
                    "pv": ["D4", "E4"],
                }
            ],
        }
        after = {
            "rootInfo": {"winrate": 0.59, "scoreLead": 1.8, "visits": 100},
            "moveInfos": [
                {
                    "move": "E4",
                    "order": 0,
                    "visits": 80,
                    "prior": 0.5,
                    "winrate": 0.59,
                    "scoreLead": 1.8,
                    "pv": ["E4", "D5"],
                }
            ],
        }
        record = build_move_analyses(
            [["B", "D4"]], {0: before, 1: after}, board_size=13
        )[0]

        self.assertEqual(
            record["explanation_evidence"]["schema_version"], 1
        )
        self.assertEqual(
            record["explanation_features"]["schema_version"],
            EXPLANATION_FEATURES_SCHEMA_VERSION,
        )
        self.assertEqual(record["explanation_features"]["board_size"], 13)
        self.assertEqual(record["best_move"], "D4")
        self.assertEqual(record["best_pv"], ["D4", "E4"])


if __name__ == "__main__":
    unittest.main()
