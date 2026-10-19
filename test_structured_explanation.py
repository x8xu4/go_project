import copy
import json
import unittest
from pathlib import Path

from logos_engine import LogosEngine
from analysis_logic import build_move_analyses
from structured_explanation import (
    LimitationId,
    STRUCTURED_EXPLANATION_SCHEMA_VERSION,
    build_structured_explanation,
    render_auto_commentary,
    render_detailed_commentary,
)


GOLDEN_PATH = Path("testdata/structured_explanation_golden.json")


class StructuredExplanationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        payload = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
        cls.cases = {case["id"]: case for case in payload["cases"]}
        cls.engine = LogosEngine("logosgo_corpus_full.csv")

    def record(self, case_id):
        return copy.deepcopy(self.cases[case_id]["record"])

    def structured(self, case_id):
        return build_structured_explanation(self.record(case_id))

    def test_direct_comparison_black(self):
        structured = self.structured("direct_black")
        direct = structured["direct_comparison"]
        self.assertEqual(structured["schema_version"], 1)
        self.assertEqual(structured["interpretation"]["level"], "direct_comparison")
        self.assertTrue(direct["usable"])
        self.assertAlmostEqual(direct["winrate_gap"], 0.08)
        self.assertAlmostEqual(direct["score_gap"], 2.0)

    def test_direct_comparison_white(self):
        direct = self.structured("direct_white")["direct_comparison"]
        self.assertTrue(direct["usable"])
        self.assertAlmostEqual(direct["winrate_gap"], 0.08)
        self.assertAlmostEqual(direct["score_gap"], 3.0)

    def test_actual_missing(self):
        structured = self.structured("actual_missing")
        self.assertEqual(
            structured["interpretation"]["level"],
            "recommendation_only",
        )
        self.assertIn(
            LimitationId.ACTUAL_CANDIDATE_MISSING,
            structured["interpretation"]["limitations"],
        )
        self.assertFalse(structured["direct_comparison"]["usable"])

    def test_actual_unreliable(self):
        structured = self.structured("actual_unreliable")
        self.assertEqual(
            structured["interpretation"]["level"],
            "recommendation_only",
        )
        self.assertIn(
            LimitationId.ACTUAL_CANDIDATE_UNRELIABLE,
            structured["interpretation"]["limitations"],
        )

    def test_recommended_unreliable(self):
        record = self.record("actual_missing")
        recommended = record["explanation_evidence"]["before"]["recommended"]
        recommended["reliable"] = False
        structured = build_structured_explanation(record)
        self.assertEqual(structured["interpretation"]["level"], "limited")
        self.assertIn(
            LimitationId.RECOMMENDED_CANDIDATE_UNRELIABLE,
            structured["interpretation"]["limitations"],
        )
        self.assertNotIn(
            "KataGo 在落子前較推薦",
            render_auto_commentary(structured),
        )

    def test_observed_loss_and_candidate_gap_are_not_mixed(self):
        record = self.record("direct_black")
        record["observed_winrate_loss"] = 0.03
        record["mover_winrate_after"] = 0.52
        structured = build_structured_explanation(record)
        self.assertAlmostEqual(
            structured["severity"]["observed"]["winrate_loss"],
            0.03,
        )
        self.assertAlmostEqual(
            structured["direct_comparison"]["winrate_gap"],
            0.08,
        )
        auto = render_auto_commentary(structured)
        detailed = render_detailed_commentary(structured)
        self.assertIn("3.0 個百分點", auto)
        self.assertNotIn("8.0 個百分點", auto)
        self.assertIn("3.0 個百分點", detailed)
        self.assertIn("8.0 個百分點", detailed)
        self.assertIn("目數評估約下降 1.5 目", auto)
        self.assertNotIn("目數評估約下降 2.0 目", auto)
        self.assertIn("目數評估相差約 2.0 目", detailed)

    def test_white_perspective_normalization(self):
        structured = self.structured("direct_white")
        direct = structured["direct_comparison"]
        self.assertAlmostEqual(direct["winrate_gap"], (1 - 0.30) - (1 - 0.38))
        self.assertAlmostEqual(direct["score_gap"], 5.0 - 2.0)

    def test_winrate_uses_percentage_point_wording(self):
        text = render_auto_commentary(self.structured("actual_missing"))
        self.assertIn("下降約 8.3 個百分點", text)
        self.assertNotIn("損失 8.3%", text)

    def test_score_sign_wording(self):
        text = render_detailed_commentary(self.structured("direct_white"))
        self.assertIn("落後約 2.0 目", text)
        self.assertIn("落後約 3.5 目", text)
        self.assertIn("估計下降約 1.5 目", text)

    def test_reliable_pv_makes_variation_available(self):
        recommendation = self.structured("direct_black")["recommendation"]
        self.assertTrue(recommendation["variation_available"])
        self.assertEqual(recommendation["pv"], ["Q16", "D16", "C14"])

    def test_unreliable_pv_makes_variation_unavailable(self):
        structured = self.structured("pv_unavailable")
        self.assertFalse(structured["recommendation"]["variation_available"])
        self.assertEqual(structured["recommendation"]["pv"], [])
        self.assertIn(
            LimitationId.RECOMMENDED_PV_UNAVAILABLE,
            structured["interpretation"]["limitations"],
        )

    def test_auto_commentary_is_concise(self):
        text = render_auto_commentary(self.structured("actual_missing"))
        self.assertLessEqual(len(text.splitlines()), 3)
        self.assertNotIn("具體棋理原因", text)
        self.assertNotIn("沒有在可用候選中", text)

    def test_detailed_commentary_includes_limitation(self):
        text = render_detailed_commentary(self.structured("actual_missing"))
        self.assertIn("無法可靠地直接比較", text)
        self.assertIn("具體棋理，目前證據不足以可靠區分", text)

    def test_detailed_commentary_does_not_claim_tenuki(self):
        text = render_detailed_commentary(self.structured("direct_white"))
        self.assertNotIn("脫先", text)

    def test_detailed_commentary_does_not_claim_urgent(self):
        text = render_detailed_commentary(self.structured("direct_white"))
        self.assertNotIn("急場", text)

    def test_detailed_commentary_does_not_claim_attack_or_defense(self):
        text = render_detailed_commentary(self.structured("direct_white"))
        self.assertNotIn("攻擊", text)
        self.assertNotIn("防守", text)

    def test_detailed_commentary_does_not_repeat_pv_coordinates(self):
        text = render_detailed_commentary(self.structured("direct_black"))
        self.assertNotIn("Q16 → D16", text)
        self.assertNotIn("D16 → C14", text)

    def test_renderer_does_not_expose_search_debug_fields(self):
        text = render_detailed_commentary(self.structured("direct_black"))
        self.assertNotIn("visits", text.lower())
        self.assertNotIn("prior", text.lower())
        self.assertNotIn("候選第 2", text)

    def test_classifier_uncertain_still_renders_useful_commentary(self):
        record = self.record("direct_black")
        self.assertEqual(
            record["explanation_classification"]["category"],
            "uncertain",
        )
        text = self.engine.generate_detailed_commentary(record)
        self.assertIn("Q16", text)
        self.assertIn("同一次搜尋", text)

    def test_local_sequence_does_not_leak_into_text(self):
        record = self.record("actual_missing")
        text = self.engine.generate_detailed_commentary(record)
        self.assertNotIn("local_sequence", text)
        self.assertNotIn("局部次序", text)

    def test_global_direction_does_not_leak_into_text(self):
        record = self.record("direct_white")
        text = self.engine.generate_detailed_commentary(record)
        self.assertNotIn("global_direction", text)
        self.assertNotIn("全盤方向", text)

    def test_malformed_optional_evidence_has_safe_fallback(self):
        record = {
            "move_number": "bad",
            "player": "B",
            "actual_move": "D4",
            "best_move": "Q16",
            "best_pv": "not-a-list",
            "pv_reliable": True,
            "mover_winrate_before": float("nan"),
            "mover_winrate_after": None,
            "explanation_evidence": {"before": {"recommended": "bad"}},
            "explanation_classification": {"category": "local_sequence"},
        }
        structured = build_structured_explanation(record)
        self.assertEqual(structured["interpretation"]["level"], "limited")
        auto = render_auto_commentary(structured)
        self.assertIn("目前資料不足以描述前後變化", auto)
        self.assertNotIn("沒有顯示明確下降", auto)
        self.assertIn("資料不足", render_detailed_commentary(structured))

    def test_direct_comparison_does_not_turn_negative_gap_into_claim(self):
        record = self.record("direct_black")
        recommended = record["explanation_evidence"]["before"]["recommended"]
        actual = record["explanation_evidence"]["before"]["actual"]
        recommended["winrate_black"] = 0.50
        recommended["score_lead_black"] = 1.0
        actual["winrate_black"] = 0.52
        actual["score_lead_black"] = 2.0
        structured = build_structured_explanation(record)
        self.assertAlmostEqual(
            structured["direct_comparison"]["winrate_gap"], -0.02
        )
        self.assertAlmostEqual(
            structured["direct_comparison"]["score_gap"], -1.0
        )
        text = render_detailed_commentary(structured)
        self.assertIn("搜尋排序較偏好 Q16", text)
        self.assertNotIn("評估較高", text)
        self.assertNotIn("相差約", text)

    def test_existing_public_api_compatibility(self):
        record = self.record("direct_black")
        auto = self.engine.generate_auto_commentary(record)
        detailed = self.engine.generate_detailed_commentary(record)
        legacy = self.engine.generate_commentary(record)
        self.assertIsInstance(auto, str)
        self.assertIsInstance(detailed, str)
        self.assertEqual(legacy, auto)

    def test_clickable_pv_fields_remain_compatible(self):
        record = self.record("direct_black")
        original_pv = list(record["best_pv"])
        original_flag = record["pv_reliable"]
        structured = build_structured_explanation(record)
        self.assertEqual(record["best_pv"], original_pv)
        self.assertEqual(record["pv_reliable"], original_flag)
        self.assertTrue(structured["recommendation"]["variation_available"])

    def test_move_analysis_attaches_structured_explanation(self):
        positions = {
            0: {
                "rootInfo": {
                    "winrate": 0.60,
                    "scoreLead": 4.0,
                    "visits": 100,
                },
                "moveInfos": [
                    {
                        "move": "Q16",
                        "order": 0,
                        "visits": 60,
                        "winrate": 0.60,
                        "scoreLead": 4.0,
                        "pv": ["Q16", "D16"],
                    },
                    {
                        "move": "D4",
                        "order": 1,
                        "visits": 20,
                        "winrate": 0.52,
                        "scoreLead": 2.0,
                        "pv": ["D4", "C4"],
                    },
                ],
            },
            1: {
                "rootInfo": {
                    "winrate": 0.50,
                    "scoreLead": 1.0,
                    "visits": 100,
                },
                "moveInfos": [
                    {
                        "move": "C4",
                        "order": 0,
                        "visits": 50,
                        "winrate": 0.50,
                        "scoreLead": 1.0,
                        "pv": ["C4", "D3"],
                    }
                ],
            },
        }
        record = build_move_analyses([["B", "D4"]], positions)[0]
        self.assertIn("structured_explanation", record)
        self.assertEqual(
            record["structured_explanation"]["schema_version"],
            STRUCTURED_EXPLANATION_SCHEMA_VERSION,
        )
        self.assertEqual(
            record["structured_explanation"]["interpretation"]["level"],
            "direct_comparison",
        )

    def test_identical_input_produces_identical_text(self):
        structured = self.structured("direct_black")
        self.assertEqual(
            render_auto_commentary(structured),
            render_auto_commentary(copy.deepcopy(structured)),
        )
        self.assertEqual(
            render_detailed_commentary(structured),
            render_detailed_commentary(copy.deepcopy(structured)),
        )

    def test_five_golden_examples_match_key_assertions(self):
        self.assertEqual(len(self.cases), 5)
        for case_id, case in self.cases.items():
            with self.subTest(case=case_id):
                structured = build_structured_explanation(case["record"])
                expected = case["expected"]
                auto = render_auto_commentary(structured)
                detailed = render_detailed_commentary(structured)
                self.assertEqual(
                    structured["schema_version"],
                    STRUCTURED_EXPLANATION_SCHEMA_VERSION,
                )
                self.assertEqual(
                    structured["interpretation"]["level"],
                    expected["level"],
                )
                self.assertEqual(
                    structured["recommendation"]["variation_available"],
                    expected["variation_available"],
                )
                for key in ("winrate_gap", "score_gap"):
                    value = structured["direct_comparison"][key]
                    if expected[key] is None:
                        self.assertIsNone(value)
                    else:
                        self.assertAlmostEqual(value, expected[key])
                for fragment in expected["auto_contains"]:
                    self.assertIn(fragment, auto)
                for fragment in expected["detailed_contains"]:
                    self.assertIn(fragment, detailed)
                for fragment in expected["detailed_not_contains"]:
                    self.assertNotIn(fragment, detailed)


if __name__ == "__main__":
    unittest.main()
