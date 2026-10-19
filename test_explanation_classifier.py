import copy
import unittest
from collections import Counter

from analysis_logic import build_move_analyses
from explanation_classifier import (
    EXPLANATION_CLASSIFICATION_SCHEMA_VERSION,
    ReasonId,
    classify_explanation,
)
from explanation_features import build_explanation_features


def candidate(move, *, pv=None, reliable=True, found=True, visits=30):
    return {
        "found": found,
        "move": move,
        "order": 0 if found else None,
        "visits": visits if found else None,
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


def evidence_fixture(
    *,
    actual="E14",
    recommended="F14",
    actual_pv=None,
    recommended_pv=None,
    reply="E13",
    actual_found=True,
    actual_reliable=True,
    recommended_found=True,
    recommended_reliable=True,
):
    actual_item = candidate(
        actual,
        pv=[actual, "E13"] if actual_pv is None else actual_pv,
        found=actual_found,
        reliable=actual_reliable,
        visits=30 if actual_reliable else 1,
    )
    recommended_item = candidate(
        recommended if recommended_found else None,
        pv=(
            [recommended, "F13"]
            if recommended_pv is None
            else recommended_pv
        ),
        found=recommended_found,
        reliable=recommended_reliable,
        visits=30 if recommended_reliable else 1,
    )
    reply_item = candidate(reply, pv=[reply, "E12"])
    return {
        "schema_version": 1,
        "value_perspective": "black",
        "before": {
            "root_visits": 100,
            "minimum_reliable_visits": 5,
            "recommended": recommended_item,
            "actual": actual_item,
            "candidates": [recommended_item, actual_item],
        },
        "after": {
            "root_visits": 100,
            "minimum_reliable_visits": 5,
            "opponent_best_response": reply_item,
        },
    }


def classify_fixture(evidence, history):
    features = build_explanation_features(evidence, history, len(history))
    return classify_explanation(evidence, features), features


LOCAL_HISTORY = [
    ["B", "D14"],
    ["W", "E15"],
    ["B", "F15"],
    ["W", "D13"],
    ["B", "E13"],
    ["W", "F13"],
    ["B", "E14"],
]

GLOBAL_HISTORY = [
    ["B", "D14"],
    ["W", "E15"],
    ["B", "F14"],
    ["W", "D13"],
    ["B", "E13"],
    ["W", "F13"],
    ["B", "M6"],
]


class ConservativeClassifierTests(unittest.TestCase):
    def test_clear_local_sequence_high(self):
        result, _ = classify_fixture(evidence_fixture(), LOCAL_HISTORY)
        self.assertEqual(result["category"], "local_sequence")
        self.assertEqual(result["confidence"], "high")
        self.assertFalse(result["abstained"])
        self.assertIn(ReasonId.RECOMMENDED_PV_LOCAL, result["supporting_evidence"])
        self.assertIn(ReasonId.ACTUAL_PV_LOCAL, result["supporting_evidence"])

    def test_local_sequence_medium_with_one_usable_pv(self):
        evidence = evidence_fixture(actual_pv=[])
        result, _ = classify_fixture(evidence, LOCAL_HISTORY)
        self.assertEqual(result["category"], "local_sequence")
        self.assertEqual(result["confidence"], "medium")
        self.assertIn(ReasonId.ACTUAL_PV_UNUSABLE, result["missing_evidence"])

    def test_near_with_nonlocal_pvs_is_uncertain(self):
        dispersed = ["F14", "T1", "A1", "T19"]
        evidence = evidence_fixture(
            actual_pv=["E14", "T1", "A1", "T19"],
            recommended_pv=dispersed,
        )
        result, _ = classify_fixture(evidence, LOCAL_HISTORY)
        self.assertEqual(result["category"], "uncertain")
        self.assertIn(
            ReasonId.RECOMMENDED_PV_NONLOCAL,
            result["contradictions"],
        )

    def test_soft_context_contradiction_downgrades_local_confidence(self):
        evidence = evidence_fixture()
        features = build_explanation_features(evidence, LOCAL_HISTORY, 7)
        features["recent_play"].update(
            {
                "usable": True,
                "actual_stays_near_recent_play": False,
                "recommended_stays_near_recent_play": False,
            }
        )
        result = classify_explanation(evidence, features)
        self.assertEqual(result["category"], "local_sequence")
        self.assertEqual(result["confidence"], "medium")
        self.assertIn(
            ReasonId.RECENT_PLAY_POINTS_ELSEWHERE,
            result["contradictions"],
        )

    def test_same_region_but_far_conflict_is_uncertain(self):
        evidence = evidence_fixture()
        features = build_explanation_features(evidence, LOCAL_HISTORY, 7)
        features["actual_recommended"]["same_region"] = True
        features["actual_recommended"]["locality"] = "far"
        result = classify_explanation(evidence, features)
        self.assertEqual(result["category"], "uncertain")
        self.assertIn(
            ReasonId.CONFLICTING_CLASSIFICATION_EVIDENCE,
            result["contradictions"],
        )

    def test_cross_region_boundary_but_near_can_be_local_sequence(self):
        evidence = evidence_fixture(
            actual="G10",
            recommended="H10",
            actual_pv=["G10", "G11", "F10"],
            recommended_pv=["H10", "H11", "J10"],
            reply="H11",
        )
        history = LOCAL_HISTORY[:-1] + [["B", "G10"]]
        result, features = classify_fixture(evidence, history)
        self.assertFalse(features["actual_recommended"]["same_region"])
        self.assertEqual(features["actual_recommended"]["locality"], "near")
        self.assertEqual(result["category"], "local_sequence")

    def test_clear_global_direction_high(self):
        result, _ = classify_fixture(self._global_evidence(), GLOBAL_HISTORY)
        self.assertEqual(result["category"], "global_direction")
        self.assertEqual(result["confidence"], "high")
        self.assertIn(
            ReasonId.PVS_LOCAL_AT_SEPARATE_ANCHORS,
            result["supporting_evidence"],
        )

    def test_global_direction_medium_with_one_usable_pv(self):
        evidence = self._global_evidence(actual_pv=[])
        result, _ = classify_fixture(evidence, GLOBAL_HISTORY)
        self.assertEqual(result["category"], "global_direction")
        self.assertEqual(result["confidence"], "medium")

    def test_far_without_pv_evidence_is_uncertain(self):
        evidence = self._global_evidence(actual_pv=[], recommended_pv=[])
        result, _ = classify_fixture(evidence, GLOBAL_HISTORY)
        self.assertEqual(result["category"], "uncertain")
        self.assertIn(
            ReasonId.INSUFFICIENT_INDEPENDENT_EVIDENCE,
            result["missing_evidence"],
        )

    def test_far_with_actual_unreliable_is_uncertain(self):
        evidence = self._global_evidence(actual_reliable=False)
        result, _ = classify_fixture(evidence, GLOBAL_HISTORY)
        self.assertEqual(result["category"], "uncertain")
        self.assertIn(
            ReasonId.ACTUAL_CANDIDATE_UNRELIABLE,
            result["missing_evidence"],
        )

    def test_actual_missing_is_uncertain(self):
        evidence = evidence_fixture(actual_found=False)
        result, _ = classify_fixture(evidence, LOCAL_HISTORY)
        self.assertEqual(result["category"], "uncertain")
        self.assertIn(ReasonId.ACTUAL_CANDIDATE_MISSING, result["missing_evidence"])

    def test_recommended_unreliable_is_uncertain(self):
        evidence = evidence_fixture(recommended_reliable=False)
        result, _ = classify_fixture(evidence, LOCAL_HISTORY)
        self.assertEqual(result["category"], "uncertain")
        self.assertIn(
            ReasonId.RECOMMENDED_CANDIDATE_UNRELIABLE,
            result["missing_evidence"],
        )

    def test_recommended_missing_is_uncertain(self):
        evidence = evidence_fixture(recommended_found=False)
        result, _ = classify_fixture(evidence, LOCAL_HISTORY)
        self.assertEqual(result["category"], "uncertain")
        self.assertIn(
            ReasonId.RECOMMENDED_CANDIDATE_MISSING,
            result["missing_evidence"],
        )

    def test_spatial_unusable_is_uncertain(self):
        evidence = evidence_fixture()
        features = build_explanation_features(evidence, LOCAL_HISTORY, 7)
        features["actual_recommended"] = {"usable": False}
        result = classify_explanation(evidence, features)
        self.assertEqual(result["category"], "uncertain")
        self.assertIn(
            ReasonId.SPATIAL_COMPARISON_UNUSABLE,
            result["missing_evidence"],
        )

    def test_conflicting_local_and_global_evidence_is_uncertain(self):
        evidence = evidence_fixture()
        features = build_explanation_features(evidence, LOCAL_HISTORY, 7)
        features["actual_recommended"].update(
            {"same_region": True, "locality": "far"}
        )
        result = classify_explanation(evidence, features)
        self.assertTrue(result["abstained"])
        self.assertEqual(result["confidence"], "low")

    def test_pass_is_safe_uncertain(self):
        evidence = evidence_fixture(
            actual="PASS",
            actual_pv=["PASS", "E14"],
        )
        history = LOCAL_HISTORY[:-1] + [["B", "PASS"]]
        result, _ = classify_fixture(evidence, history)
        self.assertEqual(result["category"], "uncertain")
        self.assertIn(
            ReasonId.SPATIAL_COMPARISON_UNUSABLE,
            result["missing_evidence"],
        )

    def test_unsupported_evidence_schema_is_uncertain(self):
        evidence = evidence_fixture()
        features = build_explanation_features(evidence, LOCAL_HISTORY, 7)
        evidence["schema_version"] = 99
        result = classify_explanation(evidence, features)
        self.assertEqual(result["category"], "uncertain")
        self.assertIn(
            ReasonId.EVIDENCE_SCHEMA_UNSUPPORTED,
            result["missing_evidence"],
        )

    def test_unsupported_feature_schema_is_uncertain(self):
        evidence = evidence_fixture()
        features = build_explanation_features(evidence, LOCAL_HISTORY, 7)
        features["schema_version"] = 99
        result = classify_explanation(evidence, features)
        self.assertEqual(result["category"], "uncertain")
        self.assertIn(
            ReasonId.FEATURES_SCHEMA_UNSUPPORTED,
            result["missing_evidence"],
        )

    def test_empty_features_are_uncertain(self):
        result = classify_explanation(evidence_fixture(), {})
        self.assertEqual(result["category"], "uncertain")
        self.assertIn(
            ReasonId.FEATURES_SCHEMA_UNSUPPORTED,
            result["missing_evidence"],
        )

    def test_missing_optional_pv_does_not_crash(self):
        evidence = evidence_fixture(actual_pv=[])
        result, _ = classify_fixture(evidence, LOCAL_HISTORY)
        self.assertEqual(result["category"], "local_sequence")
        self.assertEqual(result["confidence"], "medium")

    def test_130_fixture_is_global_direction_only(self):
        result, features = classify_fixture(
            self._global_evidence(), GLOBAL_HISTORY
        )
        self.assertEqual(features["actual_region"], "bottom")
        self.assertEqual(features["recommended_region"], "top-left")
        self.assertEqual(result["category"], "global_direction")
        self.assertNotIn(result["category"], {"urgent_vs_big", "tenuki_timing"})

    def test_opponent_reply_cannot_override_unreliable_actual(self):
        evidence = self._global_evidence(actual_reliable=False)
        result, features = classify_fixture(evidence, GLOBAL_HISTORY)
        self.assertTrue(
            features["opponent_reply"]["near_original_recommendation"]
        )
        self.assertEqual(result["category"], "uncertain")

    def test_classifier_does_not_modify_evidence_or_features(self):
        evidence = self._global_evidence()
        features = build_explanation_features(evidence, GLOBAL_HISTORY, 7)
        original_evidence = copy.deepcopy(evidence)
        original_features = copy.deepcopy(features)
        classify_explanation(evidence, features)
        self.assertEqual(evidence, original_evidence)
        self.assertEqual(features, original_features)

    def test_classifier_is_deterministic(self):
        evidence = self._global_evidence()
        features = build_explanation_features(evidence, GLOBAL_HISTORY, 7)
        first = classify_explanation(evidence, features)
        for _ in range(5):
            self.assertEqual(classify_explanation(evidence, features), first)

    def test_output_schema_is_machine_readable(self):
        result, _ = classify_fixture(evidence_fixture(), LOCAL_HISTORY)
        self.assertEqual(
            set(result),
            {
                "schema_version",
                "category",
                "confidence",
                "abstained",
                "supporting_evidence",
                "contradictions",
                "missing_evidence",
                "limitations",
            },
        )
        self.assertEqual(
            result["schema_version"],
            EXPLANATION_CLASSIFICATION_SCHEMA_VERSION,
        )
        for key in (
            "supporting_evidence",
            "contradictions",
            "missing_evidence",
            "limitations",
        ):
            self.assertTrue(all(isinstance(item, str) for item in result[key]))

    def test_build_move_analyses_adds_classification_additively(self):
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
        record = build_move_analyses([["B", "D4"]], {0: before, 1: after})[0]
        self.assertIn("explanation_evidence", record)
        self.assertIn("explanation_features", record)
        self.assertIn("explanation_classification", record)
        self.assertIn(
            record["explanation_classification"]["category"],
            {"local_sequence", "global_direction", "uncertain"},
        )

    def test_canonical_fixture_coverage(self):
        cases = [
            classify_fixture(evidence_fixture(), LOCAL_HISTORY)[0],
            classify_fixture(
                evidence_fixture(actual_pv=[]), LOCAL_HISTORY
            )[0],
            classify_fixture(self._global_evidence(), GLOBAL_HISTORY)[0],
            classify_fixture(
                self._global_evidence(actual_pv=[]), GLOBAL_HISTORY
            )[0],
            classify_fixture(
                self._global_evidence(actual_pv=[], recommended_pv=[]),
                GLOBAL_HISTORY,
            )[0],
            classify_explanation(evidence_fixture(), {}),
        ]
        self.assertEqual(
            Counter(result["category"] for result in cases),
            Counter(
                {"local_sequence": 2, "global_direction": 2, "uncertain": 2}
            ),
        )

    @staticmethod
    def _global_evidence(
        *,
        actual_pv=None,
        recommended_pv=None,
        actual_reliable=True,
    ):
        return evidence_fixture(
            actual="M6",
            recommended="E14",
            actual_pv=(
                ["M6", "N6", "M7", "N7"]
                if actual_pv is None
                else actual_pv
            ),
            recommended_pv=(
                ["E14", "F14", "E13", "D14"]
                if recommended_pv is None
                else recommended_pv
            ),
            reply="F14",
            actual_reliable=actual_reliable,
        )


if __name__ == "__main__":
    unittest.main()
