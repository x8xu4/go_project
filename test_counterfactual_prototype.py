import copy
import unittest

from counterfactual_prototype import (
    COUNTERFACTUAL_EVIDENCE_SCHEMA_VERSION,
    aggregate_stability_runs,
    build_branch_queries,
    build_counterfactual_evidence,
    calibration_table_row,
    normalize_black_values,
    parse_branch_response,
)
from explanation_classifier import classify_explanation


def response_fixture(
    *,
    turn_number=130,
    current_player="B",
    root_winrate=0.4,
    root_score=-2.0,
    root_visits=100,
    reply="E14",
    reply_winrate=0.42,
    reply_score=-1.5,
    reply_visits=80,
):
    move_infos = []
    if reply is not None:
        move_infos.append(
            {
                "move": reply,
                "order": 0,
                "visits": reply_visits,
                "winrate": reply_winrate,
                "scoreLead": reply_score,
                "pv": [reply, "F14"],
            }
        )
    return {
        "id": "test",
        "isDuringSearch": False,
        "turnNumber": turn_number,
        "rootInfo": {
            "currentPlayer": current_player,
            "visits": root_visits,
            "winrate": root_winrate,
            "scoreLead": root_score,
        },
        "moveInfos": move_infos,
    }


def parsed_branch(
    name,
    *,
    original_player="W",
    first_move="E14",
    response=None,
):
    return parse_branch_response(
        name,
        response_fixture() if response is None else response,
        original_player=original_player,
        first_move=first_move,
        base_move_count=129,
        requested_visits=100,
    )


