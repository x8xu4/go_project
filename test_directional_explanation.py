import copy
import unittest

from directional_explanation import (
    DIRECTIONAL_EVIDENCE_SCHEMA_VERSION,
    DirectionalFactId,
    DirectionalLimitationId,
    build_directional_evidence,
    region_label_zh,
)
from explanation_features import build_explanation_features
from structured_explanation import (
    build_structured_explanation,
    render_auto_commentary,
    render_detailed_commentary,
)


def candidate(
    move,
    *,
    reliable=True,
    found=True,
    pv=None,
    order=0,
    winrate=0.6,
    score=2.0,
):
    return {
        "found": found,
        "move": move,
        "order": order if found else None,
        "visits": 30 if found else None,
        "prior": 0.2 if found else None,
        "winrate_black": winrate if found else None,
        "score_lead_black": score if found else None,
        "pv": list(pv or []),
        "reliable": reliable if found else False,
        "reliability_reason": (
            "sufficient_visits"
            if found and reliable
            else "insufficient_visits" if found else "missing_candidate"
        ),
    }


def record(
    *,
    actual="M6",
    recommended="E14",
    player="W",
    actual_found=True,
    actual_reliable=True,
    recommended_found=True,
    recommended_reliable=True,
    pv=None,
    pv_reliable=True,
    candidates=None,
    board_size=19,
):
    recommended_pv = list(pv if pv is not None else [recommended, "F14", "E13"])
    recommended_item = candidate(
        recommended,
        found=recommended_found,
        reliable=recommended_reliable,
        pv=recommended_pv,
        order=0,
        winrate=0.25,
        score=-1.0,
    )
    actual_item = candidate(
        actual,
        found=actual_found,
        reliable=actual_reliable,
        pv=[actual, "N6"] if isinstance(actual, str) else [],
        order=2,
        winrate=0.34,
        score=0.5,
    )
    evidence = {
        "schema_version": 1,
        "value_perspective": "black",
        "before": {
            "root_visits": 100,
            "minimum_reliable_visits": 5,
            "recommended": recommended_item,
            "actual": actual_item,
            "candidates": list(
                candidates
                if candidates is not None
                else [recommended_item, actual_item]
            ),
        },
        "after": {},
    }
    result = {
        "move_number": 130,
        "player": player,
        "actual_move": actual,
        "best_move": recommended,
        "best_pv": recommended_pv,
        "pv_reliable": pv_reliable,
        "importance": "important",
        "mover_winrate_before": 0.826,
        "mover_winrate_after": 0.743,
        "observed_winrate_loss": 0.083,
        "mover_score_before": 3.0,
        "mover_score_after": 2.4,
        "observed_score_loss": 0.6,
        "winrate_loss": 0.20,
        "score_loss": 4.0,
        "explanation_evidence": evidence,
    }
    result["explanation_features"] = build_explanation_features(
        evidence,
        [[player, actual]],
        1,
        board_size=board_size,
    )
    return result


def directional(raw_record):
    return build_structured_explanation(raw_record)["directional_evidence"]


def fact_ids(value):
    return [item["id"] for item in value["facts"]]


