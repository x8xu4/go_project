import unittest

from analysis_logic import build_move_analyses, classify_importance
from logos_engine import LogosEngine


def position(turn, winrate, score, best_move="Q16", actual_move=None):
    move_infos = [
        {
            "move": best_move,
            "winrate": winrate,
            "scoreLead": score,
            "pv": [best_move, "D4"],
            "visits": 80,
        }
    ]
    if actual_move and actual_move != best_move:
        move_infos.append(
            {
                "move": actual_move,
                "winrate": winrate - 0.20,
                "scoreLead": score - 12.0,
                "pv": [actual_move],
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


if __name__ == "__main__":
    unittest.main()
