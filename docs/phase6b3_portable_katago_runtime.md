# Phase 6B-3 — Portable KataGo Runtime + Native Assets

Date: 2026-10-13  
Target: Apple Silicon, macOS 26+

## 1. Files changed

- `packaging/macos/build_native_runtime.sh` — deterministic native-runtime staging, recursive dependency discovery, Mach-O rewriting, ad-hoc signing, architecture/path/integrity verification, and final output reporting.
- `packaging/macos/README.md` — Phase 6B-3 invocation and staging-layout documentation.
- `test_native_runtime_packaging.py` — focused static contract tests for the staging script.
- `docs/phase6b3_portable_katago_runtime.md` — this report.

Generated output remains ignored at `packaging/macos/dist/logosgo-runtime/`. No Flutter, Runner, analytical Python, model, config, corpus, SGF, or Homebrew source file was changed in this phase.

## 2. Source KataGo identity/version

- Invoked source: `/opt/homebrew/bin/katago`
- Resolved source: `/opt/homebrew/Cellar/katago/1.16.4/bin/katago`
- Version: KataGo v1.16.4, Metal backend
- Type/architecture: thin Mach-O 64-bit executable, arm64
- Source size: 5,532,432 bytes
- Source signature: ad-hoc; no Team ID
- Build metadata: minimum macOS 26.0, SDK 26.0
- Source RPATHs included `/usr/local/lib`, Xcode toolchain/SDK locations, and `/usr/lib/swift`. All source RPATHs were removed from the staged copy because its linked libraries already use absolute Apple system paths or the bundled executable-relative path.

The source executable and Homebrew libraries were only inspected and copied. `install_name_tool`, `chmod`, and `codesign` were never run against source files.

## 3. Source dependency graph

Recursive inspection produced this non-system graph:

```text
katago
└── /opt/homebrew/opt/libzip/lib/libzip.5.dylib
    ├── /opt/homebrew/opt/xz/lib/liblzma.5.dylib
    └── /opt/homebrew/opt/zstd/lib/libzstd.1.dylib
```

`liblzma` and `libzstd` have no further non-system dependencies. The machine-readable complete graph, including system dependencies, is generated at `manifest/native-dependencies.tsv`.

## 4. Bundled native dependency inventory

The portable KataGo layer contains only the recursively required third-party components:

| Component | Source role | Staged size | Architecture |
|---|---|---:|---|
| `katago/katago` | Analysis executable | 5,532,432 B | arm64 |
| `katago/lib/libzip.5.dylib` | KataGo direct dependency | 154,560 B | arm64 |
| `katago/lib/liblzma.5.dylib` | libzip transitive dependency | 184,512 B | arm64 |
| `katago/lib/libzstd.1.dylib` | libzip transitive dependency | 649,648 B | arm64 |

Sizes are for rewritten and ad-hoc-signed staging copies. No unrelated Homebrew library was bundled.

## 5. System dependencies intentionally not bundled

The following remain legitimate macOS dependencies:

- `/usr/lib/libSystem.B.dylib`, `libc++.1.dylib`, `libobjc.A.dylib`, `libz.1.dylib`, and `libbz2.1.0.dylib`
- Swift runtime libraries under `/usr/lib/swift`
- Foundation, Metal, MetalPerformanceShaders, and MetalPerformanceShadersGraph under `/System/Library/Frameworks`

These are Apple platform components. Copying them would be incorrect and unnecessary.

## 6. Staging layout

The deterministic output is:

```text
packaging/macos/dist/logosgo-runtime/
├── backend/
│   ├── logosgo-backend
│   └── _internal/...
├── katago/
│   ├── katago
│   └── lib/
│       ├── libzip.5.dylib
│       ├── liblzma.5.dylib
│       └── libzstd.1.dylib
├── model/model.bin.gz
├── config/analysis.cfg
├── data/logosgo_corpus_full.csv
└── manifest/
    ├── assets.sha256
    ├── native-dependencies.tsv
    └── runtime.txt
```

This root works directly with the Phase 6B-1 `runtime_paths` lookup rules and is ready to become a Phase 6B-4 app resource source.

## 7. Mach-O rewrite strategy

- KataGo's `libzip` reference becomes `@executable_path/lib/libzip.5.dylib`.
- Dependencies between bundled dylibs become `@loader_path/<name>`.
- All copied source RPATH entries are deleted because the graph no longer needs search-path fallback.
- Apple system references remain unchanged.
- The script rejects unresolved `@...` source dependencies and basename collisions rather than guessing.
- Recursive discovery and rewriting happen only after files are copied into the fixed ignored staging destination.

## 8. Dylib install-ID changes

Copied dylib IDs are normalized to:

```text
@rpath/libzip.5.dylib
@rpath/liblzma.5.dylib
@rpath/libzstd.1.dylib
```

