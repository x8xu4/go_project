# Phase 5D — Black/White Perspective Parity Validation

Final result: **A. PASS**

LogosGo keeps KataGo's canonical raw values in Black perspective, converts
analytical values into the mover's perspective before loss/severity decisions,
and keeps board geometry color-neutral. Synthetic mirrored cases and real White
commentary both show no Black-perspective leakage.

The machine-readable evidence is in
`benchmark/perspective_parity_validation.json`; manual perspective labels are
in `benchmark/perspective_parity_manual_labels.json`. No KataGo process was
started for this phase.

## 1. Perspective flow map

```text
analysis.cfg: reportAnalysisWinratesAs = BLACK
    ↓
KataGo rootInfo / moveInfos (canonical raw Black perspective)
    ↓
analysis_logic._mover_value
    B: winrate=x, score=x
    W: winrate=1-x, score=-x
    ↓
observed mover loss + reliable candidate gap
    ↓
classify_importance (mover-normalized non-negative losses)
    ↓
build_structured_explanation
    observed fields are already mover-normalized
    raw candidate fields are normalized by player before direct comparison
    ↓
deterministic AUTO / DETAILED renderer
    ↓
LogosEngine → server response / ask cache → Flutter commentary UI
```

`directional_explanation.py` branches from coordinates/PV/candidate locations
and does not use player color when deriving region, distance, locality, or
concentration.

## 2. Existing perspective logic

- `analysis.cfg` intentionally fixes `reportAnalysisWinratesAs = BLACK`.
- `analysis_logic._mover_value` is the canonical root conversion: White
  winrate is `1 - black_winrate`; White score lead is `-black_score_lead`.
- Observed winrate and score losses are `max(0, mover_before - mover_after)`.
  A mover deterioration therefore remains positive for both colors.
- Recommendation selection uses KataGo's ranked first `moveInfos` item. It does
  not maximize the raw Black winrate in application code, so White is not
  mis-ranked.
- Raw candidate evidence remains explicitly named `winrate_black` and
  `score_lead_black`. `structured_explanation._mover_value` converts both the
  recommended and actual candidates before computing direct gaps.
- `classify_importance`, Review Selection, and Review Summary consume
  non-negative mover-normalized losses or persisted severity ratios, not raw
  Black values.
- AUTO/DETAILED select `黑棋` or `白棋` from `move.player`. `領先／落後` is
  derived from mover-normalized score, and `下降` is emitted only from positive
  mover loss.
- `LogosEngine.generate_auto_commentary` and
  `generate_detailed_commentary` use the structured deterministic renderers.
  The legacy corpus path is not used for current move records.
- `server.py` stores AUTO commentary with each analysis record and generates
  DETAILED commentary on demand. Flutter displays those backend strings and
  uses the already normalized `mover_*` fields for its objective summary.

## 3. Synthetic parity test results

A mirrored pair used identical moves and geometry while mathematically
inverting only raw KataGo values:

| Value | Black case | White case | Result |
|---|---:|---:|---|
| Raw Black WR before | 70% | 30% | canonical input differs |
| Mover WR before → after | 70% → 55% | 70% → 55% | equal |
| Raw Black score before | +4.0 | -4.0 | canonical input differs |
| Mover score before → after | +4.0 → +2.0 | +4.0 → +2.0 | equal |
| Observed WR loss | 15 pp | 15 pp | equal, positive |
| Observed score loss | 2.0 | 2.0 | equal, positive |
| Candidate WR gap | 10 pp | 10 pp | equal, positive |
| Candidate score gap | 2.0 | 2.0 | equal, positive |
| Importance | important | important | equal |
| Recommendation | D16 | D16 | equal |

All seven artifact invariants passed: mover values, observed losses,
candidate gaps, importance, geometry, Review Selection, and Review Summary.
The 13 dedicated parity tests also passed. The fixture deliberately keeps
observed loss (15 pp) different from candidate gap (10 pp), proving the two are
not conflated.

## 4. Black real-data metrics

