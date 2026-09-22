import unittest

import server


class AnalysisApiTests(unittest.TestCase):
    def setUp(self):
        self.job = server.AnalysisJob("cache-test", "(;SZ[19];B[pd])", 1)
        self.job.status = "completed"
        self.job.result = {
            "move_analyses": [
                {
                    "move_number": 1,
                    "player": "B",
                    "actual_move": "Q16",
                    "best_move": "Q16",
                    "best_pv": ["Q16", "D4"],
                    "mover_winrate_before": 0.52,
                    "mover_winrate_after": 0.53,
                    "winrate_loss": 0.0,
                    "score_loss": 0.0,
                    "search_winrate_loss": 0.0,
                    "search_score_loss": 0.0,
                    "importance": "ordinary",
                    "crossed_even": False,
                    "actual_move_searched": True,
                }
            ]
        }
        with server.analysis_jobs_lock:
            server.analysis_jobs[self.job.job_id] = self.job
        self.client = server.app.test_client()

    def tearDown(self):
        with server.analysis_jobs_lock:
            server.analysis_jobs.pop(self.job.job_id, None)

    def test_ask_commentary_is_cached_after_first_success(self):
        first = self.client.post(
            "/analysis/cache-test/ask", json={"move_number": 1}
        )
        second = self.client.post(
            "/analysis/cache-test/ask", json={"move_number": 1}
        )
        self.assertEqual(first.status_code, 200)
        self.assertFalse(first.get_json()["cached"])
        self.assertTrue(second.get_json()["cached"])
        self.assertEqual(
            first.get_json()["commentary"], second.get_json()["commentary"]
        )


if __name__ == "__main__":
    unittest.main()
