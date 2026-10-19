# LogosGo V1 — Phase 5B Real E2E Release Candidate QA

Date: 2026-10-06 (Asia/Taipei)

Release gate: **PASS WITH P2/P3** — the only P1 found was fixed with a minimal Flutter display-layer change and passed focused, full automated, and real E2E regression. One recoverable P2 error-message polish issue remains. No packaging was performed.

## 1. Environment

- Hardware: Apple M4, 10 CPU cores, 16 GB RAM.
- OS: macOS 26.5.2 (build 25F84).
- KataGo: v1.16.4, Metal backend.
- Model/config: project-root `model.bin.gz` and `analysis.cfg`.
- Formal whole-game settings: 16 analysis threads × 4 search threads, 100 visits, PV length 8, ownership disabled.
- Foreground position judgment: 1 × 16 runtime override, 500 visits, ownership and ownership stdev enabled.
- Flutter: macOS desktop Debug mode.

## 2. Real SGFs

1. `棋譜/[朴廷桓]vs[安成浚]1765452105010001779.sgf` — 336 moves, primary long-game E2E.
2. `棋譜/[朴进率]vs[朴廷桓]1766236878010001427.sgf` — 134 moves, independent second-game validation.

Neither SGF was modified (`git diff --name-only -- 棋譜` remained empty).

## 3. Whole-game timing

| SGF | Job ID | Completed | Backend elapsed |
| --- | --- | ---: | ---: |
| 336-move game | `a6254685-384a-44fa-84ed-6a84f43ea47f` | 336 / 336 | 995.835 s (16m 35.84s) |
| 134-move game | `1ba41d12-0563-4be8-8b85-1ed2a0f87691` | 134 / 134 | 390.265 s (6m 30.27s) |

Backend and Flutter started normally through the production flow. Startup was not separately stopwatch-instrumented; both reached ready state within the normal debug startup period.

## 4. Foreground position-judgment timing

- During the 336-move background job, move 50 judgment completed in about 18 seconds.
- Result: 515 visits; Black 53.5%, White 46.5%, Black +0.3; ownership overlay rendered.
- A post-recovery move 134 judgment on the second game also completed in about 18 seconds: 515 visits; White 99.9%, Black 0.1%, White +65.1.

## 5. Analysis-time interaction and ETA

- Flutter remained responsive; board navigation and trial controls remained operable.
- Progress continuously advanced and Review did not show fabricated highlights before completion.
- ETA began with an estimating state, then updated from observed throughput. It fluctuated in the middle of the run but converged toward 47 seconds near completion.
- Commentary did not crash and the position-judgment loading state remained independent from whole-game progress.

## 6. Foreground priority scheduling

- Background analysis was preempted at 16 / 337 analyzed positions.
- Completed positions were retained.
- The interactive 1 × 16 KataGo process handled the foreground request.
- The formal 16 × 4 background process then restarted and continued from remaining turns rather than turn 0.
- Process inspection found no sustained pair of concurrent KataGo processes and no response-routing error.

## 7. Position-overlay cleanup

- Moving from move 50 to move 51 immediately cleared the prior ownership result.
- Review jumps and later navigation also cleared stale ownership.
- Closing the floating position panel cleared the overlay without affecting board or review state.

## 8. Whole-game completion

- Both backend jobs reached their final turn and Flutter left loading state.
- Move analyses, graph, commentary, `game_review`, and `review_summary` were parsed and displayed.
- No JSON/schema exception, malformed KataGo response, or process crash occurred in either completed run.

## 9. Review entry

- Long game: five highlights `[139, 141, 160, 229, 256]`, primary move 229.
- Short game: five highlights `[61, 112, 119, 127, 132]`, primary move 119.
- Flutter selected count, primary move, and AUTO summary matched backend output.
- No classifier, visit count, or engineering metadata leaked into the Review UI.

## 10. Review panel

- Panel opened above the board and kept the board visible in the background.
- Highlights were chronological; primary move had emphasis; importance and variation availability were correct.
- Detailed summary expanded correctly.
- Manual visual inspection found no overflow; the lower list was scrollable/clipped only at its intended viewport boundary.

## 11. Start Review

- “開始復盤” jumped to the chronological first highlight, move 139, not the primary move.
- Board, move number, S7 actual move, commentary, and graph selection agreed.

## 12. Primary Review

- “優先回看” jumped to backend primary move 229 and displayed actual B12.
- It remained semantically distinct from “開始復盤”.

## 13. Direct highlight jumps

- First: move 139 / S7.
- Middle: move 160 / White L6.
- Last: move 256 / White F14.
- Board, move number, actual move, commentary, and graph stayed synchronized; no off-by-one was observed.

## 14. Previous / Next highlight navigation

- Full forward and reverse traversal passed.
- Boundary controls did not jump beyond the first/last highlight.
- Manual navigation from 256 to 257 cleared active review index; returning to 256 restored 5 / 5.
- Original SGF history remained unchanged.

## 15. Phase 4A AUTO commentary

- Black/White perspective and observed loss were correct after the P1 fix described below.
- Reliable and missing/unreliable actual-candidate cases used their intended paths.
- No prohibited speculative principle labels appeared in the formal Phase 4A path.

