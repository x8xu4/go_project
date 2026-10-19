# Phase 6B-4 — First Self-Contained LogosGo.app

Date: 2026-10-13  
Target: Apple Silicon, macOS 26  
Artifact: `packaging/macos/dist/LogosGo.app`

## 1. Files changed

Phase 6B-4 made the following scoped changes while preserving all earlier dirty working-tree work:

- Backend lifecycle: `backend_startup.py`, `server.py`, `test_backend_startup.py`.
- Flutter bootstrap/endpoint bridge: `flutter_application_1/lib/main.dart`, `flutter_application_1/test/widget_test.dart`.
- Native Runner: `flutter_application_1/macos/Runner/AppDelegate.swift`, `MainFlutterWindow.swift`, and `RunnerTests/RunnerTests.swift`.
- macOS identity/build metadata: `Runner/Configs/AppInfo.xcconfig`, `Runner/Release.entitlements`, `Runner.xcodeproj/project.pbxproj`, and the shared `Runner.xcscheme`.
- App icon representations: the seven PNGs in `Runner/Assets.xcassets/AppIcon.appiconset/`; the official master was not modified.
- Packaging: `packaging/macos/build_app.sh`, `generate_app_icons.sh`, `README.md`, `test_app_packaging.py`, and build-output ignore rules in `.gitignore`.
- This report: `docs/phase6b4_first_self_contained_app.md`.

The Phase 6B-2/6B-3 backend and portable-runtime scripts are reused as inputs rather than replaced. Unrelated Phase 1–6 changes and existing untracked logs were not reset, cleaned, stashed, or overwritten.

## 2. Final architecture

The packaged process and configuration flow is:

```text
LogosGo.app / native Runner
  -> resolves Contents/Resources/LogosGoRuntime
  -> allocates a loopback port and creates a per-launch token
  -> launches the bundled PyInstaller backend directly
  -> verifies /health service + readiness + token + instance ID
  -> exposes one endpoint configuration over MethodChannel
  -> Flutter enters the existing GoBoardPage
  -> backend starts the bundled KataGo Metal executable when analysis is requested
```

The Runner, not Flutter, owns backend startup and shutdown. Flutter never invokes Python, discovers ports, or constructs a second backend configuration.

## 3. Final `.app` resource layout

```text
LogosGo.app/
  Contents/
    MacOS/LogosGo
    Frameworks/
      App.framework/
      FlutterMacOS.framework/
      file_picker.framework/
    Resources/
      AppIcon.icns
      Assets.car
      LogosGoRuntime/
        backend/
          logosgo-backend
          _internal/...
        katago/
          katago
          lib/*.dylib
        model/model.bin.gz
        config/analysis.cfg
        data/logosgo_corpus_full.csv
        manifest/...
```

All immutable paths are bundle-relative. There is one model/config/corpus copy in the embedded runtime, and the app does not write into `Contents/Resources`.

## 4. Runner lifecycle design

`BackendProcessController` is owned by `AppDelegate`. The first Flutter `getBackendConfiguration` request starts one serialized launch operation; concurrent callers become waiters for the same result. Release builds require the bundled paths. Debug builds retain the source-development fallback at `127.0.0.1:5001` only when no bundle runtime is present.

The controller launches the backend with explicit port, resource root, KataGo executable, and Runner parent PID. It keeps the `Process`, log handle, verified endpoint, launch generation, and waiter lifecycle in one private serial queue. Generation checks prevent stale callbacks from completing a later launch.

## 5. Dynamic port design

The Runner opens an IPv4 socket on `127.0.0.1` with port `0`, reads the kernel-assigned port, closes the probe socket, and passes that port to the backend. The backend itself is hard-bound to `127.0.0.1`; it never binds `0.0.0.0`.

The small bind/launch race cannot be eliminated without socket handoff support in the current Flask interface, so launch failure is bounded and retried with a newly allocated port up to three times. Packaged runs used dynamic ports including 49551, 49960, 50002, and 50196 rather than the development default.

## 6. Instance-token design

Every launch uses 32 bytes from `SecRandomCopyBytes`, encoded as unpadded URL-safe Base64. Tokens are never hard-coded or reused. The token is supplied to the child through `LOGOSGO_INSTANCE_TOKEN`, not a command-line argument, so it is absent from process listings. Flutter receives it only through the private MethodChannel and sends it as `X-LogosGo-Instance` on API requests.

The backend compares the header with `secrets.compare_digest`. `/health` reports a non-secret 24-hex-character SHA-256-derived `instance_id`; the Runner independently computes and verifies that value. The full token is not written to the backend log.

