# Phase 6A — macOS Packaging Audit

Final decision: **A. READY FOR PHASE 6B**

Audit date: 2026-10-07  
Repository: `/Users/ouo1010/Desktop/go_project`  
Initial recommendation: Apple Silicon, macOS 26+, private ZIP distribution

## 1. Executive summary

The Flutter frontend can already be built as a valid macOS release bundle, but
the resulting `.app` is not self-contained. It contains only Flutter and the
`file_picker` plugin. It does not contain or start Flask, Python, KataGo, the
model, the analysis config, or the commentary corpus.

The principal blockers are understood:

1. Flask is manually started from the repository and has no app-owned lifecycle.
2. `server.py` hard-codes the developer's model/config paths, locates KataGo
   through shell `PATH`, and loads the corpus relative to the current directory.
3. There is no reproducible backend dependency manifest or bundled Python.
4. The Homebrew KataGo binary depends on Homebrew dylibs whose install names are
   absolute, so copying only `katago` would not work on another Mac.
5. the Release Runner is sandboxed, while the future architecture needs to
   launch a helper that listens on loopback and launches KataGo.
6. Backend address, port, readiness, identity, and shutdown are not managed by
   the app.
7. The current KataGo and Python binaries require macOS 26.0 even though the
   Flutter project advertises an older deployment target.

No deeper technical blocker was found. A small native-runner lifecycle layer,
a standalone Python backend bundle, bundled engine dependencies, and explicit
runtime paths are sufficient for the first private build.

## 2. Current runtime architecture

```text
User terminal
  └─ manually activates/uses ./venv and runs server.py
       ├─ imports local Python modules from the source tree
       ├─ reads logosgo_corpus_full.csv from current working directory
       ├─ serves Flask development server on 0.0.0.0:5001
       └─ lazily starts Homebrew `katago` on first analysis
            ├─ absolute model path in server.py
            ├─ absolute analysis.cfg path in server.py
            └─ relative analysis_logs directory inherited from process cwd

Flutter app
  └─ assumes http://127.0.0.1:5001 already exists
       ├─ POST /analysis/start
       ├─ GET /analysis/<job_id>
       ├─ POST /analysis/<job_id>/cancel
       ├─ POST /analysis/<job_id>/ask
       └─ POST /analyze_position
```

`KataGoClient` uses line-delimited JSON over the child's stdin/stdout and reads
stderr on a separate daemon thread. Two lazy client objects exist: background
16×4 and foreground 1×16. Existing preemption closes the inactive engine so the
two Metal workloads do not intentionally run together.

## 3. Startup and shutdown flow

### Startup today

- No Dart, Swift, Xcode, or Flutter code starts Flask. A repository-wide search
  found no runtime reference that launches `server.py`.
- `server.py:30-37` creates Flask, loads the corpus immediately, sets KataGo to
  `"katago"`, and hard-codes model/config paths.
- `server.py:1103-1104` starts Flask's development server with
  `host='0.0.0.0'`, `port=5001`, and `debug=True`.
- KataGo is lazy-started by `KataGoClient._ensure_started` at
  `server.py:95-120`. The process command is:

  ```text
  katago analysis -model <MODEL_FILE> -config <CONFIG_FILE>
  ```

  Foreground position judgment additionally supplies the existing
  `-override-config numAnalysisThreads=1,numSearchThreadsPerAnalysisThread=16`.

### Readiness and startup failure today

- There is no `/health`, `/ready`, backend identity, version handshake, or
  startup preflight.
- Flutter discovers failure only when its first `/analysis/start` request fails
  or times out after 15 seconds (`main.dart:667-704`).
- A missing corpus fails server import/startup. Missing KataGo/model/config is
  detected only when analysis starts.
- `debug=True` may create a Flask reloader process, making packaged lifecycle
  ownership harder and unsuitable for release.

### Shutdown today

- Flutter's `dispose` only disposes UI controllers. It does not cancel jobs or
  stop Flask.
- Closing the Flutter app leaves manually started Flask running.
- `KataGoClient.close` (`server.py:315-325`) sends process terminate, waits five
  seconds, then kills as fallback.
- Both KataGo clients are registered with `atexit` (`server.py:344-345`), which
  helps on normal Python interpreter exit.