## 16. Detailed / Ask Why

- Reliable case, move 35: observed loss 8.7% / 1.0 points remained distinct from candidate gap 7.7% / 0.9 points.
- Missing actual candidate, move 256: safe limitation; observed loss 31.4% / 1.6 points; no invented candidate gap.
- Unreliable actual candidate, move 229: safe limitation; observed loss 77.4% / 8.5 points; no invented candidate gap.
- Reopening the same successful answer used Flutter cache; there was no second POST and no extra KataGo process.

## 17. Recommended variation

- At move 229, the formal base position was move 228.
- PV was replayed through existing trial mode, first move L8, final move T18, numbering 1…8.
- Move numbers were temporarily enabled and formal commentary did not duplicate raw PV coordinates.
- Automated tests verify capture replay, growable trial history, and user continuation at N+1.
- Manual placement of move 9 could not be exercised because the QA automation layer could not target a board coordinate; this is a QA tooling limitation, not an observed app failure.

## 18. Trial → Review jump

- Direct review navigation while the PV was active cleared trial/PV state first.
- Formal move 229 and its board were restored; move-number preference returned to OFF.
- No crash or trial-history residue occurred. This release-blocker flow passed.

## 19. Review → Position judgment

- Move 229 judgment returned 514 visits, White 93.1%, Black 6.9%, White +4.8, captures 5 / 11.
- Ownership matched the selected highlight and Review remained at 4 / 5.
- Jumping to move 256 cleared the old overlay.

## 20. Manual navigation

- Leaving a highlight cleared the derived review index.
- Manually returning to a highlight rediscovered the correct index.
- Review navigation continued to work afterward.

## 21. Empty/small review

Neither real SGF naturally produced 0–2 highlights. No extra KataGo run or selector modification was made. Existing Flutter tests cover empty, one-highlight, malformed, and multiple-highlight models.

## 22. Cancel and re-analyze

- Job `95a53200-ae49-4a04-8d86-57f541cd8dda` was canceled around 2 / 134.
- Flutter immediately cleared loading and showed canceled state; no half-built Review appeared.
- Reimport/retry created job `5487435b-99cc-4dff-8a35-d6611aac7f4a` and progressed normally; it was then canceled for cleanup.
- Importing the second SGF cleared the first game’s Review, primary move, ownership, trial state, and question cache.

## 23. Error recovery

- Backend-unavailable test: after stopping Flask, position judgment failed without permanent loading; the button became usable again and the app recovered after backend restart.
- The user-visible error exposed raw `ClientException` / socket details; logged as P2 and intentionally not fixed in Phase 5B.
- A subsequent real position request succeeded after restart.
- Malformed optional evidence is covered by Python and Flutter regression tests. An intentional live KataGo crash was not injected because there is no safe mock path and the instructions prohibit damaging model/config.

## 24. Bugs and fixes

### QA-5B-001 — P1 — fixed

- Reproduction: complete the 134-move game and open move 134.
- Expected: objective analysis should show observed score loss (~1.4 points).
- Actual: top objective analysis showed legacy `score_loss` candidate gap (~2.8 points), while structured AUTO correctly showed observed loss.
- Root cause: Flutter’s legacy objective header read `score_loss` / `winrate_loss` directly even when `observed_*_loss` fields were available.
- Fix: added display helpers that prefer `observed_winrate_loss` and `observed_score_loss`, with legacy fallback for old payloads; no backend schema or analysis logic changed.
- Regression: focused 15-test widget run, full 54-test Flutter run, and real move-134 E2E all passed; display now shows 1.4 points.

### QA-5B-002 — P2 — not fixed by scope

- Reproduction: stop backend and request position judgment.
- Expected: concise user-facing connection error.
- Actual: recoverable SnackBar includes raw `ClientException` / socket wording.
- Workaround: restart backend and retry; retry succeeded.

### Existing analyzer debt — P3 — not changed

`flutter analyze` reports 13 pre-existing warnings/info items (async context, braces, two unused methods, deprecated properties, and child ordering). There are no analyzer compile errors and the QA P1 helpers introduced no new diagnostic.

## 25. Automated regression, integrity, and cleanup

- Python: `176` tests passed.
- Flutter: `54` tests passed.
- Focused widget regression after P1: `15` tests passed.
- Python `py_compile`: passed for all repository Python files outside `venv`.
- `git diff --check`: passed.
- `flutter analyze`: completed with the 13 existing lint/deprecation diagnostics noted above.
- `git diff --name-only -- 棋譜`: empty.
- Final process check: no `server.py`, KataGo, `flutter run`, Flutter app, or `flutter_tester` process remained.
- Port 5001: no listener.
- Runtime analysis logs were retained; no pre-existing working-tree modifications were reset, restored, stashed, cleaned, or overwritten.

## 26. Final release gate

**PASS WITH P2/P3 — 可以進入 packaging，保留 error-message polish 與 analyzer debt backlog。**

This Phase did not start packaging and did not change visits, concurrency, KataGo scheduling, review selection, commentary architecture, or SGF data.