Runtime consumers do not rely on those IDs for lookup: KataGo uses `@executable_path`, while libzip uses `@loader_path`. The IDs are nevertheless relocatable and contain no Homebrew prefix.

## 9. Post-rewrite dependency verification

The script recursively inspects every staged Mach-O component after rewriting. Results:

- 125 combined backend/native Mach-O files inspected
- every file contains arm64
- zero load-command references to `/opt/homebrew`, `/usr/local`, or `/Users/...`
- zero forbidden developer-machine strings in staged text artifacts
- KataGo and all three copied dylibs pass strict code-sign verification
- the generated dependency inventory exactly records bundled versus system edges

The verification deliberately ignores the filename header printed by `otool`; only actual load commands are evaluated.

## 10. Code-signing/ad-hoc-signing behavior

`install_name_tool` invalidates existing signatures. After all rewrites, the script ad-hoc signs copied backend components, then the bundled KataGo dylibs, and finally the KataGo executable. It verifies every staged Mach-O with `codesign --verify --strict`.

The copied Phase 6B-2 Python framework had a pre-existing ad-hoc resource-envelope inconsistency under strict verification after copying. Re-signing all Mach-O files in the combined staging tree normalizes that copied bundle as well. This does not touch the Phase 6B-2 source output or use Developer ID. Developer ID signing and notarization remain Phase 6B-4/later work.

## 11. Asset integrity verification

The script compares source and staged SHA-256 values and fails on any mismatch. Verified hashes:

```text
93abbeea4b4b38a6b5fda83e58927b588e2ca195ef9816b831db9d629c029efa  model/model.bin.gz
194839bbac3ffef48830e79fa05167a93b3f1b8b602a6b184b954fd72517e796  config/analysis.cfg
6894a3640f2d886fa046f2663a6a5f6c2e7687b51eeb9e18fdecab08ef5e2940  data/logosgo_corpus_full.csv
```

`cmp` independently confirmed all three copies are byte-identical to the repository originals.

## 12. Production data included

- `model.bin.gz` — required by KataGo neural inference.
- `analysis.cfg` — required production analysis/concurrency/perspective configuration.
- `logosgo_corpus_full.csv` — loaded by the production LogosGo commentary engine.

No benchmarks, validation JSON, docs, tests, test SGFs, historical logs, source code, or research artifacts are placed in the runtime asset layer.

## 13. Direct portable KataGo smoke test

The complete runtime was copied to `/private/tmp/logosgo-phase6b3.<random>/`, then KataGo was launched from that external directory with:

- `env -i`
- system-only `PATH=/usr/bin:/bin:/usr/sbin:/sbin`
- no `PYTHONPATH`, `VIRTUAL_ENV`, or `DYLD_LIBRARY_PATH`
- staged executable, model, and config
- a valid empty-board analysis request with query-local `maxVisits=1`

Result: PASS. KataGo v1.16.4 initialized Metal on Apple M4, loaded the unchanged model/config, returned a valid `rootInfo` response with one visit, processed one NN row, cleaned up, and exited 0. The first sandboxed GPU attempt reached NN initialization but was denied Metal access; the identical command passed outside the command sandbox without changing any artifact.

## 14. Homebrew-independence evidence

- Recursive post-rewrite `otool` inspection found zero Homebrew/developer load paths.
- No Homebrew path was present in runtime `PATH` or `DYLD_LIBRARY_PATH`.
- `DYLD_PRINT_LIBRARIES=1` showed `libzip`, the intended `liblzma`, and `libzstd` loading from `/private/tmp/.../logosgo-runtime/katago/lib/`.
- The system may separately load Apple's `/usr/lib/liblzma.5.dylib` for an unrelated platform component; KataGo's libzip edge resolves to the bundled `@loader_path/liblzma.5.dylib`.
- The test did not rename, disable, or mutate Homebrew.

## 15. Standalone backend + portable KataGo result

Result: PASS from repository-external staging.

- Frozen backend launched directly; no `python` command or venv activation.
- CWD was `/private/tmp/.../launch`.
- Environment was clean and had no repository `PYTHONPATH` or Homebrew library injection.
- Listener was only `127.0.0.1:53125` with debug off.
- `/health` returned the expected identity, schema version, instance ID, readiness, and verified token.
- A one-move SGF produced two analyzed positions and completed in about 6.2 seconds.
- Root visits were 102 and 103, consistent with unchanged whole-game 100-visit requests.
- Response contained winrate/score, structured move analysis, game review, and generated auto commentary.
- KataGo logs proved the staged executable/model/config were used and Metal initialized successfully.
- `lsof` found no open repository, `/opt/homebrew`, or `/usr/local` files in the backend process.

## 16. Position-judgment result