## 7. Readiness behavior

After spawning, the Runner polls `/health` every 250 ms with a 1-second request timeout and a 60-second overall startup deadline. Ready means all of the following are true:

- the process is still alive;
- HTTP status is 200;
- `service == "LogosGoBackend"`;
- `ready == true`;
- `token_verified == true`;
- `instance_id` matches the current launch token.

An identity mismatch fails immediately. Exit/launch failures retry at most three launches. Timeout, missing resources, process exit, token generation failure, and identity failure all become concise localized startup errors rather than an unbounded wait.

## 8. Flutter bridge/configuration

`MainFlutterWindow` exposes `logosgo/backend` with one `getBackendConfiguration` method. It returns host, port, and token only after native readiness succeeds. `BackendEndpointConfig` remains the single authoritative Flutter API configuration and is injected into the existing `GoBoardPage`; all existing endpoints use its URI/header helpers.

`LogosGoBootstrap` displays `正在啟動 LogosGo…` during readiness. Failure displays `LogosGo 啟動失敗`, a concise cause, and a `重試` action. Raw `ClientException` is not the primary packaged-startup experience.

## 9. Shutdown/watchdog design

Normal termination calls `BackendProcessController.stop()`: invalidate the generation, send termination to the backend, wait up to 3 seconds, and then kill the backend process group and PID if needed. The backend handles SIGTERM/SIGINT by closing both KataGo clients before exiting. Each client terminates its KataGo child, waits up to 5 seconds, then force-kills only if required.

The Runner passes its PID. A one-second backend watchdog checks parent existence; unexpected Runner death closes both KataGo clients and exits the backend. The backend establishes its own process group so the Runner's bounded fallback covers descendants without targeting unrelated processes.

## 10. Sandbox/entitlement changes

The Release entitlement dictionary is intentionally empty. App Sandbox and the old user-selected-file/network sandbox entitlements were removed because this private V1 must launch bundled native child processes. No camera, microphone, automation, incoming-network, or other unnecessary entitlement was added. This is not a Mac App Store configuration.

## 11. Writable locations

The runtime path layer keeps immutable bundle resources separate from writes:

- `~/Library/Application Support/LogosGo`
- `~/Library/Caches/LogosGo`
- `~/Library/Logs/LogosGo` (including `backend.log` and KataGo working logs)
- `${TMPDIR}/LogosGo`

The final app was launched from a read-only-style bundle location and did not require writable Resources. SGF selection remains through the existing file picker and the original SGF is never rewritten.

## 12. Backend embedding

The app embeds the complete Phase 6B-2 PyInstaller onedir backend. Runtime launch directly executes `.../backend/logosgo-backend`; it does not run `python server.py`, activate a venv, set `PYTHONPATH`, or require a system Python. The final bundle contains zero `.py` source files.

The child environment is deliberately reduced to system `PATH`, `LANG`, `HOME`, `TMPDIR`, and the private instance-token variable. Explicit resource and KataGo paths point inside the same app bundle.

## 13. KataGo/runtime embedding

The Phase 6B-3 runtime is embedded unchanged under `LogosGoRuntime`: KataGo, recursively required third-party dylibs, model, config, corpus, and manifest. Final assembly thins all Mach-O files to arm64, preserves/repairs relative load paths, removes forbidden developer-machine RPATHs, and re-signs nested code.

Source and bundled SHA-256 values match:

- model: `93abbeea4b4b38a6b5fda83e58927b588e2ca195ef9816b831db9d629c029efa`
- config: `194839bbac3ffef48830e79fa05167a93b3f1b8b602a6b184b954fd72517e796`
- corpus: `6894a3640f2d886fa046f2663a6a5f6c2e7687b51eeb9e18fdecab08ef5e2940`

## 14. Icon integration

`packaging/macos/assets/logosgo_icon_master.png` remains byte-for-byte unchanged at SHA-256 `9593b70b93f175c18f0fbf9252487a1c6479b3af821985a771ecde0e25d130a7`. The deterministic generator creates 16, 32, 64, 128, 256, 512, and 1024 pixel true-PNG representations for the existing AppIcon asset set. Xcode produced both `AppIcon.icns` and `Assets.car`; the normal LaunchServices launch identified the running application as LogosGo and used the bundled application icon in the app/Dock lifecycle.

## 15. Bundle ID/app name