- Query cancellation sends KataGo's query-level `terminate` action and does not
  confuse foreground/background query IDs.
- `atexit` is not guaranteed for `SIGKILL`, interpreter crash, power loss, or a
  force-killed bundled backend. KataGo can therefore become orphaned in those
  cases unless Phase 6B adds parent/process-tree ownership.
- KataGo EOF/process failure correctly fails pending queries; a later request
  may lazy-start a new engine.

## 4. Absolute-path findings

### A. Production runtime blockers

| File:line | Finding | Impact |
|---|---|---|
| `server.py:33` | `logosgo_corpus_full.csv` is cwd-relative | Backend fails outside repository root. |
| `server.py:35` | `KATAGO_EXEC = "katago"` | Requires Homebrew/shell `PATH`. |
| `server.py:36` | `/Users/ouo1010/Desktop/go_project/model.bin.gz` | Always fails on another Mac. |
| `server.py:37` | `/Users/ouo1010/Desktop/go_project/analysis.cfg` | Always fails on another Mac. |
| `analysis.cfg:11` | `logDir = analysis_logs` | Writes relative to inherited cwd; unsafe if cwd is app resources. |
| `main.dart:673` | fixed `127.0.0.1:5001/analysis/start` | No packaged runtime discovery. |
| `main.dart:748` | fixed progress URL | Same blocker. |
| `main.dart:848` | fixed cancel URL | Same blocker. |
| `main.dart:928` | fixed position URL | Same blocker. |
| `main.dart:1350` | fixed ask URL | Same blocker. |

### B. Development/test-only

- `test.py:133` hard-codes `/opt/homebrew/bin/katago`; this is a standalone
  developer tester, not the Flutter/Flask runtime.
- `main.py:22-25` assumes `katago`, model/config, and sample SGF in cwd; it is a
  legacy interactive CLI/plotting tool and is not called by the app.
- Generated `flutter_application_1/ios/Flutter/Generated.xcconfig:2-3` contains
  developer Flutter/project paths. It is generated build metadata for iOS, not
  a macOS runtime dependency.

### C. Documentation

Existing `docs/` reports mention repository/model paths descriptively. They are
not read by production code.

### D. Benchmark/validation artifacts

- `benchmark/configs/*.cfg:11` and
  `benchmark/visits_configs/config_16x4.cfg:11` contain developer-specific log
  paths by design.
- `benchmark/results.json`, `benchmark/visits_results.json`, raw stderr logs,
  and `benchmark/katago_logs/**` record `/Users/...` and Homebrew paths from past
  runs.
- `analysis_logs/**` records absolute paths printed by KataGo.

These directories must not be copied into the production app and are not
packaging blockers.

### E. Harmless examples

README text, comments, sample SGF names, and past command examples are not used
at runtime. No production absolute path other than `server.py:36-37` was found.

## 5. Python dependency findings

### Current interpreter and reproducibility

- Development venv: Python **3.14.2**, arm64, symlinked to Homebrew
  `/opt/homebrew/opt/python@3.14/bin/python3.14`.
- The Homebrew Python framework itself declares minimum macOS **26.0**.
- There is no `requirements.txt`, `pyproject.toml`, Pipfile, Poetry lock, or
  equivalent reproducible backend manifest.
- The venv's full `site-packages` directory is about 196 MiB and contains
  legacy/development packages that the production backend does not need.

### Production direct third-party imports

- `Flask`
- `flask-cors`
- `sgfmill`
- `pandas`

The effective transitive runtime set includes Werkzeug, Jinja2, MarkupSafe,
itsdangerous, click, blinker, NumPy, python-dateutil, pytz, tzdata, and six.

### Standard library imports

`subprocess`, `json`, `os`, `threading`, `uuid`, `time`, `shutil`, `random`,
`atexit`, `queue`, `collections`, `dataclasses`, `math`, and `typing`.

### Project-local runtime modules

- `analysis_logic.py`
- `sgf_utils.py`
- `logos_engine.py`
- `review_selection.py`
- `review_summary.py`
- `structured_explanation.py`
- `directional_explanation.py`
- `explanation_features.py`
- `explanation_classifier.py`

### Development/legacy-only dependencies

