import unittest

from sgfmill import sgf

from sgf_utils import get_capture_counts, get_initial_stones_from_game


class CaptureCountTests(unittest.TestCase):
    def _game(self, content):
        return sgf.Sgf_game.from_bytes(content.encode("ascii"))

    def test_setup_stones_are_not_counted_as_captures(self):
        game = self._game("(;SZ[5]AB[ab][ba][cb]AW[bb];B[bc])")

        self.assertEqual(
            get_capture_counts(game, move_count=0),
            {"black_captures": 0, "white_captures": 0},
        )
        self.assertEqual(
            get_capture_counts(game, move_count=1),
            {"black_captures": 1, "white_captures": 0},
        )

    def test_pass_counts_as_a_move_but_not_a_capture(self):
        game = self._game("(;SZ[5]AB[ab][ba][cb]AW[bb];W[];B[bc])")

        self.assertEqual(
            get_capture_counts(game, move_count=1),
            {"black_captures": 0, "white_captures": 0},
        )
        self.assertEqual(
            get_capture_counts(game, move_count=2),
            {"black_captures": 1, "white_captures": 0},
        )

    def test_trial_moves_are_included_in_capture_count(self):
        game = self._game("(;SZ[19]AB[ab][ba][cb]AW[bb])")

        self.assertEqual(
            get_capture_counts(
                game,
                move_count=0,
                extra_moves=[["B", "B17"]],
            ),
            {"black_captures": 1, "white_captures": 0},
        )

    def test_root_setup_is_available_for_katago(self):
        game = self._game("(;SZ[19]AB[pd][dp]AW[dd])")

        self.assertEqual(
            get_initial_stones_from_game(game),
            [["B", "D4"], ["B", "Q16"], ["W", "D16"]],
        )


if __name__ == "__main__":
    unittest.main()