| Metric | Count | Percentage |
|---|---:|---:|
| Selected highlights | 5 | 100% |
| Important | 3 | 60% |
| Decisive | 2 | 40% |
| Reliable recommendation | 5 | 100% |
| Direct comparison available | 1 | 20% |
| Directional evidence available | 5 | 100% |
| Actual/recommendation region fact | 5 | 100% |
| PV directional fact | 2 | 40% |
| Candidate-distribution fact | 4 | 80% |
| Variation available | 5 | 100% |
| Objective numbers + limitation only | 0 | 0% |
| AUTO available | 5 | 100% |
| DETAILED available | 5 | 100% |

## 5. White real-data metrics

| Metric | Count | Percentage |
|---|---:|---:|
| Selected highlights | 8 | 100% |
| Important | 2 | 25% |
| Decisive | 6 | 75% |
| Reliable recommendation | 8 | 100% |
| Direct comparison available | 2 | 25% |
| Directional evidence available | 8 | 100% |
| Actual/recommendation region fact | 7 | 87.5% |
| PV directional fact | 3 | 37.5% |
| Candidate-distribution fact | 7 | 87.5% |
| Variation available | 8 | 100% |
| Objective numbers + limitation only | 0 | 0% |
| AUTO available | 8 | 100% |
| DETAILED available | 8 | 100% |

## 6. Side-by-side comparison

Both colors have 100% reliable recommendations, variations, directional
evidence, AUTO, and DETAILED output in the selected real review set. Direct
comparison availability is similarly sparse (Black 20%, White 25%) because it
requires the actual move to receive enough visits; it is not forced by color.
PV-directional coverage is also similar (40% vs 37.5%).

The review set naturally selected 5 Black and 8 White moves, with a different
important/decisive distribution. This is not treated as bias: mirrored inputs
produce equal severity, and the selector never uses color in ranking. No
selection rule was changed to force a 50/50 split.

## 7. Sampled Black AUTO/DETAILED outputs

Four real Black cases were reviewed: moves 139, 173, 77, and 119. Their exact
AUTO and DETAILED strings are preserved in the artifact. Representative output:

**Move 139, AUTO**

> 第 139 手造成明顯局勢變化。  
> 黑棋實戰 S7 後，勝率估計下降約 48.9 個百分點，目數評估約下降 6.7 目。  
> KataGo 在落子前較推薦 M8。從盤面方向來看，實戰 S7 位於右側，推薦 M8 位於中央，兩者選擇的方向明顯不同。

**Move 139, DETAILED core**

> 第 139 手，黑棋實戰下在 S7。  
> 勝率由約 70.9% 變為 22.0%，估計下降約 48.9 個百分點；目數評估由領先約 2.9 目變為落後約 3.8 目，估計下降約 6.7 目。  
> KataGo 在落子前較推薦 M8。  
> 從盤面方向來看，實戰 S7 位於右側，推薦 M8 位於中央，兩者選擇的方向明顯不同。  
> 目前無法可靠地直接比較實戰 S7 與推薦 M8 本身的評價差距。  
> 至於這個差異背後的具體棋理，目前證據不足以可靠區分，因此不再進一步猜測。

Move 119 additionally validates a near-zero Black winrate and increasingly
negative mover score: `0.3% → 0.2%`, `落後 29.5 → 落後 49.0`, observed score
loss 19.4, while its separate candidate score gap is 17.7.

## 8. Sampled White AUTO/DETAILED outputs

Four real White cases were reviewed: moves 132, 160, 66, and 138. Their exact
AUTO and DETAILED strings are preserved in the artifact. Representative output:

**Move 160, AUTO**

> 第 160 手造成明顯局勢變化。  
> 白棋實戰 L6 後，勝率估計下降約 65.0 個百分點，目數評估約下降 11.3 目。  
> KataGo 在落子前較推薦 B7。從盤面方向來看，實戰 L6 位於下方，推薦 B7 位於左側，兩者選擇的方向明顯不同。

**Move 160, DETAILED core**

> 第 160 手，白棋實戰下在 L6。  
> 勝率由約 74.0% 變為 9.1%，估計下降約 65.0 個百分點；目數評估由領先約 6.1 目變為落後約 5.2 目，估計下降約 11.3 目。  
> KataGo 在落子前較推薦 B7。  
> 從盤面方向來看，實戰 L6 位於下方，推薦 B7 位於左側，兩者選擇的方向明顯不同。  
> 推薦後的主要變化也持續集中在左側一帶，顯示這一帶是這條推薦變化的主要焦點。  
> 目前無法可靠地直接比較實戰 L6 與推薦 B7 本身的評價差距。  
> 至於這個差異背後的具體棋理，目前證據不足以可靠區分，因此不再進一步猜測。