Matplotlib and its plotting/image dependencies are used by legacy `main.py`,
not Flask. Benchmark/test scripts also use tooling that should not ship.

### Assumptions and packaging options

- The backend does not invoke `python` or `python3`; the current assumption is
  that the user manually launches `server.py` with the activated venv.
- Local imports work because the repository source directory is on `sys.path`.
- Current startup depends on repository cwd for the corpus and KataGo logs.

Recommended Phase 6B approach: build an **arm64 PyInstaller onedir backend** in
a separate pinned packaging environment. Onedir is preferable to onefile here:
startup is deterministic, no large temporary extraction is required, bundled
data/native libraries are inspectable, and crash diagnostics are simpler.
Embedded-Python-by-hand is possible but has more path/signing surface. The
Phase 6B build should first pin only the production runtime dependencies and
validate the chosen bundler against the selected Python version.

## 6. KataGo findings

- Resolved executable:
  `/opt/homebrew/Cellar/katago/1.16.4/bin/katago`
- `/opt/homebrew/bin/katago` is a symlink into that Homebrew Cellar.
- Version inferred from the installed path/logs: **v1.16.4 Metal**.
- Architecture: **arm64** Mach-O executable.
- Size: 5,532,432 bytes (about 5.3 MiB).
- Minimum macOS encoded in the binary: **26.0**.
- System dependencies include Metal, MetalPerformanceShaders,
  MetalPerformanceShadersGraph, Foundation, libc++, libSystem, zlib, and Swift
  runtime libraries.
- Non-system dependency:
  `/opt/homebrew/opt/libzip/lib/libzip.5.dylib`.
- `libzip` further depends on Homebrew `liblzma.5.dylib` and
  `libzstd.1.dylib`. Their current sizes total under 1 MiB, but their install
  names are also absolute Homebrew paths. `liblzma` and `libzstd` require
  macOS 26.0; `libzip` requires macOS 15.0.

Copying only the KataGo binary is therefore insufficient. Phase 6B must bundle
the three non-system dylibs and rewrite install names/rpaths to bundle-relative
locations, or use an equivalently self-contained build of the same KataGo
version. No KataGo download, replacement, or version change occurred here.

KataGo has no model/config cwd requirement because both are passed explicitly.
It communicates only through JSON lines on stdin/stdout. Stderr is diagnostic.
The only cwd-sensitive engine setting is `logDir = analysis_logs`.

## 7. Model/config findings

| Asset | Size | Current lookup | Writable? | Bundle feasibility |
|---|---:|---|---|---|
| `model.bin.gz` | 271,452,845 bytes / 258.9 MiB | hard-coded absolute path | read-only | Can be read directly from Resources. |
| `analysis.cfg` | 22,789 bytes | hard-coded absolute path | config itself read-only | Can be read directly from Resources. |

`analysis.cfg` does not reference another model or pattern file. Its only active
path is relative `logDir = analysis_logs`. The frozen analytical values remain:

- `reportAnalysisWinratesAs = BLACK`
- `maxVisits = 500` default
- `numAnalysisThreads = 16`
- `numSearchThreadsPerAnalysisThread = 4`
- `nnMaxBatchSize = 64`
- `nnCacheSizePowerOfTwo = 23`

The whole-game request still overrides visits to 100, and foreground position
analysis still overrides concurrency to 1×16. Phase 6B should keep the packaged
config byte-equivalent for analytical settings and launch KataGo with a writable
log cwd (or a packaging-only log path override).

## 8. Runtime asset inventory

