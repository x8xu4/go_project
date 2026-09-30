import io
import json
import queue
import threading
import unittest

import server


TEST_SGF = "(;GM[1]FF[4]SZ[19]KM[6.5];B[pd];W[dd])"


def position_response(query):
    return {
        "id": query["id"],
        "turnNumber": len(query["moves"]),
        "ownership": [0.0] * 361,
        "ownershipStdev": [0.1] * 361,
        "rootInfo": {
            "winrate": 0.55,
            "scoreLead": 1.5,
            "currentPlayer": "B",
            "visits": 503,
        },
        "moveInfos": [],
    }


class SupersedingPositionClient:
    available = True

    def __init__(self):
        self.lock = threading.Lock()
        self.queries = []
        self.first_started = threading.Event()
        self.first_cancelled = threading.Event()
        self.close_count = 0

    def query(self, payload, *, idle_timeout=None, cancel_event=None):
        with self.lock:
            index = len(self.queries)
            self.queries.append(payload)
        if index == 0:
            self.first_started.set()
            if cancel_event is None or not cancel_event.wait(timeout=3):
                raise AssertionError("older position request was not superseded")
            self.first_cancelled.set()
            raise server.AnalysisCancelled("superseded")
        return position_response(payload)

    def diagnostics(self):
        return ""

    def close(self):
        self.close_count += 1


class FakeProcess:
    def __init__(self, responses):
        self.stdout = io.StringIO("".join(json.dumps(item) + "\n" for item in responses))

    def poll(self):
        return 0


class PreemptOnceBatchClient:
    available = True

    def __init__(self):
        self.turn_batches = []

    def query_many(
        self,
        payload,
        expected_turns,
        on_final_result,
        *,
        idle_timeout=None,
        cancel_event=None,
        preempt_event=None,
    ):
        turns = list(expected_turns)
        self.turn_batches.append(turns)
        if len(self.turn_batches) == 1:
            on_final_result(0, position_response({**payload, "moves": []}))
            preempt_event.set()
            preempt_event.clear()
            raise server.AnalysisPreempted("test preemption")
        for turn in turns:
            response = position_response({**payload, "moves": [["B", "D4"]] * turn})
            response["turnNumber"] = turn
            on_final_result(turn, response)
        return set(turns)

    def diagnostics(self):
        return ""


class PositionPriorityTests(unittest.TestCase):
    def setUp(self):
        self.original_client = server.katago_client
        self.original_position_client = server.position_katago_client
        with server.position_requests_lock:
            server.position_requests.clear()
            server.position_request_active.clear()
            server.background_query_paused.set()

    def tearDown(self):
        server.katago_client = self.original_client
        server.position_katago_client = self.original_position_client
        with server.position_requests_lock:
            server.position_requests.clear()
            server.position_request_active.clear()
            server.background_query_paused.set()

    def test_new_position_request_supersedes_only_older_position_request(self):
        fake = SupersedingPositionClient()
        server.position_katago_client = fake
        first_result = {}

        def run_first():
            with server.app.test_client() as client:
                response = client.post(
                    "/analyze_position",
                    json={
                        "sgf_content": TEST_SGF,
                        "move_count": 1,
                        "client_id": "flutter-test",
                        "client_request_id": "request-100",
                    },
                )
                first_result["status"] = response.status_code
                first_result["json"] = response.get_json()

        first_thread = threading.Thread(target=run_first)
        first_thread.start()
        self.assertTrue(fake.first_started.wait(timeout=2))

        background_cancel = threading.Event()
        with server.app.test_client() as client:
            second = client.post(
                "/analyze_position",
                json={
                    "sgf_content": TEST_SGF,
                    "move_count": 2,
                    "client_id": "flutter-test",
                    "client_request_id": "request-120",
                },
            )
        first_thread.join(timeout=3)

        self.assertFalse(first_thread.is_alive())
        self.assertTrue(fake.first_cancelled.is_set())
        self.assertFalse(background_cancel.is_set())
        self.assertEqual(first_result["status"], 409)
        self.assertEqual(first_result["json"]["status"], "cancelled")
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.get_json()["client_request_id"], "request-120")
        self.assertEqual(second.get_json()["move_count"], 2)
        self.assertEqual(fake.close_count, 1)

        self.assertEqual(len(fake.queries), 2)
        self.assertNotEqual(fake.queries[0]["id"], fake.queries[1]["id"])
        for query in fake.queries:
            self.assertEqual(query["priority"], server.POSITION_PRIORITY)
            self.assertEqual(query["maxVisits"], server.POSITION_MAX_VISITS)
            self.assertTrue(query["includeOwnership"])
            self.assertTrue(query["includeOwnershipStdev"])

    def test_shared_client_routes_interleaved_responses_by_query_id(self):
        client = server.KataGoClient("unused", "unused", "unused")
        whole_queue = queue.Queue()
        position_queue = queue.Queue()
        with client._pending_lock:
            client._pending["whole-game-test"] = whole_queue
            client._pending["position-test"] = position_queue
        process = FakeProcess(
            [
                {"id": "position-test", "turnNumber": 50},
                {"id": "whole-game-test", "turnNumber": 180},
            ]
        )
        client._process = process

        client._read_stdout(process)

        self.assertEqual(position_queue.get_nowait()["id"], "position-test")
        self.assertEqual(whole_queue.get_nowait()["id"], "whole-game-test")

    def test_formal_priorities_and_quality_limits_remain_unchanged(self):
        self.assertGreater(server.POSITION_PRIORITY, server.WHOLE_GAME_PRIORITY)
        self.assertEqual(server.WHOLE_GAME_PRIORITY, 0)
        self.assertEqual(server.WHOLE_GAME_MAX_VISITS, 100)
        self.assertEqual(server.POSITION_PRIORITY, 10)
        self.assertEqual(server.POSITION_MAX_VISITS, 500)
        self.assertEqual(server.POSITION_ANALYSIS_THREADS, 1)
        self.assertEqual(server.POSITION_SEARCH_THREADS, 16)
        self.assertIn(
            "numAnalysisThreads=1",
            server.position_katago_client.override_config,
        )
        self.assertIn(
            "numSearchThreadsPerAnalysisThread=16",
            server.position_katago_client.override_config,
        )

    def test_background_preemption_keeps_completed_turns_and_resumes_remaining(self):
        fake = PreemptOnceBatchClient()
        server.katago_client = fake
        job = server.AnalysisJob("preempt-test", TEST_SGF, 2)

        server._run_analysis_job(job)

        self.assertEqual(job.status, "completed")
        self.assertEqual(fake.turn_batches[0], [0, 1, 2])
        self.assertEqual(fake.turn_batches[1], [1, 2])
        self.assertEqual(set(job.position_results), {0, 1, 2})
        self.assertEqual(job.completed_moves, 2)


if __name__ == "__main__":
    unittest.main()