Result: PASS with the real production setting.

- Backend launched the foreground engine with explicit `numAnalysisThreads=1,numSearchThreadsPerAnalysisThread=16`.
- Request retained `maxVisits=500`, `includeOwnership=true`, and `includeOwnershipStdev=true`.
- Response was HTTP 200 with status `success`, BLACK perspective, 515 completed visits, 361 ownership values, 361 ownership-stdev values, score/winrate, captures, and move count.
- Foreground engine shut down normally after the request. The slight visit overshoot is normal MCTS batching and was not a configuration change.

## 17. Process cleanup

The backend was stopped with an interrupt after the tests. Verification found:

- no backend process remaining
- no KataGo child process remaining
- port 53125 released
- no unexpected Phase 6B-3 process remaining

Native Runner lifecycle/watchdog work was not added.

## 18. Architecture result

- Source KataGo: thin arm64
- Bundled libzip/liblzma/libzstd: thin arm64
- Combined staging: 125 Mach-O files inspected, all containing arm64
- x86_64-only components: 0

The runtime satisfies the initial Apple Silicon target.

## 19. Minimum macOS requirement

| Component | Minimum macOS |
|---|---:|
| KataGo | 26.0 |
| libzip | 15.0 |
| liblzma | 26.0 |
| libzstd | 26.0 |

The effective native-layer requirement is therefore macOS 26.0. Phase 6A's private V1 target of Apple Silicon + macOS 26+ remains accurate. No deployment target was lowered.

## 20. Size result

| Layer | Size |
|---|---:|
| KataGo executable | 5.28 MiB |
| Three bundled third-party dylibs | 0.94 MiB |
| Complete `katago/` layer | 6.23 MiB |
| Model | 258.88 MiB |
| Config + corpus | 31,773 B |
| Native resources excluding backend | about 265.15 MiB |
| Standalone backend | about 59.27 MiB |
| Combined portable staging | 332,212 KiB / about 324.43 MiB |

This is below the Phase 6A estimated final uncompressed app range of roughly 405–485 MiB before Flutter app integration. No accidental bloat was found.

## 21. Failure-test results

All failures used temporary copies or intentionally incomplete temporary roots:

- Missing `libzip.5.dylib`: dyld named `@executable_path/lib/libzip.5.dylib`, reported the exact missing path, exit 134.
- Missing model: backend named both accepted model locations and exited 1.
- Missing config: backend named both accepted config locations and exited 1.
- Missing corpus: backend named both accepted corpus locations and exited 1.
- Non-executable KataGo: backend reported that the exact path was missing or non-executable and exited 1.
- Incorrect resource root: backend reported that the root did not exist or was not a directory and exited 1.

No original asset or Homebrew file was corrupted for these tests.

## 22. Regression results

- Phase 6B focused: 29 passed (`runtime_paths`, backend startup, backend packaging, native-runtime packaging)
- Relevant analysis/perspective/review set: 198 passed
- Full Python discovery: 251 passed (247 baseline + 4 Phase 6B-3 tests)
- `py_compile test_native_runtime_packaging.py`: PASS
- `bash -n packaging/macos/build_backend.sh packaging/macos/build_native_runtime.sh`: PASS
- `git diff --check`: PASS
- Clean-destination native runtime build: PASS

No production Python or Flutter source changed, so Flutter tests/analyze were not rerun solely for this phase. Existing dirty Flutter files from earlier phases were preserved and not edited.

## 23. Remaining Phase 6B-4 work

- Embed the staged backend/native/assets in the final Flutter macOS app layout.
- Implement native Runner ownership of free-port allocation, token injection, launch, readiness polling, and shutdown.
- Map the staging tree into final `Contents/Helpers` / `Contents/Resources` paths.
- Finalize app-level signing order, Developer ID signing, hardened-runtime/entitlement decisions, notarization, and distribution archive.
- Repeat full installed-app E2E QA from the final signed layout.

No final `.app`, Runner lifecycle, entitlements, app icon, ZIP, Developer ID signature, or notarization was created here.

## 24. Confirmation frozen analytical behavior is unchanged

Phase 6B-3 changes only packaging scripts, packaging documentation, a packaging contract test, and this report. The unchanged staged `analysis.cfg` still provides whole-game `16×4`; server behavior still requests whole-game 100 visits and foreground position judgment 500 visits with `1×16`, ownership/stdev, BLACK canonical perspective, and the existing scheduling/preemption/cancellation paths. Smoke responses confirm the same schemas and commentary path.

No analytical threshold, model, config content, perspective conversion, classifier, review selection/summary, trial/variation behavior, or network binding was altered.

A. READY FOR PHASE 6B-4

Portable KataGo/native assets work independently of Homebrew and are
ready for integration into LogosGo.app.