| Asset | Required? | Purpose | Current lookup | Destination recommendation |
|---|---|---|---|---|
| PyInstaller backend + local modules | Yes | Flask/API/analysis logic | source repo + venv | `Contents/Helpers/LogosGoBackend/` |
| KataGo v1.16.4 arm64 | Yes | analysis engine | shell `PATH` | `Contents/Helpers/KataGo/katago` |
| libzip/liblzma/libzstd | Yes with current engine | KataGo native dependencies | Homebrew absolute paths | helper-local `lib/` with rewritten rpaths |
| `model.bin.gz` | Yes | neural-network model | developer absolute path | `Contents/Resources/LogosGo/model.bin.gz` |
| `analysis.cfg` | Yes | engine configuration | developer absolute path | `Contents/Resources/LogosGo/analysis.cfg` |
| `logosgo_corpus_full.csv` | Yes under current server | LogosEngine startup + legacy endpoint | cwd-relative | `Contents/Resources/LogosGo/logosgo_corpus_full.csv` |
| `rules - rules.csv` | No | not referenced by production runtime | none | do not ship |
| sample/root `game-*.sgf` | No | development samples | none | do not ship |
| `棋譜/` | No | validation/test data | none | do not ship |
| `temp_upload.sgf` | No | stale development artifact | none | do not ship |
| benchmark/testdata/docs/logs | No | engineering evidence | none | do not ship |

Executable helpers should be placed where future nested-code signing is
well-defined, not mixed with ordinary user data.

## 9. Writable and temporary data findings

### Current production runtime writes

- KataGo writes logs to `analysis_logs` relative to its cwd
  (`analysis.cfg:11`). During development this is the repository's
  `analysis_logs/` directory.
- Analysis jobs, results, ETA history, and on-demand commentary cache are memory
  only.
- Flutter reads the selected SGF into memory and sends its content to Flask. It
  does not require the backend to reopen the user's file.
- Flask does not write uploaded SGFs or generated JSON to disk.

### Non-production writes

- `sgf_parser.py:63-64` downloads SGFs into a username directory, but that
  utility is not imported by the app.
- Benchmark and validation scripts write under `benchmark/`; they must not ship.

### Correct future destinations

| Data | Destination |
|---|---|
| KataGo logs | `~/Library/Logs/LogosGo/KataGo/` |
| Backend/launcher logs | `~/Library/Logs/LogosGo/` |
| Mutable settings/state, if later added | `~/Library/Application Support/LogosGo/` |
| Recomputable analysis cache, if later added | `~/Library/Caches/LogosGo/` |
| One-run handshake/temp data | system temporary directory, deleted on exit |
| Imported SGF | remain at user-selected location; do not copy by default |

The app bundle must be treated as read-only. A PyInstaller onedir backend avoids
onefile extraction and does not need to write beside source code.

## 10. Flutter macOS findings

- Product name: `flutter_application_1`
  (`macos/Runner/Configs/AppInfo.xcconfig:8`).
- Bundle identifier: `com.example.flutterApplication1`
  (`AppInfo.xcconfig:11`).
- Version/build: `1.0.0+1`.
- Project deployment target: macOS 10.15; built x86_64 slice uses 10.15 and
  arm64 slice uses 11.0.
- Actual frontend executable is universal x86_64 + arm64, although the backend
  and engine target are arm64 only.
- Debug/Profile and Release both enable App Sandbox. Release entitlements are:
  app sandbox, user-selected read-only files, and network client.
- Release lacks network-server entitlement. More importantly, the sandboxed
  host is not currently designed to launch a bundled backend/KataGo process.
- For private V1, the simplest viable choice is to **disable App Sandbox** rather
  than design and sign a sandboxed helper/XPC service. App Store distribution is
  outside current scope.
- The file picker requests `.sgf` with `withData: true`; user-selected read-only
  access is sufficient, and content is loaded into memory immediately.
- Flutter uses package `http` over Dart I/O to loopback. Release has network
  client permission. There is no observed ATS-specific blocker, but the final
  bundled release must verify plain loopback HTTP on a clean Mac.
- The macOS AppDelegate only closes the app when its last window closes. The
  native runner contains no backend startup/shutdown code.
- The default app name, example bundle identifier/copyright, and generic icon
  are release polish findings, not core packaging blockers.

## 11. Backend lifecycle findings

Existing useful infrastructure:

- `KataGoClient.close` has terminate/wait/kill fallback.
- both engine clients have `atexit` cleanup;
- pending queries are failed on engine EOF;
- foreground/background cancellation IDs are separate;
- the app already exposes explicit whole-game cancel behavior.

Missing infrastructure:

- an app-owned backend process;
- bundle-relative resource discovery;
- production WSGI/server startup without debug reloader;
- readiness/identity handshake;
- backend crash notification/restart UX;
- graceful backend shutdown initiated by the app;
- force-quit/parent-death cleanup;
- process-tree ownership preventing orphan KataGo;
- persistent backend/engine logs outside the bundle.