- User-facing/product/executable name: `LogosGo`
- Bundle identifier: `com.logosgo.desktop`
- Architecture: `arm64`
- Minimum supported OS in this V1 artifact: macOS 26.0

The old Flutter placeholder identity was also removed from the test host and shared scheme.

## 16. Deterministic build pipeline

`packaging/macos/build_app.sh --katago /absolute/path/to/katago` performs, in order:

1. clean standalone-backend build;
2. portable KataGo runtime staging;
3. icon generation from the checked-in master;
4. Flutter macOS Release build;
5. deterministic runtime copy to `Contents/Resources/LogosGoRuntime`;
6. executable permission, architecture, dependency, RPATH, resource, and hash gates;
7. deepest-first ad-hoc signing and outer-bundle verification.

Generated `packaging/macos/build/` and `dist/` outputs are ignored. The final rebuild completed successfully and produced `packaging/macos/dist/LogosGo.app` without manual Finder assembly.

## 17. Signing/validation

All 130 Mach-O files in the final bundle are arm64-only. Binaries are signed first, then frameworks, then the outer app, using an ad-hoc identity only. Final `codesign --verify --deep --strict` succeeded, the designated requirement was satisfied, and `Info.plist` passed `plutil` validation.

The build also passed executable-bit checks, expected-resource checks, source/bundle hash equality, zero bundled `.py` files, and recursive forbidden load-path/string gates. No Developer ID signing or notarization was attempted.

## 18. Final app size

Uncompressed size is 355,616 KiB (347 MiB). Breakdown:

- embedded runtime: 332,212 KiB;
- model: 265,092 KiB;
- standalone backend: 60,696 KiB;
- KataGo plus native libraries: 6,376 KiB;
- Flutter frameworks: 20,552 KiB.

This is about 23 MiB above the Phase 6B-3 combined runtime (~324.43 MiB), explained mainly by Flutter frameworks/application assets and bundle metadata. It is below the Phase 6A 405–485 MiB estimate because the final app is arm64-only and does not duplicate the model/runtime.

## 19. First double-click result

PASS. A copy staged outside the repository was launched with normal macOS `open`/LaunchServices semantics; no internal binary or manual backend command was used. The UI opened as LogosGo, displayed startup state briefly, automatically launched the embedded backend on a dynamic loopback port, verified instance identity, and entered the normal board UI without terminal setup.

After the final token-transport adjustment, a fresh repo-independent copy was launched again as a minimal smoke. Runner and bundled backend were alive, the backend command line did not contain `--instance-token`, `/health` was reached, and normal close left zero processes from that copy.

## 20. Packaged SGF analysis result

PASS. The packaged app imported real `game-3.sgf` (59 moves) through the file picker. The board rendered, whole-game progress/polling displayed `0 / 59` with ETA, and analysis completed. Commentary, move navigation, and a two-highlight review were produced. This proves the packaged backend/API path; the separate real position-judgment run below proves bundled KataGo execution even if a whole-game cache was available.

The original SGF hash/content was not modified.

## 21. Packaged position judgment result

PASS. While whole-game analysis was active, position judgment at move 59 invoked the bundled foreground KataGo client and returned HTTP 200. Production request settings remained 500 max visits, 1 analysis thread × 16 search threads, ownership enabled, and ownership standard deviation enabled. KataGo reported 514 actual visits (normal batching can finish slightly beyond the requested cap).

The board displayed the ownership overlay and floating result window. The observed result was black 190.1, white 170.9, black lead 8.1, black win rate 96.5%, white 3.5%. Closing the window retained the existing overlay lifecycle behavior.

## 22. Variation/trial result

PASS. From the move-46 recommendation link, the packaged app entered the existing trial mode, rendered a seven-move PV with relative numbering 1–7 over official move 45, and exposed `結束試下`. Closing trial removed temporary PV state and restored official move 46 with trial mode off. No PV/trial stones were written to the SGF or official history.

## 23. Review UI result

PASS. After completed analysis, `本局復盤` showed two highlights. The primary action opened move 46. `開始復盤` opened chronological move 14 as `1 / 2`; next moved to move 46 as `2 / 2`. Objective evidence, structured LogosGo explanation, detailed commentary, and the recommendation/variation integration all rendered in the existing UI.

## 24. Shutdown during idle

PASS. Closing the normally running packaged app exited Runner and backend, left no KataGo process, and released the observed dynamic port 49551. The final post-build smoke likewise left zero processes rooted in its repo-independent bundle path.

## 25. Shutdown during analysis

