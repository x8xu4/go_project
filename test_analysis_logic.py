import unittest

from analysis_logic import (
    EXPLANATION_EVIDENCE_PV_MAX_MOVES,
    EXPLANATION_EVIDENCE_SCHEMA_VERSION,
    EXPLANATION_EVIDENCE_TOP_K,
    build_move_analyses,
    classify_importance,
)
from logos_engine import LogosEngine


def position(turn, winrate, score, best_move="Q16", actual_move=None):
    move_infos = [
        {
            "move": best_move,
            "order": 0,
            "winrate": winrate,
            "scoreLead": score,
            "pv": [best_move, "D4"],
            "prior": 0.6,
            "visits": 80,
        }
    ]
    if actual_move and actual_move != best_move:
        move_infos.append(
            {
                "move": actual_move,
                "order": 1,
                "winrate": winrate - 0.20,
                "scoreLead": score - 12.0,
                "pv": [actual_move],
                "prior": 0.2,
                "visits": 10,
            }
        )
    return {
        "turnNumber": turn,
        "rootInfo": {
            "winrate": winrate,
            "scoreLead": score,
            "visits": 100,
        },
        "moveInfos": move_infos,
    }


def candidate(
    move,
    order,
    visits,
    *,
    winrate=0.60,
    score=2.0,
    prior=0.10,
    pv=None,
):
    return {
        "move": move,
        "order": order,
        "visits": visits,
        "prior": prior,
        "winrate": winrate,
        "scoreLead": score,
        "pv": list(pv if pv is not None else [move]),
    }


def evidence_fixture(*, actual_move="D4", actual_visits=5):
    """Small before/after fixture covering rank, bounds, and opponent reply."""

    long_pv = ["Q16", "D16", "Q4", "D4", "R14", "C14", "R6", "C6", "K10"]
    before_candidates = [
        # Deliberately not response-list ordered: explicit KataGo order must win.
        candidate("C3", 2, 12, pv=["C3", "D3"]),
        candidate("Q16", 0, 55, winrate=0.68, score=6.5, prior=0.42, pv=long_pv),
        candidate(
            "D4",
            1,
            actual_visits,
            winrate=0.61,
            score=3.0,
            prior=0.25,
            pv=["D4", "C4"],
        ),
    ]
    extra_moves = ["Q3", "D16", "R10", "C10", "K4", "K16", "A10"]
    before_candidates.extend(
        candidate(move, order, 3, prior=0.01)
        for order, move in enumerate(extra_moves, start=3)
    )
    before = {
        "turnNumber": 0,
        "rootInfo": {"winrate": 0.66, "scoreLead": 5.0, "visits": 100},
        "moveInfos": before_candidates,
    }
    after = {
        "turnNumber": 1,
        "rootInfo": {"winrate": 0.62, "scoreLead": 3.5, "visits": 120},
        "moveInfos": [
            candidate("R4", 1, 15, pv=["R4", "R5"]),
            candidate("C6", 0, 45, winrate=0.38, score=-3.2, pv=["C6", "D6"]),
        ],
    }
    return [["B", actual_move]], {0: before, 1: after}


class AnalysisLogicTests(unittest.TestCase):
    def test_black_and_white_losses_use_mover_perspective(self):
        black_records = build_move_analyses(
            [["B", "D4"]],
            {
                0: position(0, 0.70, 8.0, actual_move="D4"),
                1: position(1, 0.45, -5.0),
            },
        )
        self.assertEqual(black_records[0]["importance"], "decisive")
        self.assertAlmostEqual(black_records[0]["winrate_loss"], 0.25)

        white_records = build_move_analyses(
            [["W", "D4"]],
            {
                0: position(0, 0.30, -8.0, actual_move="D4"),
                1: position(1, 0.55, 5.0),
            },
        )
        self.assertEqual(white_records[0]["importance"], "decisive")
        self.assertAlmostEqual(white_records[0]["winrate_loss"], 0.25)

    def test_direct_candidate_loss_is_used_when_actual_move_was_searched(self):
        records = build_move_analyses(
            [["B", "D4"]],
            {
                0: position(0, 0.70, 8.0, best_move="Q16", actual_move="D4"),
                1: position(1, 0.68, 7.0),
            },
        )
        self.assertTrue(records[0]["actual_move_searched"])
        self.assertGreaterEqual(records[0]["search_winrate_loss"], 0.19)
        self.assertEqual(records[0]["best_move"], "Q16")

    def test_pv_is_explicitly_tied_to_the_position_before_the_move(self):
        record = build_move_analyses(
            [["B", "D4"]],
            {
                0: position(0, 0.70, 8.0, best_move="Q16", actual_move="D4"),
                1: position(1, 0.68, 7.0),
            },
        )[0]
        self.assertTrue(record["pv_reliable"])
        self.assertEqual(record["pv_base_move"], 0)
        self.assertEqual(record["pv_first_player"], "B")
        self.assertEqual(record["best_pv"][0], record["best_move"])

    def test_small_change_stays_ordinary(self):
        self.assertEqual(classify_importance(0.01, 0.8), "ordinary")

    def test_detailed_commentary_is_grounded_in_record(self):
        engine = LogosEngine("logosgo_corpus_full.csv")
        record = build_move_analyses(
            [["B", "D4"]],
            {
                0: position(0, 0.70, 8.0, best_move="Q16", actual_move="D4"),
                1: position(1, 0.50, -3.0),
            },
        )[0]
        text = engine.generate_detailed_commentary(record)
        self.assertIn("D4", text)
        self.assertIn("Q16", text)
        self.assertIn("KataGo", text)