The safest owner is the **native macOS Runner**, not a Flutter widget. Native
ownership survives Dart isolate/UI failure, resolves `Bundle.main` resources,
has application termination callbacks, and can expose connection information to
Dart through one MethodChannel. Flutter should remain an API client.

## 12. Port and readiness findings

Port 5001 is hard-coded once in Flask and five times in Flutter. It is not
configurable.

Current collision behavior:

- if another process owns 5001, manual Flask startup fails;
- Flutter receives no startup-specific explanation;
- if an unrelated service answers compatible-looking requests, Flutter can talk
  to the wrong process and may send SGF content to it;
- two LogosGo instances cannot safely share the fixed port;
- no ownership token or API identity is checked.

Recommendation: **B. dynamically allocate a loopback port.** The backend should
bind `127.0.0.1` with port `0` through a controllable production server, print a
single machine-readable readiness record containing the selected port, and
verify a per-launch instance token. The native runner passes the endpoint/token
to Dart. This avoids fixed-port collision and wrong-service attachment without
global process discovery.

Phase 6B should add a lightweight endpoint such as:

```json
{
  "service": "LogosGoBackend",
  "api_version": 1,
  "app_version": "1.0.0",
  "instance_id": "<per-launch token>",
  "ready": true
}
```

Readiness should validate that bundled executable/model/config/corpus paths are
present, without starting a KataGo search. All normal requests should carry the
same instance token, or at minimum the readiness response must be matched to the
owned child process.

## 13. Release-build findings

Command:

```text
flutter build macos --release
```

Result: **success**.

- Output:
  `flutter_application_1/build/macos/Build/Products/Release/flutter_application_1.app`
- Flutter reported 42.2 MB; on-disk `du` is approximately 40.3 MiB.
- The app contains FlutterMacOS.framework (~28 MiB), App.framework (~12 MiB),
  file_picker.framework, executable, resources, and ad-hoc signature.
- It contains no backend, Python runtime, KataGo, model, config, or corpus.
- Executable architectures: x86_64 and arm64.
- Bundle metadata: `com.example.flutterApplication1`, display name
  `flutter_application_1`, minimum version 10.15.
- `codesign --verify --deep --strict` passes for the current frontend bundle.
- Signature is ad hoc with no TeamIdentifier. Gatekeeper assessment rejects it,
  as expected for this private unsigned/not-notarized build.
- Plists and entitlements pass `plutil -lint`.
- The resulting Release signature unexpectedly includes
  `com.apple.security.get-task-allow`; this should be removed during final
  private build hardening, although it does not block Phase 6B development.

This is a frontend build smoke result, not a deliverable LogosGo package.

## 14. Size estimate

| Component | Approximate uncompressed size |
|---|---:|
| Current Flutter release app | 40.3 MiB |
| `model.bin.gz` | 258.9 MiB |
| KataGo | 5.3 MiB |
| KataGo Homebrew dylibs | <1 MiB |
| Config + corpus | <32 KiB |
| Candidate standalone Python backend | roughly 100–180 MiB |

The current runtime subset includes about 104 MiB of pandas + NumPy alone; the
Homebrew Python framework is about 77 MiB before bundler pruning. A realistic
first uncompressed app estimate is **405–485 MiB**. A ZIP is likely roughly
**330–430 MiB** because the 259 MiB model is already gzip-compressed.

This is large but not an obvious blocker for private desktop distribution. A
future removal of pandas from the runtime path could reduce size, but it is not
necessary for the first package and is not part of this audit.

## 15. Private-distribution and security findings

- The existing ad-hoc app is rejected by Gatekeeper. Private testers will need
  right-click Open/system approval, and a ZIP must preserve executable bits.
- Downloaded ZIP/app quarantine can affect both the outer app and nested helper
  executables. Phase 6B must test the exact transferred ZIP, not only the local
  build directory.
- The future nested backend, KataGo, and dylibs must be copied before the final
  outer ad-hoc signing step; executable permission must remain set.