class DirectionalEvidenceTests(unittest.TestCase):
    def test_schema_and_same_region(self):
        result = directional(record(actual="D16", recommended="E14"))
        self.assertEqual(
            result["schema_version"], DIRECTIONAL_EVIDENCE_SCHEMA_VERSION
        )
        self.assertIn(DirectionalFactId.SAME_DIRECTION, fact_ids(result))
        self.assertEqual(result["actual"]["region"], "top-left")

    def test_clearly_different_regions(self):
        result = directional(record())
        self.assertIn(DirectionalFactId.DIFFERENT_DIRECTION, fact_ids(result))
        self.assertEqual(result["relationship"]["distance_class"], "far")

    def test_near_cross_region_boundary_is_not_called_different_direction(self):
        result = directional(record(actual="G10", recommended="H10"))
        self.assertNotIn(DirectionalFactId.DIFFERENT_DIRECTION, fact_ids(result))
        self.assertIn(
            DirectionalLimitationId.REGION_BOUNDARY_NEAR,
            result["limitations"],
        )

    def test_center_region(self):
        result = directional(record(actual="K10", recommended="L10"))
        self.assertEqual(result["actual"]["region"], "center")
        self.assertEqual(result["recommendation"]["region"], "center")

    def test_all_four_corner_labels(self):
        expected = {
            "top-left": "左上",
            "top-right": "右上",
            "bottom-left": "左下",
            "bottom-right": "右下",
        }
        self.assertEqual(
            {key: region_label_zh(key) for key in expected}, expected
        )

    def test_board_edges_have_correct_orientation(self):
        result = directional(record(actual="A10", recommended="T10"))
        self.assertEqual(result["actual"]["region"], "left")
        self.assertEqual(result["recommendation"]["region"], "right")

    def test_pass_actual_has_no_fake_direction(self):
        result = directional(record(actual="PASS"))
        self.assertIsNone(result["actual"]["region"])
        self.assertIn(
            DirectionalLimitationId.ACTUAL_DIRECTION_UNAVAILABLE,
            result["limitations"],
        )

    def test_pass_recommendation_has_no_fake_direction(self):
        result = directional(record(recommended="PASS", pv=["PASS", "D4"]))
        self.assertIsNone(result["recommendation"]["region"])
        self.assertNotIn(DirectionalFactId.DIFFERENT_DIRECTION, fact_ids(result))

    def test_missing_recommendation(self):
        result = directional(
            record(recommended_found=False, recommended_reliable=False)
        )
        self.assertFalse(result["relationship"]["available"])

    def test_unreliable_recommendation(self):
        result = directional(record(recommended_reliable=False))
        self.assertIn(
            DirectionalLimitationId.RECOMMENDATION_UNRELIABLE,
            result["limitations"],
        )
        self.assertNotIn(DirectionalFactId.DIFFERENT_DIRECTION, fact_ids(result))

    def test_actual_candidate_missing_but_coordinate_known(self):
        result = directional(
            record(actual_found=False, actual_reliable=False)
        )
        self.assertIn(DirectionalFactId.DIFFERENT_DIRECTION, fact_ids(result))

    def test_actual_candidate_unreliable_but_coordinate_known(self):
        result = directional(record(actual_reliable=False))
        self.assertIn(DirectionalFactId.DIFFERENT_DIRECTION, fact_ids(result))

    def test_reliable_pv_stays_local(self):
        result = directional(record(pv=["E14", "F14", "E13", "PASS"]))
        self.assertIn(
            DirectionalFactId.RECOMMENDED_PV_STAYS_LOCAL,
            fact_ids(result),
        )
        self.assertEqual(result["recommended_pv"]["pass_move_count"], 1)

    def test_pv_unavailable(self):
        result = directional(record(pv=[], pv_reliable=False))
        self.assertFalse(result["recommended_pv"]["available"])

    def test_pv_unreliable(self):
        result = directional(record(pv_reliable=False))
        self.assertNotIn(
            DirectionalFactId.RECOMMENDED_PV_STAYS_LOCAL,
            fact_ids(result),
        )

    def test_pv_first_move_mismatch(self):
        result = directional(record(pv=["D4", "E4", "D5"]))
        self.assertFalse(result["recommended_pv"]["available"])

    def test_pv_pass_is_excluded_from_locality(self):
        result = directional(record(pv=["E14", "PASS", "F14", "E13"]))
        self.assertTrue(result["recommended_pv"]["available"])
        self.assertEqual(result["recommended_pv"]["valid_move_count"], 3)

    def test_concentrated_reliable_candidates(self):
        candidates = [
            candidate("E14", pv=["E14", "F14"]),
            candidate("F14", order=1),
            candidate("E13", order=2),
        ]
        result = directional(record(candidates=candidates))
        self.assertIn(
            DirectionalFactId.CANDIDATES_CONCENTRATED,
            fact_ids(result),
        )

    def test_distributed_reliable_candidates(self):
        candidates = [
            candidate("E14"),
            candidate("Q16", order=1),
            candidate("D4", order=2),
        ]
        result = directional(record(candidates=candidates))
        self.assertIn(
            DirectionalFactId.CANDIDATES_DISTRIBUTED,
            fact_ids(result),
        )

    def test_too_few_reliable_candidates(self):
        candidates = [candidate("E14"), candidate("Q16", reliable=False)]
        result = directional(record(candidates=candidates))
        self.assertFalse(result["candidate_distribution"]["available"])

    def test_malformed_candidate_is_ignored(self):
        candidates = [candidate("E14"), {"move": ["bad"], "reliable": True}]
        result = directional(record(candidates=candidates))
        self.assertFalse(result["candidate_distribution"]["available"])

    def test_malformed_coordinate_is_safe(self):
        result = directional(record(actual="Z99"))
        self.assertIsNone(result["actual"]["region"])

    def test_white_perspective_does_not_change_geometry(self):
        white = directional(record(player="W"))
        black = directional(record(player="B"))
        self.assertEqual(white["facts"], black["facts"])

    def test_black_perspective_does_not_change_geometry(self):
        result = directional(record(player="B"))
        self.assertEqual(result["actual"]["region"], "bottom")
        self.assertEqual(result["recommendation"]["region"], "top-left")

    def test_direct_comparison_unavailable_but_direction_available(self):
        structured = build_structured_explanation(
            record(actual_found=False, actual_reliable=False)
        )
        self.assertFalse(structured["direct_comparison"]["usable"])
        self.assertTrue(structured["directional_evidence"]["available"])

    def test_builder_does_not_mutate_record(self):
        raw = record()
        original = copy.deepcopy(raw)
        build_directional_evidence(
            raw,
            recommendation_found=True,
            recommendation_reliable=True,
            variation_available=True,
        )
        self.assertEqual(raw, original)


