# Phase 7B — Windows Runtime Abstraction & Source Preparation

Date: 2026-10-14  
Target: Windows 11 x64 source preparation performed on macOS  
Status: no Windows build or Windows runtime validation is claimed

## 1. Scope

Phase 7B separated the shared Python runtime from operating-system-specific path and process behavior, prepared native-Windows PyInstaller inputs, and documented the future Windows Runner contract. It deliberately did not cross-compile, download or ship Windows binaries, create an installer, change Flutter UI behavior, or begin Phase 7C.

The accepted LogosGo analysis, explanation, review, scheduling, and perspective behavior remains frozen. The work was performed in the existing dirty working tree without reset, restore, checkout, clean, or stash.

## 2. Files changed

Phase 7B changes are limited to:

- `runtime_paths.py`: explicit platform names, executable names, writable directories, packaged Windows resource inference, dependency-directory metadata, and deterministic KataGo runtime candidates.
- `runtime_processes.py`: a small POSIX/Windows boundary for child creation flags, backend process-group setup, parent monitoring, and termination signal registration.
- `server.py`: uses the shared runtime/process abstractions, runs KataGo in a writable log directory, and exposes a token-authenticated local `/shutdown` endpoint.
- `packaging/macos/backend.spec`: includes the new `runtime_processes` module so the existing macOS packaged backend remains complete.
- `packaging/windows/backend.spec`: native-Windows x64 PyInstaller onedir input.
- `packaging/windows/build_backend.ps1`: native-only Windows backend build entry point with isolated build/dist directories.
- `packaging/windows/requirements-backend.txt` and `requirements-build.txt`: separated pinned runtime and packaging dependencies.
- `packaging/windows/README.md`: native build prerequisites, planned runtime layout, Runner contract, KataGo fallback policy, and dependency policy.
- `.gitignore`: ignores platform-specific packaging build outputs.
- `test_runtime_paths.py`, `test_runtime_processes.py`, `test_backend_startup.py`, `test_backend_packaging.py`, and `test_windows_packaging.py`: portability and packaging contract coverage.
- `flutter_application_1/macos/Runner/AppDelegate.swift`: removed an invalid call to `super.applicationWillTerminate`, discovered by the required real shutdown smoke test; backend cleanup remains in place.
- `flutter_application_1/macos/RunnerTests/RunnerTests.swift`: regression test for safe termination without a running backend.

## 3. Files intentionally untouched

Phase 7B made no changes to the Flutter/Dart UI, the Windows Runner sources, SGFs, model, corpus, analysis thresholds, review/explanation implementation, or branding assets. In particular, it did not change `analysis.cfg`, `analysis_logic.py`, `logos_engine.py`, `structured_explanation.py`, `directional_explanation.py`, `review_selection.py`, `review_summary.py`, or `flutter_application_1/lib/main.dart`.

Some of those paths already have accepted Phase 1–7A working-tree changes; Phase 7B preserved them exactly rather than reverting or folding them into this phase. The frozen archive `release/v1.0.0/LogosGo-v1.0.0-macOS-arm64.zip` was not rebuilt or edited.

## 4. Original platform assumptions found

- Runtime discovery understood source-tree paths and macOS `.app/Contents`, but not a packaged Windows `runtime/` tree.
- Executable validation assumed POSIX execute bits and no `.exe` naming.
- Writable paths were macOS-only (`~/Library/Application Support`, `Caches`, and `Logs`).
- Backend startup used `os.setpgid`, POSIX PID probing, and POSIX signals directly in `server.py`.
- KataGo launch had no explicit Windows console-window policy.
- The macOS Runner owns the dynamic-port/token handshake and bundle paths; the existing Windows Runner is still the default Flutter template and has no `logosgo/backend` MethodChannel.
- Windows OpenCL/Eigen selection, DLL placement, Job Object cleanup, and native startup diagnostics did not yet have an explicit source contract.
- The macOS termination smoke exposed an unrelated lifecycle defect: `FlutterAppDelegate` does not implement the selector reached by `super.applicationWillTerminate(notification)`. Calling it caused the App to terminate with an unrecognized-selector exception after trial use. Removing that invalid super call preserved the intended `backendController.stop()` cleanup.

## 5. Runtime abstraction architecture

`runtime_paths.py` now owns the platform-neutral runtime model:

- `platform_identifier`: `macos`, `windows`, or `posix`.
- `RuntimeNames`: stable backend and KataGo executable names.
- `RuntimePaths`: immutable resource root, model, config, corpus, KataGo path, runtime dependency directory, writable paths, and packaged/development mode.
- `WritablePaths`: application state, cache, log, and temporary directories.
- `KataGoRuntimeCandidate`: ordered backend type and executable path.

Explicit CLI/environment paths remain highest priority. Packaged resource discovery never depends on the current working directory. Development mode still resolves from the source module and may use `PATH`; packaged mode must resolve complete bundled resources.

`runtime_processes.py` is the single boundary for process differences. Shared analysis code still passes argument arrays to `subprocess.Popen`; no `shell=True` was introduced.

## 6. macOS path behavior

The existing macOS behavior is preserved:

- application state: `~/Library/Application Support/LogosGo`
- cache: `~/Library/Caches/LogosGo`
- logs/KataGo working directory: `~/Library/Logs/LogosGo`
- temporary state: the system temporary directory under `LogosGo`
- packaged resources: the established `.app/Contents/Resources/LogosGo` and helper layout
- executable names: `logosgo-backend` and `katago`

The real macOS backend/KataGo smoke test confirmed that development path resolution and both analysis lanes still work.

## 7. Planned Windows path behavior

Windows uses environment/platform data rather than user-specific hard-coded paths:

- application state: `%LOCALAPPDATA%\LogosGo`
- cache: `%LOCALAPPDATA%\LogosGo\Cache`
- logs: `%LOCALAPPDATA%\LogosGo\Logs`
- temporary state: `%TEMP%\LogosGo` (or `%TMP%`, then the platform temporary API)
- backend executable: `logosgo_backend.exe`
- KataGo executable: `katago.exe`

If `LOCALAPPDATA` is unavailable, the resolver logs a warning and uses the profile-relative `AppData\Local\LogosGo` fallback. Pure-logic tests cover spaces and Unicode in these paths. Native wide-character process launch remains a Windows Runner responsibility.

## 8. Process lifecycle abstraction

On POSIX/macOS, behavior remains a dedicated backend process group, SIGTERM/SIGINT handling, parent-PID liveness probing, graceful close, and existing hard-kill fallback in the macOS Runner.

On Windows, prepared Python paths use `CREATE_NO_WINDOW` for KataGo, avoid POSIX process groups, can monitor the owning parent through a Win32 process handle, and register only signals supported by Python on that platform. These branches are source-preparation code and are not marked as Windows-validated.

The backend now also provides local `POST /shutdown`, authenticated by `X-LogosGo-Instance`. The Windows Runner must call it first, wait for bounded graceful exit, and use a Job Object with kill-on-close as the authoritative descendant-cleanup fallback. The Job Object is intentionally not emulated in Python or on macOS.

## 9. KataGo backend selection design

The planned Windows candidate order is deterministic:

1. official KataGo v1.16.4 OpenCL x64 at `runtime/katago/opencl/katago.exe`
2. official KataGo v1.16.4 non-AVX2 Eigen x64 at `runtime/katago/eigen/katago.exe`

Generic packaged candidates follow only for diagnostics/compatibility. Discovery does not claim that OpenCL works. Phase 7C must perform a bounded real initialization probe with the frozen model/config, capture diagnostics, and choose Eigen only after a definite OpenCL failure. The selected executable is passed explicitly to the backend.

## 10. Windows packaging file layout

Planned application layout:

```text
LogosGo/
├── LogosGo.exe
├── flutter_windows.dll
├── data/...
└── runtime/
    ├── backend/logosgo_backend/
    │   ├── logosgo_backend.exe
    │   └── _internal/...
    ├── katago/opencl/katago.exe + official DLLs
    ├── katago/eigen/katago.exe + official DLLs
    ├── model/model.bin.gz
    ├── config/analysis.cfg
    ├── data/logosgo_corpus_full.csv
    ├── licenses/...
    └── manifest/...
```

Immutable assets stay under `runtime/`; all writable data stays in per-user system directories. The Python backend is an onedir payload rather than a onefile executable, avoiding unnecessary extraction/runtime complexity for large scientific dependencies.

## 11. PyInstaller native-Windows build instructions

On a real Windows 11 x64 host with Windows x64 Python 3.14:

```powershell
py -3.14 -m venv .venv-packaging-windows
.\.venv-packaging-windows\Scripts\python.exe -m pip install `
  -r packaging\windows\requirements-backend.txt `
  -r packaging\windows\requirements-build.txt
packaging\windows\build_backend.ps1 `
  -PythonExecutable .\.venv-packaging-windows\Scripts\python.exe