PASS. A 134-move real SGF was loaded and analysis was closed while active. Before close, the verified tree was Runner -> bundled backend -> bundled KataGo. After close there was no matching Runner, backend, or KataGo process.

Abnormal protection also passed: after SIGKILL of the Runner in a separate run, the one-second parent watchdog removed backend and KataGo without leaving an orphan.

## 26. Failure/recovery results

The practical missing-backend test used a copied app with the backend removed and the outer bundle re-signed. The startup UI showed `LogosGo 安裝不完整，缺少必要資源：logosgo-backend` and a `重試` button; it did not expose a raw network exception.

Other failure paths are bounded in code/tests:

- resource root and KataGo are validated before launch;
- process launch/early exit retries at most three times;
- a port race gets a fresh launch/port attempt;
- wrong service/token/instance identity fails readiness;
- startup timeout is 60 seconds, never infinite;
- a later KataGo launch error is returned by the existing API error handling;
- Flutter bootstrap failure and retry are covered by widget tests.

No failure test left a child process. Missing model/config/corpus and wrong-identity behavior are covered by the Phase 6B runtime/startup and native identity contracts rather than destructively repeating every live bundle variant.

## 27. Repository-independence evidence

The full E2E and final smoke used app copies under `/private/tmp`, outside `~/Desktop/go_project`. Process paths for Runner, backend, and KataGo all resolved inside the copied `.app`. The child had no `PYTHONPATH`, venv activation, Python command, current-working-directory dependency, or source-tree resource lookup. Backend health, SGF import, analysis, position judgment, review, variation, and shutdown all worked from that copy.

## 28. Homebrew-independence evidence

The final app was recursively scanned after assembly. All Mach-O dependencies and load commands contain zero `/opt/homebrew`, `/usr/local`, or `/Users/...` runtime paths. Embedded third-party dylibs use bundle-relative references. The packaged process environment uses only the system executable PATH and bundle-explicit native paths; Homebrew is a build input, not a runtime requirement.

## 29. Regression results

- Native Runner/XCTest: 4 passed, including endpoint map, random URL-safe token, cross-language instance ID, and dynamic loopback port. The renamed product module required the test import to be corrected from `Runner` to `LogosGo`; final run passed.
- Python full suite: 256 passed (baseline 251; new tests account for the increase).
- Flutter full suite: 59 passed (baseline 56; new bootstrap tests account for the increase).
- `flutter analyze`: the same 13 baseline diagnostics (2 warnings, 11 info); no new Phase 6B-4 analyzer error/warning.
- Python `py_compile`: passed with bytecode redirected outside the repository.
- Packaging shell `bash -n`: passed.
- `git diff --check`: passed.
- Final Release build, native runtime checks, plist validation, and deep/strict codesign verification: passed.
- Real packaged E2E, idle shutdown, active-analysis shutdown, parent-death cleanup, and startup-failure UX: passed.

No full 336-move benchmark was rerun because the required packaged behavior was proven with shorter real SGFs and settings/hash verification.

## 30. Remaining private-release issues

No blocking private-V1 issue remains on the supported Apple Silicon/macOS 26 target. Deliberate scope limits remain:

- the app is ad-hoc signed and not notarized, so another Mac may show the expected Gatekeeper warning;
- Developer ID signing, notarization, installer/ZIP distribution, GitHub release, Windows, Intel, and older macOS support are not part of this phase;
- a clean second physical Mac without developer tools is still the strongest future distribution acceptance test.

These are public-distribution or wider-compatibility tasks, not defects in the requested private self-contained app.

## 31. Confirmation frozen analytical behavior is unchanged

Phase 6B-4 did not change `analysis.cfg`, `model.bin.gz`, analytical thresholds, schemas, classifiers, review selection/summary, commentary, preemption, cancellation/resume, perspective conversion, ownership behavior, or trial/variation semantics.

Verified production settings remain:

- whole-game: `maxVisits = 100`, `analysisPVLen = 8`, ownership off, concurrency 16×4;
- position judgment: `maxVisits = 500`, concurrency 1×16, ownership and ownership stdev on;
- KataGo Metal runtime and the same model/config/corpus hashes embedded in the app.

LogosGo.app can therefore launch normally on the supported Mac without a terminal, source repository, Python installation, venv, or Homebrew runtime. It automatically owns and verifies its standalone backend, uses the bundled portable KataGo Metal runtime and unchanged analytical assets, supports real SGF analysis and position judgment, and cleans up backend/KataGo processes when the app exits.

A. FIRST SELF-CONTAINED APP PASS