class DirectionalRendererTests(unittest.TestCase):
    def test_auto_includes_one_directional_fact(self):
        text = render_auto_commentary(build_structured_explanation(record()))
        self.assertIn("實戰 M6 位於下方", text)
        self.assertLessEqual(len(text.splitlines()), 3)

    def test_auto_is_not_dominated_by_limitations(self):
        text = render_auto_commentary(
            build_structured_explanation(
                record(actual_found=False, actual_reliable=False)
            )
        )
        self.assertNotIn("無法可靠", text)
        self.assertNotIn("證據不足", text)

    def test_detailed_places_positive_direction_before_limitations(self):
        text = render_detailed_commentary(
            build_structured_explanation(
                record(actual_found=False, actual_reliable=False)
            )
        )
        self.assertLess(text.index("實戰 M6 位於下方"), text.index("無法可靠"))
        self.assertLess(text.index("推薦後的主要變化"), text.index("具體棋理"))

    def test_no_unsupported_go_principle_terms_are_generated(self):
        text = render_detailed_commentary(build_structured_explanation(record()))
        for forbidden in (
            "急場",
            "大場",
            "攻擊",
            "防守",
            "弱棋",
            "先手",
            "後手",
            "脫先",
            "定石",
            "棋形",
            "打入",
            "侵消",
            "切斷",
            "連接",
        ):
            with self.subTest(term=forbidden):
                self.assertNotIn(forbidden, text)

    def test_missing_actual_candidate_still_explains_direction(self):
        text = render_detailed_commentary(
            build_structured_explanation(
                record(actual_found=False, actual_reliable=False)
            )
        )
        self.assertIn("兩者選擇的方向明顯不同", text)
        self.assertIn("這條推薦變化的主要焦點", text)

    def test_observed_loss_is_not_candidate_gap(self):
        text = render_detailed_commentary(build_structured_explanation(record()))
        self.assertIn("估計下降約 8.3 個百分點", text)
        self.assertIn("勝率評估相差約 9.0 個百分點", text)
        self.assertNotIn("估計下降約 20.0 個百分點", text)

    def test_variation_link_semantics_unchanged(self):
        structured = build_structured_explanation(record())
        text = render_detailed_commentary(structured)
        self.assertTrue(structured["recommendation"]["variation_available"])
        self.assertIn("查看推薦變化圖", text)
        self.assertNotIn("E14 → F14", text)


if __name__ == "__main__":
    unittest.main()