class CounterfactualPrototypeTests(unittest.TestCase):
    def test_query_builder_creates_two_symmetric_queries(self):
        base = [["B", "D4"], ["W", "Q16"]]
        queries = build_branch_queries(
            base,
            original_player="B",
            recommended_move="E14",
            actual_move="M6",
            rules="korean",
            komi=6.5,
        )
        self.assertEqual(set(queries), {"recommended_branch", "actual_branch"})
        self.assertEqual(queries["recommended_branch"]["moves"][-1], ["B", "E14"])
        self.assertEqual(queries["actual_branch"]["moves"][-1], ["B", "M6"])
        self.assertEqual(queries["recommended_branch"]["maxVisits"], 100)
        self.assertEqual(queries["actual_branch"]["analysisPVLen"], 8)
        for query in queries.values():
            self.assertFalse(query["includeOwnership"])
            self.assertNotIn("focusMoves", query)
            self.assertNotIn("includeMovesOwnership", query)
        self.assertEqual(base, [["B", "D4"], ["W", "Q16"]])

    def test_black_perspective_normalization(self):
        self.assertEqual(
            normalize_black_values(0.7, 5.0, "B"),
            {"mover_winrate": 0.7, "mover_score_lead": 5.0},
        )

    def test_white_perspective_normalization(self):
        self.assertEqual(
            normalize_black_values(0.3, -5.0, "W"),
            {"mover_winrate": 0.7, "mover_score_lead": 5.0},
        )

    def test_branch_move_counts_and_side_to_move_are_explicit(self):
        branch = parsed_branch("recommended_branch")
        self.assertEqual(branch["base_move_count"], 129)
        self.assertEqual(branch["after_first_move_count"], 130)
        self.assertEqual(branch["after_reply_move_count"], 131)
        self.assertEqual(branch["requested_visits"], 100)
        self.assertEqual(branch["side_to_move_after_first"], "B")
        self.assertEqual(branch["side_to_move_after_reply"], "W")
        self.assertTrue(branch["reliability"]["usable"])

    def test_score_and_winrate_gaps_use_original_white_player(self):
        recommended = parsed_branch(
            "recommended_branch",
            response=response_fixture(
                root_winrate=0.30,
                root_score=-5.0,
                reply_winrate=0.32,
                reply_score=-4.0,
            ),
        )
        actual = parsed_branch(
            "actual_branch",
            first_move="M6",
            response=response_fixture(
                root_winrate=0.40,
                root_score=-2.0,
                reply="M5",
                reply_winrate=0.45,
                reply_score=-1.0,
            ),
        )
        evidence = self._evidence(recommended, actual)
        first = evidence["comparison"]["after_first_move"]
        reply = evidence["comparison"]["after_opponent_reply"]
        change = evidence["comparison"]["gap_change_after_replies"]
        self.assertAlmostEqual(first["mover_winrate_gap"], 0.10)
        self.assertAlmostEqual(first["mover_score_gap"], 3.0)
        self.assertAlmostEqual(reply["mover_winrate_gap"], 0.13)
        self.assertAlmostEqual(reply["mover_score_gap"], 3.0)
        self.assertAlmostEqual(change["mover_winrate_gap_change"], 0.03)
        self.assertAlmostEqual(change["mover_score_gap_change"], 0.0)

    def test_black_player_gap_has_same_positive_semantics(self):
        recommended = parsed_branch(
            "recommended_branch",
            original_player="B",
            response=response_fixture(
                current_player="W",
                root_winrate=0.70,
                root_score=5.0,
                reply_winrate=0.68,
                reply_score=4.0,
            ),
        )
        actual = parsed_branch(
            "actual_branch",
            original_player="B",
            first_move="M6",
            response=response_fixture(
                current_player="W",
                root_winrate=0.60,
                root_score=2.0,
                reply="M5",
                reply_winrate=0.55,
                reply_score=1.0,
            ),
        )
        evidence = build_counterfactual_evidence(
            base_move_count=129,
            original_player="B",
            recommended_move="E14",
            actual_move="M6",
            recommended_branch=recommended,
            actual_branch=actual,
        )
        self.assertAlmostEqual(
            evidence["comparison"]["after_first_move"]["mover_winrate_gap"],
            0.10,
        )
        self.assertAlmostEqual(
            evidence["comparison"]["after_first_move"]["mover_score_gap"],
            3.0,
        )

    def test_missing_branch_is_safe_and_unusable(self):
        actual = parsed_branch("actual_branch", first_move="M6")
        evidence = self._evidence(None, actual)
        self.assertFalse(evidence["comparison"]["usable"])
        self.assertIn(
            "recommended_branch_unusable",
            evidence["reliability"]["reasons"],
        )

    def test_pass_reply_keeps_evaluation_but_marks_location_unavailable(self):
        branch = parsed_branch(
            "recommended_branch",
            response=response_fixture(reply="PASS"),
        )
        self.assertTrue(branch["reliability"]["usable"])
        self.assertFalse(branch["reliability"]["reply_location_usable"])
        self.assertIn(
            "reply_location_unavailable",
            branch["reliability"]["reasons"],
        )

    def test_unequal_branch_depth_is_not_comparable(self):
        recommended = parsed_branch("recommended_branch")
        actual = parsed_branch("actual_branch", first_move="M6")
        actual["after_reply_move_count"] += 1
        evidence = self._evidence(recommended, actual)
        self.assertFalse(evidence["comparison"]["usable"])
        self.assertIn("unequal_branch_depth", evidence["reliability"]["reasons"])

    def test_unequal_visit_budget_is_not_comparable(self):
        recommended = parsed_branch("recommended_branch")
        actual = parsed_branch("actual_branch", first_move="M6")
        actual["requested_visits"] = 200
        evidence = self._evidence(recommended, actual)
        self.assertFalse(evidence["comparison"]["usable"])
        self.assertIn("unequal_visit_budget", evidence["reliability"]["reasons"])

    def test_no_opponent_response_is_unusable(self):
        branch = parsed_branch(
            "recommended_branch",
            response=response_fixture(reply=None),
        )
        self.assertFalse(branch["reliability"]["usable"])
        self.assertIn(
            "missing_opponent_response",
            branch["reliability"]["reasons"],
        )

    def test_wrong_side_to_move_is_unusable(self):
        branch = parsed_branch(
            "recommended_branch",
            response=response_fixture(current_player="W"),
        )
        self.assertFalse(branch["reliability"]["usable"])
        self.assertIn("unexpected_side_to_move", branch["reliability"]["reasons"])

    def test_schema_contains_objective_evidence_only(self):
        evidence = self._evidence(
            parsed_branch("recommended_branch"),
            parsed_branch("actual_branch", first_move="M6"),
        )
        self.assertEqual(
            evidence["schema_version"],
            COUNTERFACTUAL_EVIDENCE_SCHEMA_VERSION,
        )
        forbidden = {"urgent", "tenuki", "punishment", "category", "confidence"}
        self.assertTrue(forbidden.isdisjoint(evidence))
        self.assertFalse(evidence["reliability"]["stability_assessed"])

    def test_inputs_are_not_modified(self):
        recommended = parsed_branch("recommended_branch")
        actual = parsed_branch("actual_branch", first_move="M6")
        original_recommended = copy.deepcopy(recommended)
        original_actual = copy.deepcopy(actual)
        self._evidence(recommended, actual)
        self.assertEqual(recommended, original_recommended)
        self.assertEqual(actual, original_actual)

    def test_phase_3a_classifier_is_not_affected(self):
        evidence = {
            "schema_version": 1,
            "before": {
                "actual": {"found": True, "reliable": True},
                "recommended": {"found": True, "reliable": True},
            },
        }
        features = {
            "schema_version": 1,
            "actual_recommended": {
                "usable": True,
                "same_region": True,
                "locality": "near",
            },
            "recommended_pv": {"usable": True, "stays_local": True},
            "actual_pv": {"usable": True, "stays_local": True},
        }
        before = classify_explanation(evidence, features)
        prototype = self._evidence(
            parsed_branch("recommended_branch"),
            parsed_branch("actual_branch", first_move="M6"),
        )
        after = classify_explanation(evidence, features)
        self.assertEqual(before, after)
        self.assertNotIn("explanation_classification", prototype)

    def test_repeated_result_aggregation_and_ranges(self):
        first = self._evidence(
            parsed_branch("recommended_branch"),
            parsed_branch("actual_branch", first_move="M6"),
        )
        second = copy.deepcopy(first)
        second["comparison"]["after_first_move"]["mover_winrate_gap"] += 0.04
        second["comparison"]["after_first_move"]["mover_score_gap"] += 1.5
        summary = aggregate_stability_runs([first, second])
        self.assertEqual(summary["usable_run_count"], 2)
        self.assertAlmostEqual(
            summary["metrics"]["first_move_winrate_gap"]["range"],
            0.04,
        )
        self.assertAlmostEqual(
            summary["metrics"]["first_move_score_gap"]["median"],
            (
                first["comparison"]["after_first_move"]["mover_score_gap"]
                + second["comparison"]["after_first_move"]["mover_score_gap"]
            )
            / 2,
        )

    def test_reply_region_can_be_stable_when_exact_move_changes(self):
        first = self._evidence(
            parsed_branch("recommended_branch"),
            parsed_branch("actual_branch", first_move="M6"),
        )
        second = copy.deepcopy(first)
        second["actual_branch"]["opponent_reply"]["move"] = "F14"
        summary = aggregate_stability_runs([first, second])
        self.assertFalse(summary["actual_reply"]["exact_move_stable"])
        self.assertTrue(summary["actual_reply"]["region_stable"])

    def test_missing_and_failed_runs_are_counted(self):
        usable = self._evidence(
            parsed_branch("recommended_branch"),
            parsed_branch("actual_branch", first_move="M6"),
        )
        failed = copy.deepcopy(usable)
        failed["comparison"]["usable"] = False
        summary = aggregate_stability_runs([usable, None, failed])
        self.assertEqual(summary["run_count"], 3)
        self.assertEqual(summary["usable_run_count"], 1)
        self.assertEqual(summary["missing_or_failed_run_count"], 2)

    def test_case_table_serialization(self):
        evidence = self._evidence(
            parsed_branch("recommended_branch"),
            parsed_branch("actual_branch", first_move="M6"),
        )
        row = calibration_table_row(
            {
                "case": {
                    "id": "case-1",
                    "sgf": "game.sgf",
                    "move_number": 130,
                    "expected_case_type": "ambiguous",
                    "selection_note": "fixture",
                },
                "phase3a": {
                    "player": "W",
                    "actual_move": "M6",
                    "recommended_move": "E14",
                    "category": "global_direction",
                    "confidence": "high",
                },
                "actual_candidate_quality": {
                    "actual_order": 2,
                    "actual_visits": 12,
                    "recommended_visits": 30,
                    "actual_visit_share": 0.12,
                    "initial_winrate_gap": 0.02,
                    "initial_score_gap": 0.5,
                },
                "experiment": {
                    "query_count": 2,
                    "total_runtime_seconds": 6.0,
                },
                "counterfactual_evidence": evidence,
            },
            stability={"run_count": 2},
        )
        self.assertEqual(row["case_id"], "case-1")
        self.assertEqual(row["actual"], "M6")
        self.assertEqual(row["recommendation"], "E14")
        self.assertEqual(row["stability"]["run_count"], 2)
        self.assertIsInstance(row["first_move_gap_winrate"], float)

    @staticmethod
    def _evidence(recommended, actual):
        return build_counterfactual_evidence(
            base_move_count=129,
            original_player="W",
            recommended_move="E14",
            actual_move="M6",
            recommended_branch=recommended,
            actual_branch=actual,
        )


if __name__ == "__main__":
    unittest.main()