Move 138 is an important edge case: White winrate rises slightly from 1.3% to
1.7%, so commentary does **not** claim winrate deterioration; the independently
observed score deterioration from `落後 13.9` to `落後 26.0` is correctly
reported as 12.1 points. No sample contained raw-Black leakage or unsupported
urgent/tenuki/attack/defense claims.

## 9. Move-130 White validation

The historical White `M6` versus recommendation `E14` fixture passed:

- mover winrate `82.6% → 74.3%`, observed loss 8.3 pp;
- mover score `+3.0 → +2.4`, observed loss 0.6;
- actual `M6`, recommendation `E14`;
- lower-area versus upper-left directional fact;
- reliable recommendation continuation remains upper-left;
- direct candidate comparison is unavailable and is stated as such;
- final text abstains from assigning a specific Go principle.

It does not resurrect `urgent_vs_big`, `tenuki_timing`, attack, or defense.

## 10. Review Selection parity

Mirrored Black/White records produce the same importance, threshold ratios,
selected move numbers, and severity basis. Review Selection reads structured
mover-normalized observed/combined loss fields; its ranking key contains no
player or raw Black value. The dedicated synthetic selector test passed.

## 11. Review Summary parity

A two-highlight mirrored test verifies that both colors produce:

- chronological `review_order = [1, 10]`;
- `primary_move = 10` from the same severity basis;
- move 10 as the largest observed winrate change;
- move 10 as the largest observed score change;
- identical structured review summaries.

Review Summary uses Phase 4B's persisted non-negative severity basis and does
not branch on player color.

## 12. Geometric parity

With identical coordinates, both mirrored colors produce identical:

- actual/recommendation regions (`bottom-right` / `top-left`);
- `far` distance class and different-direction fact;
- recommendation PV locality (`top-left`, ratio 1.0);
- candidate concentration/distribution facts.

The full `directional_evidence` dictionaries compare equal. Player color only
changes the rendered player name and evaluation perspective.

## 13. Manual quality labels by color

Across all 13 real selected highlights, existing Phase 5C quality labels split
as follows:

| Color | A | B | C | D |
|---|---:|---:|---:|---:|
| Black | 5 | 0 | 0 | 0 |
| White | 6 | 2 | 0 | 0 |

Perspective correctness was independently labeled on four real samples per
color:

| Color | Correct | Suspicious | Incorrect |
|---|---:|---:|---:|
| Black | 4 | 0 | 0 |
| White | 4 | 0 | 0 |

The historical White move-130 case was also labeled correct. There are zero
incorrect-perspective cases, satisfying the PASS rule.

## 14. Discovered bugs

No perspective or parity defect was found. The validation artifact contains an
empty `detected_asymmetries` list and
`incorrect_perspective_case_count = 0`.

The lower proportion of Black direct-comparison cases and the different
important/decisive counts are evidence-coverage differences, not implementation
asymmetry. No BLOCKER, HIGH, MEDIUM, or LOW parity bug is filed.

## 15. Regression results

- New parity tests: **13 passed**.
- Phase-focused evidence/features/structured/selector/summary/directional/parity
  tests: **167 passed**.
- Full Python suite: **222 passed** (baseline 209 + 13 parity tests).
- Full Flutter suite: **54 passed**.
- `flutter analyze`: **13 existing diagnostics**, no new diagnostic.
- `py_compile`: passed for production, validation, and parity test modules.
- `git diff --check`: passed.

## 16. Production code modification

No production code, Flutter code, KataGo setting, threshold, selector, summary,
or renderer was modified in Phase 5D. Added files are limited to parity tests,
validation tooling/data, the machine-readable artifact, and this report.

## 17. Recommendation

**A. PASS — current Black/White behavior is sufficiently symmetric and correct
for V1.**

The release can rely on one canonical BLACK-perspective KataGo representation:
equivalent Black and White situations produce equivalent mover loss/severity
semantics, user-facing text uses the correct player perspective, and geometric
evidence remains color-neutral. No parity repair is required before packaging.
Packaging was not started in this phase.