```

The script refuses non-Windows and non-x64 hosts, cleans only its own `packaging/windows/build` and `dist` directories, runs the separate Windows spec, and verifies the expected `logosgo_backend.exe`. PyInstaller is not a cross-compiler; this command was not run on macOS. PowerShell itself was unavailable on the Phase 7B host, so native parsing/execution remains Phase 7C work.

## 12. Flutter Windows Runner plan

The repository already contains the standard Flutter Windows Runner, but it does not yet implement LogosGo backend lifecycle integration. Phase 7C must implement:

1. resolve the packaged `runtime/` tree with Win32 wide-character paths;
2. probe OpenCL then select non-AVX2 Eigen fallback with bounded diagnostics;
3. reserve a loopback dynamic port with a bounded launch-race retry;
4. generate a random URL-safe instance token;
5. call `CreateProcessW` with explicit absolute arguments and a controlled child environment;
6. assign the backend to a kill-on-close Job Object before descendants can escape;
7. redirect logs to `%LOCALAPPDATA%\LogosGo\Logs`;
8. authenticate `/health` and verify service, API schema, instance identity, and token;
9. expose `{host, port, instanceToken}` through MethodChannel `logosgo/backend`, method `getBackendConfiguration`;
10. on normal close, call authenticated `/shutdown`, wait, then terminate the Job Object if needed; and
11. prove abnormal Runner death leaves no Python backend or KataGo child.

Packaged Release must not silently fall back to port 5001.

## 13. DLL/runtime dependency plan

- Keep every DLL from each official KataGo archive beside its matching executable until a native dependency/license inventory proves otherwise.
- Do not copy DLLs from a developer machine, bundle GPU drivers, or bundle an OpenCL ICD supplied by the machine vendor.
- Bundle all PyInstaller Python dependencies inside the onedir backend payload.
- Inspect every final PE import and decide whether the Microsoft Visual C++ runtime is app-local or installed through the supported redistributable.
- Keep Flutter-generated `flutter_windows.dll` and plugin DLLs in Flutter's standard release layout.
- Record source URL, exact version, architecture, SHA-256, and license for all staged native files.
- Validate the final portable directory on a clean Windows 11 x64 VM with no Python, Flutter, or Visual Studio installed.

## 14. Tests run on macOS

- Full Python regression: **271 tests passed**.
- Focused portability/backend tests: **40 tests passed**.
- Python compile check: every tracked/untracked project `.py` file compiled successfully using `py_compile` with a temporary cache prefix.
- Flutter unit/widget regression: **59 tests passed**.
- Flutter static analysis: completed with exit code 0 and 13 pre-existing diagnostics in `lib/main.dart`; Phase 7B did not modify Dart source.
- macOS Runner XCTest: **5 tests passed**, including dynamic port, random URL-safe token, identity hash, channel value, and safe application termination.
- macOS packaging shell scripts: all five scripts passed `bash -n`.
- `git diff --check`: passed.
- Windows pure-logic scaffolding: Windows naming, LOCALAPPDATA/TEMP/fallback, Unicode/spaced paths, packaged resource inference, OpenCL-before-Eigen ordering, process flags, packaging layout, module inclusion, and native-only build-script contract passed on macOS.

These injected-platform tests validate deterministic shared logic only; they do not validate Windows APIs or runtime behavior.

## 15. macOS regression results

- Backend started on loopback with an explicit dynamic test port and instance token.
- Authenticated `/health` returned the expected service identity and token verification.
- A two-move SGF whole-game request completed 2/2 positions with the frozen 100-visit/PV8/no-ownership request behavior.
- Position judgment completed with 515 actual visits and returned 361 ownership plus 361 ownership-stdev values, preserving the 500-visit/1×16 ownership lane.
- Authenticated `/shutdown` returned `shutting_down`; backend and KataGo exited.
- Real Flutter UI smoke imported `game-3.sgf`, displayed 59/59 moves, started whole-game analysis, accepted cancellation, and remained responsive.
- After the termination regression fix, a rebuilt real Flutter macOS app launched and quit without the previous unrecognized-selector exception; Flutter reported only `Lost connection to device`.
- Final process inspection found no remaining LogosGo backend, KataGo, or `flutter run` process.

No frozen release archive was launched, rebuilt, or overwritten during these checks.

## 16. Windows behaviors NOT validated

- No Windows executable, Flutter build, package, or installer was produced.
- `CreateProcessW`, Job Objects, handle inheritance, console suppression, process-handle parent watching, and abnormal cleanup were not executed on Windows.
- The PowerShell build script and PyInstaller Windows spec were not run by native Windows Python.
- Official OpenCL/Eigen archives and their DLLs were not downloaded, staged, or executed.
- OpenCL device discovery, initialization failure diagnostics, and Eigen fallback were not tested.
- Windows firewall, Defender/antivirus, SmartScreen, path-length, Unicode filesystem, school-machine policy, sleep/resume, and multi-launch behavior were not tested.
- The Visual C++ runtime strategy and final PE import closure are not yet validated.
- The default Windows Runner still lacks the required backend lifecycle and MethodChannel implementation.

## 17. Known risks

- The Windows Runner is a documented implementation task, not a completed integration; this is the largest open source-level risk.
- A Job Object must be assigned early enough that KataGo cannot outlive the Runner. Incorrect handle inheritance or nested-job policy could break cleanup.
- Dynamic-port allocation has an unavoidable bind/launch race and needs bounded retries with identity validation.
- OpenCL availability varies by machine and driver; path presence is not proof of successful initialization.
- The non-AVX2 Eigen fallback is expected to be slower and needs responsiveness validation under the frozen 16×4 configuration.
- PyInstaller scientific dependencies may add DLLs or hooks not observable on macOS.
- Windows termination timing around `/shutdown` and forced Job termination must be verified under active whole-game and ownership analysis.
- The exact Visual C++ redistributable/app-local decision and redistribution licenses remain open.

## 18. Exact next steps for Phase 7C

1. Use a native Windows 11 x64 build machine or clean VM; record OS, CPU, GPU, driver, Flutter, Visual Studio, Python, and PyInstaller versions.
2. Verify the source tree and frozen analysis constants before building.
3. Implement the Windows Runner lifecycle contract in the existing Runner using `CreateProcessW`, authenticated health/channel handshake, Job Object kill-on-close, bounded shutdown, and log redirection.
4. Obtain the official KataGo v1.16.4 Windows x64 OpenCL and non-AVX2 Eigen archives; verify provenance, SHA-256, architecture, and licenses.
5. Implement and test the bounded OpenCL initialization probe and deterministic Eigen fallback.
6. Run `packaging/windows/build_backend.ps1` with native Windows Python and inspect the onedir output.
7. Stage the planned runtime layout, then run a native `flutter build windows --release`.
8. Inspect PE architecture and complete EXE/DLL dependency closure; finalize the Visual C++ runtime policy.
9. Run Python/shared tests that are valid on Windows plus Windows Runner unit/integration tests.
10. On a clean Windows 11 x64 VM without developer tools, run SGF import, whole-game analysis, position judgment, cancellation/preemption, review/commentary/variation, Unicode/spaced-path, OpenCL-primary, Eigen-fallback, normal-close, crash-close, and repeated-launch E2E checks.
11. Confirm frozen settings and compare representative black/white results with the accepted macOS baseline.
12. Produce a Phase 7C report with exact binaries, hashes, logs, failures, and an evidence-based gate; do not begin installer/signing work unless separately authorized.

## 19. macOS archive hash before/after

Frozen artifact:

```text
release/v1.0.0/LogosGo-v1.0.0-macOS-arm64.zip
```

- Before Phase 7B SHA-256: `28892525cf3373d82ecddb445ae059fb177d1e39a9f41ca923e101bb4a334509`
- After Phase 7B SHA-256: `28892525cf3373d82ecddb445ae059fb177d1e39a9f41ca923e101bb4a334509`
- Result: identical; the archive was not modified.

Additional frozen-input verification:

- `model.bin.gz`: `93abbeea4b4b38a6b5fda83e58927b588e2ca195ef9816b831db9d629c029efa`
- `analysis.cfg`: `194839bbac3ffef48830e79fa05167a93b3f1b8b602a6b184b954fd72517e796`

## 20. Final gate decision

The shared runtime abstraction, native packaging inputs, tests, and Windows implementation contract are sufficient to proceed to a real Windows environment. The macOS release and accepted analysis behavior remain intact. However, the Windows Runner lifecycle, native PyInstaller output, KataGo OpenCL/Eigen execution, DLL closure, Job Object behavior, and clean-machine E2E remain unimplemented or unvalidated, so an unconditional ready claim would be premature.

B. READY WITH OPEN WINDOWS RISKS