- Current Flask binds `0.0.0.0` and runs `debug=True` with unrestricted CORS.
  This exposes the service beyond localhost and is unsuitable for distribution.
  Phase 6B must bind only `127.0.0.1`, disable debug/reloader, and use the
  per-launch identity token.
- No cloud service is required or recommended.
- Developer ID signing, notarization, DMG, App Store sandboxing, and Windows are
  explicitly deferred.

## 16. P0 findings

1. **No self-contained backend or lifecycle owner.** The current `.app` cannot
   start analysis on its own and therefore cannot meet the requested user flow.
   Phase 6B must bundle/start a backend and connect Flutter to it.

This is a current-state packaging blocker with a clear implementation path, not
an unknown feasibility blocker.

## 17. P1 findings

1. `server.py:36-37` hard-code this developer's model/config paths.
2. `server.py:33` requires repository cwd for the corpus.
3. KataGo is found through `PATH`; the app would depend on Homebrew.
4. The copied Homebrew engine would fail without bundled/relinked libzip,
   liblzma, and libzstd.
5. No pinned production dependency manifest or standalone Python runtime exists.
6. App Sandbox is enabled in Release but the proposed child backend/engine
   architecture has not been made sandbox-compatible.
7. Relative KataGo log output would target an undefined or read-only cwd.
8. Current Python/KataGo dependencies require macOS 26, while Flutter metadata
   suggests support back to 10.15/11.0. The first package must declare macOS 26+
   or rebuild dependencies for a lower target.

## 18. P2 findings

1. Port 5001 is fixed, collision-prone, and has no backend identity check.
2. Closing Flutter does not stop Flask or KataGo; crash/force-quit can leave
   orphan processes.
3. Flask uses `0.0.0.0`, debug mode/reloader, and broad CORS.
4. No startup/readiness UX or backend crash/restart notification exists.
5. Backend/KataGo stdout and stderr have no packaged persistent log destination.
6. The frontend is universal while all proposed backend/engine binaries are
   arm64, so an Intel Mac could open the UI but not analyze.
7. Gatekeeper rejects the ad-hoc build and quarantine behavior has not yet been
   tested on a transferred ZIP.
8. Release signing currently includes `get-task-allow`.

## 19. P3 findings

1. Product name is `flutter_application_1`.
2. Bundle identifier/copyright still use `com.example` defaults.
3. Branding/icon/version metadata need final polish.
4. Legacy `main.py`, `sgf_parser.py`, sample SGFs, logs, screenshots, benchmark,
   tests, and unused `rules - rules.csv` must be excluded by the packaging
   manifest.
5. Shipping a universal Flutter frontend is unnecessary for an arm64-only V1
   and costs some size, but it does not block functionality.
6. Pandas is heavy for its current CSV use; dependency reduction is optional
   later and should not delay the first package.
7. Signing, notarization, DMG, automatic updates, and wider macOS compatibility
   remain future distribution work.

## 20. Recommended packaging architecture

```text
LogosGo.app
├─ Contents/MacOS/LogosGo                 Flutter/native Runner
├─ Contents/Helpers/LogosGoBackend/       PyInstaller onedir, arm64
├─ Contents/Helpers/KataGo/
│  ├─ katago                              v1.16.4 Metal, arm64
│  └─ lib/                                relinked non-system dylibs
└─ Contents/Resources/LogosGo/
   ├─ model.bin.gz
   ├─ analysis.cfg
   └─ logosgo_corpus_full.csv
```

Lifecycle:

1. Native Runner creates logs/app-support directories.
2. Runner generates an instance token and starts bundled backend as an owned
   child, passing resource/log paths and parent PID.
3. Backend resolves only explicit bundle/runtime paths, binds
   `127.0.0.1:0`, disables debug/reloader, and emits readiness JSON.
4. Runner validates service identity and gives base URI/token to Flutter through
   a MethodChannel.
5. Flutter uses one centralized API client instead of literal URLs.
6. Backend launches bundled KataGo with explicit model/config paths and a
   writable log cwd. Existing scheduling and all analysis parameters stay
   unchanged.
7. On normal app termination, Runner requests graceful backend shutdown;
   backend cancels jobs and closes both KataGo clients. Runner then uses bounded
   terminate/kill fallback.
8. Backend watches its parent PID, and backend/KataGo share a controllable
   process tree/group so frontend force-quit does not leave an engine orphan.

