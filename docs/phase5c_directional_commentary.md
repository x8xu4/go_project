# LogosGo V1 — Phase 5C Evidence-Grounded Directional Commentary

Date: 2026-10-07 (Asia/Taipei)

Product Acceptance recommendation: **PASS — commentary now meets the V1 broad-direction requirement.** Packaging was not started.

## 1. Files changed

- `directional_explanation.py`: new pure Evidence Description Layer.
- `structured_explanation.py`: attaches directional evidence and renders it in AUTO / DETAILED commentary.
- `logos_engine.py`: documentation updated to reflect evidence-grounded direction; API behavior remains the same.
- `test_directional_explanation.py`: focused geometry, reliability, malformed-data, perspective, and renderer tests.
- `test_structured_explanation.py`: updated safe-language assertions.
- `testdata/structured_explanation_golden.json`: move-130 M6/E14 fixture now contains Phase 2 directional features and expected language.
- `benchmark/validate_directional_commentary.py`: saved-artifact coverage validator; never starts KataGo.
- `benchmark/directional_commentary_manual_labels.json`: manual A/B/C/D review labels.
- `benchmark/directional_commentary_validation.json`: generated real-artifact metrics and rendered samples.
- `docs/phase5c_directional_commentary.md`: this report.

No Flutter production file was changed in Phase 5C.

## 2. Exact additive schema

`structured_explanation` retains its existing top-level schema and gains:

```text
directional_evidence:
  schema_version
  available
  actual: move, region
  recommendation: move, region, reliable
  relationship:
    available, same_region, distance_class, direction_difference
  recommended_pv:
    available, stays_local, dominant_region, local_ratio,
    valid_move_count, pass_move_count
  candidate_distribution:
    available, dominant_region, concentration_ratio,
    reliable_candidate_count, distinct_region_count, is_concentrated
  facts: [{id, ...fact-specific fields}]
  limitations: [stable limitation ids]
```

The structure is deterministic, JSON-safe, board-size aware, independent of the Phase 3 classifier, and contains no raw KataGo payload duplication.

## 3. Directional fact vocabulary

- `same_direction`
- `different_direction`
- `recommended_pv_stays_local`
- `candidates_concentrated`
- `candidates_distributed`

`recommended_pv_shifts_away` is intentionally not emitted in V1: existing features can reliably say that a line is not local, but do not always establish one stable destination strongly enough to call it a directional shift.

## 4. Reliability and safety gates

- Actual-vs-recommendation geometry requires a reliable recommendation and valid board coordinates.
- Actual candidate presence/reliability is not required when the SGF actual coordinate is known.
- A cross-region pair classified `near` is treated as a boundary ambiguity, not a meaningful direction change.
- PV facts require the existing Phase 4A variation gate: reliable recommendation, reliable/non-empty PV, first PV move matching the recommendation, and valid Phase 2 locality data.
- PASS is excluded from locality counts and never assigned a fake region.
- Candidate-distribution facts use only reliable candidates and require at least two usable board moves.
- Missing, malformed, PASS, unreliable, and insufficient cases abstain through stable limitation ids.
- No fact claims urgency, size, attack, defense, weakness, timing, sente, joseki, shape, invasion, reduction, cutting, or connection.

## 5. AUTO rendering

- Remains at at most three lines.
- Priority remains importance → observed loss → recommendation.
- Adds at most one strongest useful directional sentence.
- Does not append generic limitations or engineering language.
- Observed loss and candidate gap remain separate.

## 6. DETAILED / Ask rendering

Order is:

1. move and observed before/after result;
2. reliable recommendation;
3. reliable direct candidate comparison, if available;
4. positive directional facts;
5. variation availability;
6. direct-comparison limitation, if needed;
7. specific-Go-reason abstention at the end.

Missing/unreliable actual candidates now use natural language rather than top-K/search-debug terminology. Positive facts appear before limitations.

## 7. Known move-130 M6/E14 output

AUTO:

```text
第 130 手值得注意。
白棋實戰 M6 後，勝率估計下降約 8.3 個百分點，目數評估約下降 0.6 目。
KataGo 在落子前較推薦 E14。從盤面方向來看，實戰 M6 位於下方，推薦 E14 位於左上，兩者選擇的方向明顯不同。
```

DETAILED adds that the reliable recommended PV remains around the upper-left, then explicitly leaves the exact Go reason unresolved. It does not revive `urgent_vs_big` or claim that M6 is merely a big point.

Artifact note: the currently saved Phase 3C Park-vs-An move 130 record is M11/B7. The requested M6/E14 historical case is preserved by the `kim-park-130` research case and the structured golden fixture; the validator reports this distinction rather than relabeling either case.

## 8. Other real outputs sampled

- Park–An move 160, L6 → B7: lower vs left direction; reliable PV stays on the left; reliable candidates concentrate on the left.
- Park–An move 173, T17 → E9: upper-right vs left; PV remains on the left; candidates are otherwise distributed, limiting interpretation strength.
- Park–Hsu move 138, K9 → J6: near a 3x3 boundary, so no artificial different-direction claim; PV’s central focus remains available.
- Park Jin-sol–Park Junghwan move 119, K14 → L13: same upper direction; PV and candidate concentration independently support the upper-area focus.

## 9. Product-level coverage

Using the frozen Phase 4B selector over saved real Phase 3C artifacts:

| Metric | Result |
| --- | ---: |
| Total selected highlights | 13 |
| Reliable recommendation | 13 |
| `directional_evidence.available` | 13 |
| Actual-vs-recommendation region fact | 12 |
| Reliable PV directional fact | 5 |
| Candidate-distribution fact | 11 |
| Objective/recommendation/limitation only, no positive direction | 0 |

No new KataGo analysis was run to obtain these numbers.

## 10. Manual quality review

| Grade | Meaning | Count |
| --- | --- | ---: |
| A | useful broad explanation | 11 |
| B | somewhat useful | 2 |
| C | still mostly insufficient evidence | 0 |
| D | misleading / unsupported | 0 |

The two B cases are deliberately conservative: one has same-region but distributed candidates; the other is a near cross-region boundary where the system abstains from calling the directions different. No safety gate was relaxed to force an A.

## 11. Tests and regression

- Focused Phase 5C + Phase 4A tests: 61 passed.
- Focused Phase 1/2/4A integration set: 100 passed.
- Full Python suite: 209 passed.
- Full Flutter suite: 54 passed.
- Python `py_compile`: passed for all repository Python files outside `venv`.
- `git diff --check`: passed.
- `flutter analyze`: unchanged 13 existing lint/deprecation diagnostics; no new Flutter diagnostic.
- Real-artifact validator: completed; no KataGo process started.

## 12. Remaining limitations

- The layer describes observable direction, not professional-level causal Go principles.
- 3×3 regions are intentionally coarse; close moves across a region boundary abstain.
- A non-local PV is not described as “shifting away” unless future evidence provides a stable, validated destination rule.
- Candidate distribution describes locations, not evaluation-gap magnitude.
- The existing Phase 5B raw `ClientException` UX issue and analyzer debt remain backlog and were not touched.

## 13. Frozen foundations confirmation

Phase 5C did not modify:

- `analysis.cfg`, model, visits, concurrency, ownership, or PV length;
- whole-game/foreground scheduling, cancellation, process lifecycle, or resume behavior;
- `analysis_logic.py` evidence generation;
- Phase 3 classifier gates/categories;
- Phase 4B Review selection/ranking/suppression;
- Phase 4C summary semantics;
- Flutter Review, variation, trial, position judgment, or observed-loss display.

## 14. Product Acceptance recommendation

**A. PASS — commentary now meets the V1 broad-direction requirement.**

Typical selected highlights now provide at least one positive, evidence-grounded board-direction observation before limitations. No sampled explanation was graded misleading, and packaging was not started.