class ExplanationEvidenceTests(unittest.TestCase):
    def test_schema_and_top_k_use_explicit_candidate_order(self):
        moves, positions = evidence_fixture()
        evidence = build_move_analyses(moves, positions)[0][
            "explanation_evidence"
        ]

        self.assertEqual(
            evidence["schema_version"], EXPLANATION_EVIDENCE_SCHEMA_VERSION
        )
        self.assertEqual(evidence["value_perspective"], "black")
        candidates = evidence["before"]["candidates"]
        self.assertEqual(len(candidates), EXPLANATION_EVIDENCE_TOP_K)
        self.assertEqual([item["order"] for item in candidates], list(range(8)))
        self.assertEqual(evidence["before"]["recommended"]["move"], "Q16")
        self.assertEqual(evidence["before"]["recommended"]["order"], 0)

    def test_actual_move_equal_to_top_candidate(self):
        moves, positions = evidence_fixture(actual_move="Q16")
        before = build_move_analyses(moves, positions)[0][
            "explanation_evidence"
        ]["before"]

        self.assertTrue(before["actual"]["found"])
        self.assertEqual(before["actual"], before["recommended"])

    def test_non_top_actual_candidate_preserves_objective_fields(self):
        moves, positions = evidence_fixture()
        actual = build_move_analyses(moves, positions)[0][
            "explanation_evidence"
        ]["before"]["actual"]

        self.assertEqual(
            actual,
            {
                "found": True,
                "move": "D4",
                "order": 1,
                "visits": 5,
                "prior": 0.25,
                "winrate_black": 0.61,
                "score_lead_black": 3.0,
                "pv": ["D4", "C4"],
                "reliable": True,
                "reliability_reason": "sufficient_visits",
            },
        )

    def test_missing_actual_candidate_is_explicit_and_safe(self):
        moves, positions = evidence_fixture(actual_move="T1")
        actual = build_move_analyses(moves, positions)[0][
            "explanation_evidence"
        ]["before"]["actual"]

        self.assertEqual(
            actual,
            {
                "found": False,
                "move": "T1",
                "order": None,
                "visits": None,
                "prior": None,
                "winrate_black": None,
                "score_lead_black": None,
                "pv": [],
                "reliable": False,
                "reliability_reason": "missing_candidate",
            },
        )

    def test_candidate_below_visit_threshold_is_unreliable(self):
        moves, positions = evidence_fixture(actual_visits=4)
        before = build_move_analyses(moves, positions)[0][
            "explanation_evidence"
        ]["before"]

        self.assertEqual(before["minimum_reliable_visits"], 5)
        self.assertFalse(before["actual"]["reliable"])
        self.assertEqual(
            before["actual"]["reliability_reason"], "insufficient_visits"
        )

    def test_candidate_at_visit_threshold_is_reliable(self):
        moves, positions = evidence_fixture(actual_visits=5)
        actual = build_move_analyses(moves, positions)[0][
            "explanation_evidence"
        ]["before"]["actual"]

        self.assertTrue(actual["reliable"])
        self.assertEqual(actual["reliability_reason"], "sufficient_visits")

    def test_after_top_candidate_is_opponent_best_response(self):
        moves, positions = evidence_fixture()
        after = build_move_analyses(moves, positions)[0][
            "explanation_evidence"
        ]["after"]

        self.assertEqual(after["root_visits"], 120)
        self.assertEqual(after["minimum_reliable_visits"], 6)
        response = after["opponent_best_response"]
        self.assertEqual(response["move"], "C6")
        self.assertEqual(response["order"], 0)
        self.assertEqual(response["visits"], 45)
        self.assertTrue(response["reliable"])

    def test_candidate_and_pv_bounds_are_enforced_without_padding(self):
        moves, positions = evidence_fixture()
        before = build_move_analyses(moves, positions)[0][
            "explanation_evidence"
        ]["before"]

        self.assertEqual(len(before["candidates"]), EXPLANATION_EVIDENCE_TOP_K)
        self.assertEqual(
            len(before["recommended"]["pv"]),
            EXPLANATION_EVIDENCE_PV_MAX_MOVES,
        )
        self.assertEqual(before["actual"]["pv"], ["D4", "C4"])

    def test_black_perspective_is_not_inverted_for_white_move(self):
        positions = {
            0: position(0, 0.30, -8.0, best_move="Q16", actual_move="D4"),
            1: position(1, 0.55, 5.0),
        }
        black_record = build_move_analyses([["B", "D4"]], positions)[0]
        white_record = build_move_analyses([["W", "D4"]], positions)[0]

        black_evidence = black_record["explanation_evidence"]["before"]
        white_evidence = white_record["explanation_evidence"]["before"]
        self.assertEqual(black_evidence["recommended"]["winrate_black"], 0.30)
        self.assertEqual(white_evidence["recommended"]["winrate_black"], 0.30)
        self.assertEqual(black_evidence["recommended"]["score_lead_black"], -8.0)
        self.assertEqual(white_evidence["recommended"]["score_lead_black"], -8.0)
        self.assertAlmostEqual(black_record["mover_winrate_before"], 0.30)
        self.assertAlmostEqual(white_record["mover_winrate_before"], 0.70)
        self.assertAlmostEqual(black_record["mover_score_before"], -8.0)
        self.assertAlmostEqual(white_record["mover_score_before"], 8.0)

    def test_pass_and_empty_after_candidates_are_safe(self):
        before = {
            "rootInfo": {"winrate": 0.5, "scoreLead": 0.0, "visits": 100},
            "moveInfos": [candidate("pass", 0, 20, pv=["pass"])],
        }
        after = {
            "rootInfo": {"winrate": 0.5, "scoreLead": 0.0, "visits": 100},
            "moveInfos": [],
        }
        evidence = build_move_analyses(
            [["B", "pass"]], {0: before, 1: after}
        )[0]["explanation_evidence"]

        self.assertEqual(evidence["before"]["actual"]["move"], "PASS")
        self.assertEqual(evidence["before"]["actual"]["pv"], ["PASS"])
        self.assertEqual(
            evidence["after"]["opponent_best_response"]["reliability_reason"],
            "missing_candidate",
        )
        self.assertFalse(
            evidence["after"]["opponent_best_response"]["found"]
        )

        empty_before = dict(before, moveInfos=[])
        empty_evidence = build_move_analyses(
            [["B", "pass"]], {0: empty_before, 1: after}
        )[0]["explanation_evidence"]
        self.assertFalse(empty_evidence["before"]["recommended"]["found"])
        self.assertFalse(empty_evidence["before"]["actual"]["found"])

    def test_malformed_optional_candidate_fields_do_not_crash(self):
        malformed = {
            "move": "Q16",
            "order": "first",
            "visits": "many",
            "prior": "unknown",
            "winrate": None,
            "scoreLead": {},
            "pv": ["Q16", None, "invalid"],
        }
        before = {
            "rootInfo": {"winrate": 0.5, "scoreLead": 0.0, "visits": 100},
            "moveInfos": [malformed, None, {"move": "not-a-move"}],
        }
        after = {
            "rootInfo": {"winrate": 0.5, "scoreLead": 0.0, "visits": 100},
            "moveInfos": None,
        }
        record = build_move_analyses(
            [["B", "Q16"]], {0: before, 1: after}
        )[0]
        actual = record["explanation_evidence"]["before"]["actual"]

        self.assertTrue(actual["found"])
        self.assertIsNone(actual["order"])
        self.assertIsNone(actual["visits"])
        self.assertIsNone(actual["prior"])
        self.assertIsNone(actual["winrate_black"])
        self.assertIsNone(actual["score_lead_black"])
        self.assertEqual(actual["pv"], ["Q16"])
        self.assertEqual(actual["reliability_reason"], "insufficient_visits")
        self.assertFalse(record["search_comparison_reliable"])

    def test_existing_move_analysis_fields_keep_their_semantics(self):
        record = build_move_analyses(
            [["B", "D4"]],
            {
                0: position(0, 0.70, 8.0, best_move="Q16", actual_move="D4"),
                1: position(1, 0.68, 7.0),
            },
        )[0]

        self.assertEqual(record["best_move"], "Q16")
        self.assertEqual(record["best_pv"], ["Q16", "D4"])
        self.assertEqual(record["actual_move"], "D4")
        self.assertTrue(record["actual_move_searched"])
        self.assertEqual(record["actual_candidate_visits"], 10)
        self.assertAlmostEqual(record["observed_winrate_loss"], 0.02)
        self.assertAlmostEqual(record["search_winrate_loss"], 0.20)
        self.assertAlmostEqual(record["winrate_loss"], 0.20)


if __name__ == "__main__":
    unittest.main()