For the first private V1, disable App Sandbox and set the real app name/bundle
identifier. This is substantially simpler and safer than introducing a signed
XPC helper solely to preserve sandboxing.

## 21. Exact Phase 6B implementation plan

1. **Freeze target and manifest.** Declare Apple Silicon + macOS 26+ for the
   first private build. Add pinned backend runtime/build dependency manifests.
   Validate imports in a fresh packaging venv.
2. **Add a packaging-only backend entry point.** Resolve resource/log paths from
   arguments/environment; run a production controllable server on
   `127.0.0.1:0`; no debug/reloader. Keep all analytical constants untouched.
3. **Add identity/readiness.** Return service/API/app version, instance token,
   and asset readiness. Add tests for wrong token, missing assets, occupied
   resources, and startup failure.
4. **Add graceful lifecycle.** Add shutdown/signal handling that cancels active
   work and calls both existing `KataGoClient.close` methods. Add parent-death
   monitoring and bounded kill fallback tests.
5. **Build PyInstaller onedir backend.** Confirm it runs without repo, venv, or
   shell `PATH`; inspect all imported native libraries and record size.
6. **Bundle KataGo v1.16.4.** Copy the arm64 engine and required dylibs; rewrite
   install names to `@loader_path`/`@rpath`; verify `otool -L` contains no
   Homebrew paths and run a non-analysis startup/version smoke.
7. **Bundle immutable assets.** Copy model/config/corpus to Resources; verify
   model checksum and config analytical settings. Launch KataGo with a writable
   logs cwd so the packaged config remains read-only.
8. **Implement native Runner ownership.** Start/monitor backend, parse readiness,
   expose connection data over MethodChannel, surface startup errors, and stop
   the process tree on app termination.
9. **Centralize Flutter backend access.** Replace five literal URLs with the
   runner-provided base URI/token and wait for readiness before analysis. Do not
   change API schemas or UI analysis behavior.
10. **Adjust private Release configuration.** Disable App Sandbox, make the app
    arm64-only or explicitly reject Intel, align minimum OS with helpers, and set
    LogosGo product/bundle metadata.
11. **Automate bundle assembly.** Add deterministic Xcode/Flutter build phases
    that copy helpers/assets, preserve modes, and ad-hoc sign nested code before
    the outer app. Never manually modify a built app.
12. **Regression and clean-machine validation.** Run Python/Flutter suites,
    build Release, then test a transferred ZIP on another macOS 26+ Apple
    Silicon Mac without repo, Homebrew KataGo, or Python. Verify SGF import,
    whole-game analysis, review/commentary, variation, position judgment,
    cancellation, startup failure UX, and no processes/listeners after close.
13. **Private handoff.** Produce a checksum and concise Gatekeeper/right-click
    Open instructions. Signing/notarization remain a later phase.

If support below macOS 26 is required, insert a separate step before bundle
assembly to build the same Python/KataGo version and dylibs with an agreed lower
deployment target. Do not silently claim the Flutter 10.15 target while helpers
require 26.0.

## 22. Files changed during audit

- Added `docs/phase6a_macos_packaging_audit.md`.
- `flutter build macos --release` generated/updated ignored files under
  `flutter_application_1/build/` and Flutter ephemeral build directories.
- No tracked production, Flutter, backend, config, model, test, benchmark, or
  analytical file was modified by Phase 6A.

Audit commands also inspected signatures, plists, Mach-O architectures,
deployment targets, dylib dependencies, file sizes, and the current venv. No
dependency was installed and no package was assembled.

## 23. Frozen analytical behavior confirmation

Phase 6A did not change:

- whole-game 100 visits or 16×4 concurrency;
- foreground 500 visits, ownership, or 1×16 configuration;
- scheduling, preemption, cancellation, or schemas;
- structured/directional commentary or classifier behavior;
- Review Selection or Review Summary;
- trial/variation, perspective conversion, or thresholds;
- `analysis.cfg`, `model.bin.gz`, KataGo version, Flutter production code, or
  backend production code.

No packaging architecture was implemented and no final package was produced.

**A. READY FOR PHASE 6B**

Packaging blockers are understood and there is a clear implementation path.
