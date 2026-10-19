# Phase 7A — Windows Portability & Packaging Audit

Date: 2026-10-14

Repository: `~/Desktop/go_project`

Scope: audit and design only; no Windows build, production-code change, or analytical change

## 1. Executive summary

LogosGo V1 is suitable for a Windows port without forking the product or rewriting the analysis stack. The Flutter UI, Flask API, SGF logic, KataGo JSON protocol, commentary, review, trial/variation, and ownership rendering can remain shared. The work that is genuinely platform-specific is bounded and identifiable:

- implement the existing `logosgo/backend` bootstrap contract in the Windows Runner;
- launch and own a Windows PyInstaller backend plus KataGo process tree;
- add Windows writable-location and parent-lifecycle branches;
- package a Windows-native KataGo backend and its verified dependencies;
- build and validate everything on Windows x64 hardware.

The largest release risk is not the LogosGo architecture but unknown school-PC hardware. KataGo v1.16.4 publishes Windows x64 OpenCL, Eigen, Eigen AVX2, CUDA, and TensorRT binaries. A CUDA-only build would exclude AMD, Intel, and many machines without a compatible CUDA/cuDNN installation. The recommended Windows V1 package therefore contains **OpenCL as the preferred engine and non-AVX2 Eigen as the compatibility fallback**, with one frozen model/config/data set shared by both. Backend selection must be based on an actual startup/probe result, not GPU-name guessing.

The current Windows Runner is only Flutter's default template. It has no native backend lifecycle controller or MethodChannel implementation, so the present source cannot yet launch a usable Windows release. The current Python path abstraction is a strong base, but `writable_paths()` and parent-death handling are still macOS/POSIX-specific. These are implementation tasks for Phase 7B, not architectural blockers.

Conclusion: Windows V1 is feasible, but real Windows x64 build/test hardware and an accepted OpenCL→Eigen fallback policy are mandatory. No Windows success is claimed in this audit.

## 2. Proposed Windows target

Initial target:

- Product/version: **LogosGo V1.0.0**, an additional platform release beside the frozen macOS V1.0.0.
- OS policy: **Windows 11, 64-bit**.
- CPU architecture: **x86_64/amd64 only**.
- Distribution: initially a self-contained ZIP/portable directory; no installer is required for the first private school build.
- Windows ARM64: out of scope for V1. KataGo v1.16.4's official Windows artifacts used here are x64, the project has no ARM64 Windows validation, and adding emulation/native-ARM combinations would widen the matrix without helping the known school use case.

Flutter currently documents Windows 10 and Windows 11 support, but Windows 10 reached end of support on 2025-10-14. Windows 11 x64 is therefore the reasonable V1 product minimum in 2026 even though some components may happen to run on Windows 10. This is a release-support policy, not an assertion that the shared source is intrinsically incapable of running on Windows 10. See [Flutter supported platforms](https://docs.flutter.dev/reference/supported-platforms), [Flutter Windows setup](https://docs.flutter.dev/platform-integration/windows/setup), and [Microsoft's Windows 10 end-of-support notice](https://support.microsoft.com/en-us/windows/windows-10-support-ends-on-october-14-2025-2ca8b313-1946-43d3-b55c-2b95b107f281).

## 3. KataGo Windows backend options

The exact frozen engine version has official Windows x64 release assets. The [KataGo v1.16.4 release](https://github.com/lightvector/KataGo/releases/tag/v1.16.4) contains, among others:

- `katago-v1.16.4-opencl-windows-x64.zip`;
- `katago-v1.16.4-eigen-windows-x64.zip`;
- `katago-v1.16.4-eigenavx2-windows-x64.zip`;
- CUDA 12.1/12.5/12.8 Windows x64 variants; and
- TensorRT/CUDA Windows x64 variants.

The official v1.16.4 documentation describes these trade-offs:

| Backend | Hardware/runtime | Compatibility | Performance expectation | V1 distribution consequence |
|---|---|---|---|---|
| OpenCL | GPU/accelerator with OpenCL 1.2+ supplied by its driver | Broadest GPU option: NVIDIA, AMD, and many Intel GPUs; driver quality varies | Usually much faster than CPU; first-run tuning may take seconds or minutes | Best default for unknown PCs, but cannot be the only path |
| CUDA | Modern NVIDIA GPU plus compatible CUDA and cuDNN | NVIDIA-only | Can be fast, though v1.16.4 notes OpenCL may beat CUDA on many GPUs | Poor universal school default; adds external runtime/version constraints |
| TensorRT | NVIDIA GPU plus CUDA and TensorRT | NVIDIA-only and most runtime-specific | Often fastest on modern NVIDIA hardware | Too complex and narrow for the first general package |
| Eigen AVX2 | CPU with AVX2/FMA | Common on modern desktop x64 CPUs, but fails outright on unsupported CPUs | Faster CPU fallback | Useful optional optimization only after CPU detection/testing |
| Eigen non-AVX2 | Ordinary x64 CPU | Widest official CPU compatibility | Significantly slower than GPU | Reliable last-resort functional fallback |

Sources: [KataGo v1.16.4 README](https://github.com/lightvector/KataGo/blob/v1.16.4/README.md) and [v1.16.4 compiling guide](https://github.com/lightvector/KataGo/blob/v1.16.4/Compiling.md).

OpenCL's initial tuner requires a writable working directory. The current backend already starts KataGo with `cwd=RUNTIME_PATHS.writable.logs`; after Windows writable paths are corrected this avoids trying to tune inside `Program Files` or another read-only package directory. First launch must show honest progress and retain the engine's diagnostic log because tuning can look like a hang.

## 4. Recommended KataGo strategy

Recommended V1 strategy: **one Windows x64 LogosGo package with two exact-v1.16.4 engine variants**.

1. Prefer official `opencl-windows-x64`.
2. Run a bounded, real initialization probe against the frozen model/config in a writable working directory. A version string or GPU-name check alone is insufficient because it does not prove model initialization and OpenCL kernel tuning work.
3. If OpenCL cannot initialize, exits, or produces a malformed/no-response probe, record its diagnostics and select official **non-AVX2 Eigen**.
4. Pass only the selected absolute `katago.exe` path to the existing backend via `--katago-executable`; the Flask/KataGo JSON pipeline remains unchanged.
5. Cache the selected backend only as machine-local runtime state, keyed by KataGo/model identity and preferably display-driver/device identity. Always offer a diagnostic reset/re-probe route in development. A stale cache must never prevent fallback.

Why not CUDA-only: it excludes AMD/Intel and requires CUDA/cuDNN compatibility outside LogosGo's control. Why not only OpenCL: older/buggy Intel/AMD drivers are an explicit KataGo risk. Why not only Eigen: it maximizes compatibility but may make 100/500-visit analysis unacceptably slow. Shipping both official executables adds only roughly ten megabytes of compressed engine assets, small relative to the existing model, while preserving one model and one analysis protocol.

The package must not redistribute vendor GPU drivers, an OpenCL ICD/runtime, CUDA, or cuDNN without a separate license and deployment review. OpenCL support is expected from the installed graphics driver. KataGo executable/license notices and every bundled DLL's license must be preserved. The repository currently has no top-level `LICENSE`/`NOTICE` inventory, so dependency-license collection is a Phase 7C release requirement, not something to infer silently.

## 5. Model compatibility

The current frozen `model.bin.gz` SHA-256 is:

`93abbeea4b4b38a6b5fda83e58927b588e2ca195ef9816b831db9d629c029efa`

Evidence supporting unchanged use:

- all recommended engine artifacts are official builds of the same KataGo **v1.16.4** release;
- KataGo's documented command line accepts the same `.bin.gz` neural-network model through `-model` for OpenCL, CUDA/TensorRT, and Eigen builds;
- backend choice changes neural-network execution, not the serialized model format or LogosGo's JSON analysis schema;
- the release provides multiple backend binaries, not backend-specific model downloads.

Therefore the existing model is expected to be backend-independent and should be copied byte-for-byte. It must not be converted, renamed semantically, or regenerated. Final compatibility is still gated on Windows probes that start each shipped engine with this exact hash and perform at least one known analysis request. A successful `katago.exe version` alone does not validate the model.

Model redistribution provenance/license is not recorded in the repository's current license inventory. That does not indicate technical incompatibility, but it must be documented before any distribution broader than the existing private school-delivery scope.

## 6. `analysis.cfg` compatibility

Frozen config SHA-256:

`194839bbac3ffef48830e79fa05167a93b3f1b8b602a6b184b954fd72517e796`

Active settings and classification:

| Setting | Classification | Windows finding |
|---|---|---|
| `reportAnalysisWinratesAs = BLACK` | Analytical/semantic | Platform-independent; must stay frozen |
| `maxVisits = 500` | Analytical default | Platform-independent; whole-game requests still override to 100 and position requests explicitly use 500 |
| `numAnalysisThreads = 16` | Hardware/performance | Syntax is portable; suitability is not portable |
| `numSearchThreadsPerAnalysisThread = 4` | Hardware/performance | Syntax is portable; suitability is not portable |
| `nnMaxBatchSize = 64` | Hardware/memory/performance | Backend-neutral syntax but GPU/RAM-sensitive |
| `nnCacheSizePowerOfTwo = 23` | Memory/performance | Backend-neutral but memory-sensitive |
| `nnMutexPoolSizePowerOfTwo = 17` | Performance/memory | Backend-neutral |
| `nnRandomize = true` | Search behavior | Platform-independent; preserve |
| `logDir = analysis_logs` | Relative writable path | Portable only when KataGo's working directory is a Windows user-writable directory |

All Metal, CUDA, TensorRT, OpenCL, and Eigen device settings in the current file are comments. There is no active Metal-only key. The exact file should therefore be used unchanged for the first Windows compatibility probe.

Release recommendation is **B: package a Windows runtime config derived from the frozen config only if real-device calibration proves runtime overrides are required**. The reason is not analytical semantics; it is the unknown GPU/CPU/RAM envelope. Any derived file must preserve perspective, visits, rules supplied per request, komi supplied per request, ownership behavior, cache semantics, and all quality-related values. Only explicitly approved hardware settings such as concurrency, batch size, cache size, Eigen threads, or an OpenCL device selection may differ, with a recorded diff and Windows-specific hash. Phase 7A does not create that file.

## 7. Concurrency portability

The frozen behavior remains:

- whole-game: 100 visits, 16 analysis threads × 4 search threads, PV length 8, ownership off;
- position judgment: 500 visits, 1 × 16 via `-override-config`, ownership and stdev on;
- canonical perspective: BLACK.

Visits, PV length, ownership fields, rules/komi, and perspective are analytical settings and must remain identical. `16×4`, `1×16`, `nnMaxBatchSize=64`, and NN cache sizing are hardware scheduling/resource settings. The current 16×4 result was calibrated on Apple M4/Metal and cannot be declared safe or optimal for an unknown integrated-GPU school PC, an NVIDIA desktop, and Eigen CPU fallback alike.

Potential failure modes include GPU out-of-memory, excessive CPU load, UI/system contention, and very poor Eigen latency. Phase 7C therefore needs a small calibration matrix per shipped backend/device class. This audit does **not** lower or alter concurrency. If Windows must use different hardware settings, that must be an explicit platform runtime profile while analytical output requirements remain frozen.

## 8. Flutter Windows audit

Dependencies in `pubspec.lock`:

- `http 1.6.0`: pure Dart networking used against `127.0.0.1`; no macOS-only dependency.
- `fl_chart`: shared rendering; no audited macOS-only call in the product path.
- `file_picker 8.3.7`: declares `FilePickerWindows` as a Dart/FFI Windows implementation and depends on `ffi`/`win32`. An empty generated native-plugin list is therefore expected for this package version, not proof that picking is unavailable.
- Flutter/Cupertino libraries: shared.

Portable/shared portions:

- board, ownership, review, commentary, trial, variation, and move-number rendering are Dart widgets/painters;
- HTTP endpoint configuration is abstracted by `BackendEndpointConfig`;
- the client restricts the native-injected endpoint to `127.0.0.1` and includes `X-LogosGo-Instance`;
- SGF bytes are read in Flutter, not passed as a host path to Python, reducing path coupling.

Current Windows blockers/gaps:

- `NativeBackendEndpoint` unconditionally invokes MethodChannel `logosgo/backend`, method `getBackendConfiguration`.
- macOS implements that contract in `MainFlutterWindow.swift`; `windows/runner/flutter_window.cpp` does not.
- the Windows Runner is the default template with product/window/binary name `flutter_application_1` and placeholder company metadata.
- no Windows code launches the backend, selects KataGo, polls `/health`, owns shutdown, or injects the endpoint.
- the default Windows icon is not the accepted LogosGo icon.

The shared Dart source appears suitable for Windows, but **`flutter build windows --release` is not sufficient to produce a functioning LogosGo app today**. It may compile in a proper environment, but startup would fail at the missing bootstrap channel and no Windows build has been run. Build success can only be claimed in Phase 7C on Windows.

## 9. Windows Runner design

Keep the same conceptual contract as macOS and implement it in Windows-specific C++:

1. Resolve the directory containing `LogosGo.exe` with a Unicode Win32 API, then validate all bundled paths.
2. Allocate an ephemeral port by binding an IPv4 socket to `127.0.0.1:0`; close it immediately before backend launch and retain the existing bounded launch/retry strategy for the unavoidable race.
3. Generate 32 cryptographically secure random bytes using `BCryptGenRandom`, encode URL-safe Base64, and place the token in the child's environment, not the command line.
4. Select/probe OpenCL then non-AVX2 Eigen as defined in section 4.
5. Launch `logosgo-backend.exe` with `CreateProcessW`, explicit `--port`, `--resource-root`, `--katago-executable`, and `--parent-pid` arguments. Use a correctly quoted wide-character command line, a sanitized environment block, explicit working/log directory, redirected stdout/stderr, and no shell.
6. Create a Windows Job Object before/resume time, set `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, and assign the backend to it. KataGo descendants inherit membership unless deliberately broken away.
7. Poll authenticated `http://127.0.0.1:<port>/health` with short per-request timeouts and a bounded overall startup timeout. Verify service identity, readiness, token verification, API schema, and token-derived instance ID exactly as macOS does.
8. Register MethodChannel `logosgo/backend`; answer `getBackendConfiguration` with `{host, port, instanceToken}` only after verified readiness. Return a localized `FlutterError` on failure.
9. On window close, first request graceful authenticated backend shutdown (the current backend needs a small Windows-capable shutdown mechanism in Phase 7B), wait a bounded interval, then terminate the Job Object if anything remains.
10. If the Runner crashes, Job Object handle closure kills the backend and all KataGo descendants. This is the primary abnormal-parent guarantee; a Windows backend parent watcher may be retained as defense in depth using `OpenProcess(SYNCHRONIZE)` and `WaitForSingleObject`, never `os.kill`.

The Windows controller should mirror the macOS state machine: one start in flight, waiter fan-out, generation invalidation, bounded retries, one cached verified configuration, idempotent stop, and logs that never expose the token.

## 10. Backend portability audit

`runtime_paths.py` strengths:

- uses `pathlib`, absolute explicit paths, and no current-working-directory dependency for immutable resources;
- accepts explicit `--resource-root` and `--katago-executable`, which is the preferred packaged path;
- supports model/config/corpus subdirectory layouts.

Required Windows work:

- `writable_paths()` hard-codes `~/Library/Application Support`, `~/Library/Caches`, and `~/Library/Logs`.
- packaged inference only recognizes an ancestor named `.app/Contents`; a Windows frozen executable cannot infer resources that way. The Runner can and should pass explicit paths, while a Windows inference branch/test remains useful.
- automatic candidates omit `katago.exe`; explicit Runner injection avoids immediate failure, but `.exe` candidates should be supported for development/diagnostics.
- executable validation uses POSIX-shaped `os.access(..., X_OK)`. Its Windows behavior must be tested; existence plus `.exe`/PATHEXT-aware validation may be clearer.

`backend_startup.py` is otherwise portable: argparse, token generation, hashing, host/port validation, and path objects are platform-neutral.

`server.py` strengths:

- KataGo starts with a list of arguments and `shell=False`; spaces/backslashes do not require shell escaping.
- JSON-line routing, locks, queues, cancellation, health identity, and two-lane scheduling are platform-neutral.
- direct child `Popen.terminate()/kill()/wait()` exists and is a useful local fallback.

Required Windows work:

- `os.setpgid(0, 0)` is POSIX-only;
- `os.kill(parent_pid, 0)` is not a valid portable Windows parent-liveness design;
- Unix `SIGTERM`/`SIGINT` lifecycle cannot be the Windows Runner's sole graceful shutdown path;
- process-tree ownership must reside in the Windows Runner Job Object, because terminating only the PyInstaller child is not a complete descendant guarantee;
- comments and diagnostics that specifically assume one resident Metal model should be generalized to the selected Windows backend without changing scheduling behavior.

No analysis, explanation, review, SGF, or API data model requires a Windows rewrite.

## 11. PyInstaller strategy

Use **PyInstaller onedir on Windows**, built natively on Windows. PyInstaller explicitly is not a cross-compiler; a Windows bundle must be produced on Windows. Onedir retains the proven macOS architecture, is easier to inspect and debug, avoids onefile extraction/antivirus overhead, and lets the Runner own a stable child executable. See [PyInstaller operating mode](https://pyinstaller.org/en/stable/operating-mode.html).

Create a separate `packaging/windows/backend.spec` rather than overloading the macOS spec. Reuse the same `server.py` entry point and shared module list, but differ in:

- Windows executable/icon/version metadata and `.exe` name;
- no `target_arch="arm64"`, macOS code-signing identity, entitlements, or `argv_emulation` assumptions;
- Windows-collected Python DLL, CRT/native wheels, and hidden imports;
- explicit exclusion/review of unnecessary packages;
- console strategy. Prefer a console-capable backend with stdout/stderr redirected by `CreateProcessW` and `CREATE_NO_WINDOW`, preserving diagnostics without flashing a console;
- Windows-native build manifest and dependency scan.

The build environment should pin the same production Python package versions where Windows wheels exist. The current mac build used Python 3.14.2, PyInstaller 6.22.3, Flask 3.1.3, pandas 2.3.3, NumPy 2.3.5, and sgfmill 1.1.1. Phase 7C must verify compatible Windows x64 wheels and freeze the actual versions/hashes; it must not assume a macOS onedir can be copied.

## 12. Path abstraction

The Phase 6B-1 abstraction is structurally sound but not yet completely cross-platform. Keep analytical modules unaware of packaging paths and add platform logic only in `runtime_paths.py`, native Runner code, and packaging scripts.

Proposed portable layout:

```text
LogosGo-v1.0.0-Windows-x64/
├── LogosGo.exe
├── flutter_windows.dll
├── data/                         # Flutter runtime assets/AOT data
└── runtime/
    ├── backend/
    │   └── logosgo-backend/
    │       ├── logosgo-backend.exe
    │       └── _internal/...
    ├── katago/
    │   ├── opencl/katago.exe
    │   └── eigen/katago.exe
    ├── model/model.bin.gz
    ├── config/analysis.cfg
    ├── data/logosgo_corpus_full.csv
    ├── licenses/...
    └── manifest/...
```

The Runner supplies `runtime/` and the selected `katago.exe` as absolute paths. `Path.resolve()`, argument lists, and wide-character native launch support drive letters, backslashes, spaces, and non-ASCII components. Do not use string concatenation, `cmd.exe`, or `chdir` as resource discovery.

## 13. Writable locations

Use Windows Known Folder APIs in the Runner when possible, then pass/derive the locations without embedding a username. Recommended mapping:

| Purpose | macOS | Windows V1 |
|---|---|---|
| persistent machine-local app data | `~/Library/Application Support/LogosGo` | `%LOCALAPPDATA%\LogosGo` |
| cache/tuning | `~/Library/Caches/LogosGo` | `%LOCALAPPDATA%\LogosGo\Cache` |
| logs | `~/Library/Logs/LogosGo` | `%LOCALAPPDATA%\LogosGo\Logs` |
| temporary | `$TMPDIR/LogosGo` | `%TEMP%\LogosGo` (prefer per-instance child directory) |

`%APPDATA%` is roaming and is not appropriate for GPU tuning artifacts, large caches, or logs tied to one machine. Use `%LOCALAPPDATA%` from `FOLDERID_LocalAppData`, not a literal `C:\Users\...` path. See [Microsoft Known Folder IDs](https://learn.microsoft.com/en-us/windows/win32/shell/knownfolderid).

V1 currently needs logs and KataGo/OpenCL tuning output. Do not invent user databases or new persistent caches. Package resources remain immutable beside the executable; all writes go to the locations above.

## 14. Process-management findings

| Current behavior | Class | Windows action |
|---|---|---|
| `subprocess.Popen([...], shell=False, stdin/stdout/stderr=PIPE, cwd=...)` | A — already cross-platform | Retain and validate Unicode paths |
| KataGo JSON `terminate` action by query ID | A | Retain; independent of OS process signals |
| `Popen.poll/wait/terminate/kill` on the direct KataGo child | A, but incomplete for trees | Retain; Runner Job Object is final tree fallback |
| `os.setpgid(0, 0)` | B — Windows branch required | Skip on Windows; Job Object replaces process-group ownership |
| `os.kill(parent_pid, 0)` parent watcher | B | Replace with Win32 process handle wait or rely on Job Object, with tests |
| Python `SIGTERM`/`SIGINT` handlers | B | Keep POSIX branch; add authenticated/graceful Windows shutdown path |
| `os._exit()` after engine close | A, intentionally abrupt | Safe as final backend exit, but only after bounded engine close |
| executable-bit checks/chmod | B/C | Windows validates file/PE launchability; no chmod semantics |
| `codesign`, `otool`, `install_name_tool`, Mach-O/RPATH handling | C — macOS packaging only | Do not port; use PE/DLL dependency and optional Authenticode tools |
| shell build scripts in `packaging/macos` | C | Leave frozen; add PowerShell/Python/CMake Windows scripts separately |
| process group `SIGKILL` in Swift Runner | C | Replace with `TerminateJobObject` fallback |
| fork assumptions | D — none found | No action |

Active KataGo termination during request cancellation is protocol-based and portable. Backend/Runner termination is the gap. A Job Object is required because two KataGo processes may exist over time and child cleanup must survive Runner crashes. Normal close should remain graceful first and forceful second.

## 15. Networking

The existing design is valid on Windows:

- bind Flask to `127.0.0.1` only;
- allocate a dynamic port per launch;
- inject that endpoint privately through the native channel;
- authenticate every request with a random instance token;
- verify `/health` service/API/instance identity before exposing the endpoint;
- never listen on `0.0.0.0`, a LAN address, or a fixed shared port.

Loopback HTTP does not require an inbound LAN listener. Windows Defender/endpoint security may still scan or prompt on newly downloaded executables, but LogosGo must not add a firewall rule. The Runner's bind-close-launch sequence has a small port race; preserve the existing identity check and bounded retries so another listener can never be mistaken for LogosGo.

## 16. SGF/file-picker compatibility

`file_picker 8.3.7` declares a Windows implementation using Dart FFI/Win32. The current call requests one custom `.sgf` file with `withData: true`. It consumes bytes when available and only falls back to `File(path).readAsString()`. The original SGF is never opened for writing and must remain unchanged.

Future Windows tests must cover:

- Explorer-style picker and `.sgf` filter;
- upper/lower-case extension behavior;
- selection under a spaced path and a non-ASCII user/profile path;
- cancellation without stale analysis state;
- UTF-8 SGF and legacy/non-UTF-8 metadata behavior;
- a before/after source-file hash proving no modification.

One pre-existing caveat is that the fallback comment claims GB2312/GBK compatibility while Dart `latin1` is not a GBK decoder. This is cross-platform product behavior and out of Phase 7A scope; it is not a Windows packaging blocker, but a Chinese legacy-encoded fixture should be included if such SGFs are a release requirement.

## 17. Unicode/path findings

Positive findings:

- Python uses `pathlib` and `subprocess` argument arrays, not shell-joined commands.
- Flask receives SGF content, so backend analysis does not reopen the user's SGF path.
- Windows project defines `UNICODE` and `_UNICODE`; its entry point is `wWinMain`.
- the file picker uses Win32 wide APIs through the package's Windows implementation.

Required safeguards:

- native Runner resource discovery and launch must use `GetModuleFileNameW`, `CreateProcessW`, and wide environment/argument handling;
- do not convert resource paths through an ANSI code page;
- do not invoke `cmd.exe`, PowerShell command strings, or manual backslash escaping at runtime;
- verify `C:\Users\Test User\...`, `C:\Users\測試\...`, drive-letter paths, and mixed-case paths on NTFS;
- ensure logs and JSON are explicitly UTF-8 and a Chinese path does not leak the instance token;
- verify PyInstaller and both KataGo executables from a Unicode/spaced extraction directory.

No case-sensitive filename distinction should be relied upon. The proposed layout uses stable lowercase runtime directory names and explicit paths.

## 18. Windows native dependencies

Dependency policy by category:

| Component | Bundle? | Policy |
|---|---|---|
| Flutter release DLLs/data emitted by `flutter build windows` | Yes | Copy exactly as Flutter's install bundle produces; validate with a clean extraction |
| PyInstaller Python DLL and collected extension DLLs | Yes | Built/collected on Windows; inspect PE dependencies and licenses |
| Official KataGo v1.16.4 `katago.exe` variants | Yes | Preserve release identity/hash and KataGo notices |
| KataGo-adjacent DLLs present in the official ZIP (if any) | Only after dependency/license inventory | Keep beside the matching engine; do not mix variants blindly |
| OpenCL ICD/vendor driver | No | Expected from the installed GPU driver; fallback to Eigen when unavailable/broken |
| CUDA/cuDNN/TensorRT | No for recommended V1 | Not used by the general package |
| Microsoft VC runtime | Conditional | Determine from actual PE import tables; use supported redistribution strategy in section 19 |
| GPU driver | No | End-user machine responsibility; document minimum behavior and fallback |

If official release contents are insufficient, do not copy arbitrary DLLs from a developer machine. Use `dumpbin /dependents` or a maintained PE dependency inspector on the final Windows staging tree, classify system vs redistributable dependencies, retain license notices, and validate on a clean VM with no development tools.

## 19. Visual C++ runtime

The eventual package may contain three independently built PE families: Flutter Runner/engine, PyInstaller/Python extensions, and KataGo. Their VC/UCRT dependencies must be inspected from the **actual Windows artifacts**; macOS cannot answer this conclusively.

Recommended strategy:

1. Build with a supported Visual Studio toolchain.
2. Inventory imported runtime DLLs for every EXE/DLL.
3. Prefer Microsoft's current supported x64 Visual C++ Redistributable for normal installer-based deployment.
4. For the first no-installer private ZIP, use app-local runtime DLLs only when Microsoft's redistribution license permits it and clean-VM testing proves the complete set. Do not assume every school PC already has the runtime.
5. Do not download DLLs from unofficial sites or copy them opportunistically from `System32`/a developer machine.

Microsoft states that the installed redistributable version must be at least as recent as the MSVC build tools used. See [Latest supported Visual C++ Redistributable](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist?view=msvc-170) and [Redistributing Visual C++ files](https://learn.microsoft.com/en-us/cpp/windows/redistributing-visual-cpp-files?view=msvc-170).

This remains a Phase 7C empirical decision. A no-Python/no-SDK promise is achievable; a no-VC-runtime-installer promise is conditional on verified app-local redistribution or system availability.

## 20. Unsigned/private build behavior

The first Windows build is expected to be unsigned. A school evaluator may see:

- Microsoft Defender scanning or quarantining an unfamiliar PyInstaller executable;
- SmartScreen “Windows protected your PC” / unknown publisher warnings after download;
- browser “uncommon download” warnings;
- institutional policy that removes or blocks the “Run anyway” option.

Self-signing does not create public reputation. For a private build, ship SHA-256 checksums, a manifest, source/reproducibility notes, exact extraction/run instructions, and a contact path for false positives. Build on a clean controlled machine and scan the archive before delivery. If school policy blocks unsigned executables, Authenticode signing becomes a release prerequisite rather than a runtime bug. Phase 7A does not sign anything.

## 21. Icon strategy

Reuse `packaging/macos/assets/logosgo_icon_master.png` as the accepted elderly-dog artwork. Although the filename ends in `.png`, the current file is a 2048×2048 JPEG image; conversion tooling must decode by content and must not redesign or crop the artwork unexpectedly.

Generate a Windows multi-resolution `.ico` containing at least 16, 20/24, 32, 40/48, 64, 128, and 256 pixel representations with alpha where the accepted artwork supports it. Replace `windows/runner/resources/app_icon.ico` and keep `IDI_APP_ICON` in `Runner.rc`. Also update product/file metadata to LogosGo V1.0.0. Verify Explorer small/large icon, title bar, taskbar, Alt-Tab, and high-DPI rendering on 100% and 200% scale.

No new logo or Windows-specific brand is proposed.

## 22. Cross-platform source structure

Keep one source tree:

```text
go_project/
├── flutter_application_1/
│   ├── lib/                       # shared UI/state/networking
│   ├── test/                      # shared Flutter tests
│   ├── macos/Runner/              # macOS lifecycle implementation
│   └── windows/runner/            # Windows lifecycle implementation
├── server.py                      # shared API/analysis scheduling
├── runtime_paths.py               # shared API + small OS path branches
├── backend_startup.py             # shared startup contract + OS watcher branch
├── analysis_*.py, logos_engine.py,
│   explanation_*.py, review_*.py,
│   sgf_utils.py                   # shared analytical behavior
├── packaging/
│   ├── macos/                     # frozen macOS pipeline
│   └── windows/
│       ├── README.md
│       ├── backend.spec
│       ├── requirements-*.txt
│       ├── build_backend.ps1
│       ├── stage_runtime.ps1
│       ├── build_app.ps1
│       ├── package_release.ps1
│       └── assets/                # generated .ico or generation recipe
└── release/v1.0.0/                # platform-distinct archives/manifests
```

Do not duplicate analytical Python or Dart sources under `packaging/windows`. Windows scripts stage immutable copies and generate a platform manifest. Platform native code implements one common contract: `host`, `port`, `instanceToken`, readiness, and owned shutdown.

## 23. Windows build environment

Build-time requirements:

- Windows 11 x64 build machine or clean VM;
- Flutter SDK version matching the accepted project line (Phase 6 used Flutter 3.38.x; pin the exact Windows build commit/version in the manifest);
- Visual Studio 2022 with **Desktop development with C++**, Windows SDK, CMake/MSBuild tooling as required by Flutter;
- Git;
- Windows x64 Python 3.14.x compatible with the pinned wheels;
- PyInstaller 6.22.3 and pinned Windows-compatible backend requirements;
- official KataGo v1.16.4 Windows x64 OpenCL and Eigen artifacts;
- frozen model/config/corpus inputs and the accepted icon master;
- PE dependency inspection, checksum, archive, antivirus, and test tools;
- current GPU drivers on the hardware used to validate OpenCL.

End-user runtime requirements:

- Windows 11 x64;
- enough disk/RAM for the Flutter app, ~259 MiB model, backend, and two small engines;
- an OpenCL-capable working graphics driver for accelerated analysis **or** an x64 CPU for Eigen fallback;
- any VC runtime components proven necessary and either app-local in the permitted package or already installed;
- no Python, venv, Flutter SDK, Git, Visual Studio, Homebrew, CUDA, or manual Flask/KataGo startup.

The Flutter setup requirements are documented in [Flutter's Windows development guide](https://docs.flutter.dev/platform-integration/windows/setup). KataGo should use official binaries first; source compilation requirements are documented in its [v1.16.4 compiling guide](https://github.com/lightvector/KataGo/blob/v1.16.4/Compiling.md).

## 24. macOS-vs-Windows build responsibilities

Can the final Windows application be built from the current Mac? **No.** Flutter Windows release generation and PyInstaller Windows freezing are native-platform builds; PyInstaller is not a cross-compiler, and Windows Runner/PE/DLL/runtime behavior requires Windows.

| Work | macOS | Windows |
|---|---:|---:|
| audit/design and shared-source review | Yes | Optional |
| shared Python/Dart implementation and platform-neutral tests | Yes | Also rerun |
| icon source preparation and manifest schema | Yes | Final `.ico` validation |
| Windows Runner compilation | No | Required |
| `flutter build windows --release` | No supported production path | Required |
| Windows PyInstaller backend | No | Required |
| official Windows KataGo staging/PE dependency check | Can inspect metadata | Required for acceptance |
| OpenCL/Eigen runtime probe | No meaningful proof | Required on real/VM Windows hardware |
| SmartScreen/Defender/Unicode/lifecycle/E2E | No | Required |
| final Windows ZIP and release hashes | No | Required |

The Mac remains authoritative for the already frozen macOS archive and may prepare shared patches, but it cannot certify Windows release readiness.

## 25. Available Windows build infrastructure

Present in the repository:

- a standard Flutter `windows/` target with CMake, Win32 Runner, manifest, resource script, and default icon;
- Unicode compile definitions and a `wWinMain` entry point;
- Flutter's normal install-bundle rules for the executable, engine DLL, data, plugins, and native assets;
- shared Dart and Python code suitable for reuse.

Not present:

- Windows implementation of `logosgo/backend`;
- Windows backend/KataGo lifecycle controller;
- Windows PyInstaller spec or packaging scripts;
- Windows runtime layout/manifest/dependency validation;
- LogosGo product metadata/icon in the Windows Runner;
- Windows-specific tests/build artifacts;
- `.github` or other Windows CI workflow;
- evidence of an attached Windows host/VM or actual Windows build.

A future `windows-latest` CI job could perform compile/static/unit checks, but hosted CI usually cannot validate school GPU/OpenCL behavior, SmartScreen, or full long analysis. It supplements, not replaces, a real Windows x64 acceptance machine. No CI is created in Phase 7A.

## 26. Future test matrix

Every acceptance run should record Windows build, CPU, RAM, GPU, driver, selected KataGo backend/version/hash, model/config hashes, and cold/warm startup timing.

| ID | Required test | Acceptance condition |
|---|---|---|
| A | Startup | Extracted `LogosGo.exe` opens without console, Python, SDK, repo, or venv |
| B | Backend readiness | Dynamic loopback port and authenticated `/health` identity succeed |
| C | SGF import | Windows picker loads a real SGF; original hash unchanged |
| D | Whole-game analysis | Completes representative game at frozen 100 visits/PV8 |
| E | Black commentary | Objective data and explanation preserve BLACK perspective |
| F | White commentary | White move/player perspective parity remains correct |
| G | Review | Whole-game Review selection/summary renders and navigates |
| H | Variation | Reliable PV link opens correct base position and sequence |
| I | Trial | Trial moves remain temporary and restore cleanly |
| J | Position judgment | Foreground 500-visit request preempts/resumes background safely |
| K | Ownership | 361 ownership/stdev values render with captures/score correctly |
| L | Cancel/retry | Cancel, stale-request protection, and a fresh retry all work |
| M | Normal shutdown | Runner, backend, both possible KataGo children, port, handles exit |
| N | Shutdown during analysis | Graceful timeout then Job Object fallback leaves no process |
| O | Abnormal Runner death | Forced Runner termination kills backend/KataGo tree |
| P | Unicode path | Full launch/import under `C:\Users\測試\...` passes |
| Q | Spaced path | Full launch/import under `C:\Users\Test User\...` passes |
| R | Repo independence | Copied ZIP extracted outside repo and developer paths passes |
| S | No Python/venv | Clean machine/VM without Python starts and analyzes |
| T | GPU/runtime identity | UI/log/manifest identifies OpenCL or Eigen actually selected |

Additional required matrix axes:

- OpenCL-capable NVIDIA or AMD machine;
- Intel integrated GPU if available;
- machine/VM where OpenCL deliberately fails or is absent, proving Eigen fallback;
- clean Windows 11 VM with no Visual Studio/Python;
- normal user account with no administrator elevation;
- cold OpenCL first run versus warm tuned run;
- 100%/200% display scaling and Chinese SGF metadata;
- package dependency/license/hash and Defender scan.

## 27. Hardware compatibility strategy

Comparison:

| Strategy | Complexity | Compatibility | Performance | Package size | School reliability |
|---|---:|---:|---:|---:|---:|
| A. CUDA-only | Medium/high | Low; NVIDIA + exact runtime | High on suitable hardware | High if runtimes bundled | Low |
| B. OpenCL-only | Low/medium | Medium/high but driver-sensitive | Good | Low | Medium |
| C. Separate downloadable variants | Medium operational burden | High if evaluator picks correctly | Backend-dependent | Smaller per ZIP | Medium; easy to pick wrong build |
| D. Eigen-only | Low | Highest CPU compatibility | Slow | Low | Functional but potentially poor UX |
| E. Runtime selection: OpenCL + Eigen fallback | Medium | Highest practical | Fast when possible, functional otherwise | Modest increase | **Highest** |

Recommendation: **E**, implemented with official exact-v1.16.4 OpenCL and non-AVX2 Eigen binaries in one package. This avoids requiring the evaluator to understand GPU APIs and does not depend on internet access. Eigen AVX2 can be considered later only with reliable CPU-feature detection; CUDA/TensorRT can be an optional performance edition later, not the Windows V1 baseline.

The selected backend and reason for fallback must be visible in logs/diagnostics. OpenCL failure must not silently look like an infinite launch. Performance acceptance should distinguish “functionally compatible fallback” from “meets normal interactive ETA”; Eigen may require a documented slower-performance limitation or a calibrated hardware profile.

## 28. Risk register

| Priority | Risk | Evidence/impact | Mitigation/gate |
|---|---|---|---|
| P1 | Windows Runner lacks backend MethodChannel/lifecycle | Current app cannot obtain endpoint or launch backend | Implement/test Windows controller in 7B before any release claim |
| P1 | Unknown school GPU/OpenCL driver | OpenCL may tune slowly, fail, or crash on some Intel/AMD drivers | Ship/prove non-AVX2 Eigen fallback; record selected backend |
| P1 | Abnormal process-tree cleanup | POSIX group/watchdog does not work on Windows; orphan backend/KataGo possible | Job Object kill-on-close plus shutdown-under-load/death tests |
| P1 | No real Windows build/host evidence | Flutter/PyInstaller/PE behavior cannot be certified on macOS | Native Windows 11 x64 build and clean-machine E2E are release gates |
| P1 | Missing VC/runtime DLL on clean machine | App may start on developer PC only | PE import inventory and clean VM test; supported redist/app-local policy |
| P2 | macOS-only writable paths | Writes target nonsensical paths; tuning/logs fail | `%LOCALAPPDATA%`/`%TEMP%` platform branch with tests |
| P2 | 16×4 / batch/cache sizing on weak Windows hardware | OOM, system contention, bad ETA | Backend/device calibration; keep visits/semantics frozen |
| P2 | OpenCL first-run tuning appears hung | Evaluator may force-close during minutes-long first run | Progress/log messaging, bounded health/probe logic, warm/cold tests |
| P2 | SmartScreen/Defender/PyInstaller false positive | Private ZIP may be warned, blocked, or quarantined | Checksums, controlled build, Defender scan/submission, signing if policy demands |
| P2 | Unicode/spaced paths | Native launch/argument bugs can block school usernames | Wide Win32 APIs and full E2E fixtures |
| P2 | Dependency/model redistribution provenance | Technical bundle may lack complete notices | Produce license/NOTICE inventory before distribution |
| P2 | PyInstaller Windows hidden DLL/import behavior | Runtime-only crashes despite build success | Native onedir build, dependency scan, clean VM regression |
| P2 | Flutter/file-picker Windows behavior untested | Compile success does not prove import flow | Real picker/hash tests in 7C/7D |
| P2 | Backend graceful shutdown on Windows undefined | `TerminateProcess` can skip cleanup/log flushing | Authenticated shutdown mechanism + bounded Job Object fallback |
| P2 | Package size | Model already dominates (~259 MiB); ZIP remains large | One shared model/config; avoid bundled CUDA stack/duplicate assets |
| P3 | Placeholder Windows product metadata/icon | Poor identity but not analytical failure | Update Runner resource/version/icon in 7B |
| P3 | Legacy GBK comment does not match `latin1` fallback | Some Chinese metadata may decode incorrectly | Add fixture; defer product-level decoder change unless release requires it |
| P3 | No Windows CI | Slower repeatability | Add compile/unit CI later; retain physical-GPU manual gate |

## 29. Proposed Phase 7B/7C/7D sequence

### Phase 7B — Cross-platform source preparation

- add Windows-aware writable paths and `.exe` discovery without changing analytical modules;
- replace/branch POSIX parent-liveness and shutdown behavior;
- implement Windows Runner lifecycle, MethodChannel, dynamic port/token, health identity, Job Object, and graceful/forced stop;
- rename Windows product metadata to LogosGo V1.0.0 and generate the accepted icon;
- add platform-neutral and Windows-native unit/contract tests;
- keep macOS Runner and frozen archive untouched;
- do not claim final runtime success yet.

### Phase 7C — Native Windows build and runtime assembly

- establish/pin Windows 11 x64 Flutter, Visual Studio, Python, and PyInstaller environment;
- build the Windows PyInstaller onedir backend;
- obtain and hash official v1.16.4 OpenCL and non-AVX2 Eigen assets;
- inventory DLLs/licenses and resolve VC runtime policy;
- implement and validate OpenCL probe/Eigen fallback;
- stage one self-contained Windows directory and run startup/backend/KataGo smoke tests;
- calibrate hardware-only concurrency profiles if necessary, with analytical settings frozen and explicit approval.

### Phase 7D — Self-contained Windows E2E release candidate

- build `flutter build windows --release` and assemble the runtime beside it;
- execute the complete A–T matrix on clean Windows paths/hardware;
- validate cold/warm OpenCL and forced Eigen fallback;
- validate cancellation, foreground preemption, normal/abnormal shutdown, repo independence, and no installed Python;
- package a private ZIP with manifest, hashes, licenses, diagnostics instructions, and known limitations;
- return a Windows release gate, without changing the accepted macOS artifact.

### Phase 7E — Windows V1 release freeze

- freeze exact source state, toolchain, selected runtime assets, settings/profile, hashes, E2E evidence, release notes, and archive;
- sign only if a certificate/policy is available and required;
- preserve platform-qualified artifacts side by side with macOS V1.0.0.

No Phase 7B/7C/7D/7E work was started in this audit.

## 30. macOS release hash verification

Protected artifact:

`release/v1.0.0/LogosGo-v1.0.0-macOS-arm64.zip`

Required/observed SHA-256 before writing this report:

`28892525cf3373d82ecddb445ae059fb177d1e39a9f41ca923e101bb4a334509`

The same hash is recorded in `release/v1.0.0/SHA256SUMS.txt` and the Phase 6D freeze report. A final post-report hash check is required below; any mismatch is a release blocker.

## 31. Frozen analytical behavior was untouched

Phase 7A adds only this audit document. It does not modify or run a Windows build, start KataGo, rebuild either platform, change the accepted archive, or alter production Flutter/Python/config/model/corpus/SGF files.

Frozen values remain:

- whole-game `maxVisits=100`, `16×4`, `analysisPVLen=8`, ownership off;
- position judgment `maxVisits=500`, `1×16`, ownership and ownership stdev on;
- `reportAnalysisWinratesAs=BLACK`;
- model SHA-256 `93abbeea4b4b38a6b5fda83e58927b588e2ca195ef9816b831db9d629c029efa`;
- config SHA-256 `194839bbac3ffef48830e79fa05167a93b3f1b8b602a6b184b954fd72517e796`;
- KataGo protocol, commentary, classifier, directional explanation, Review Selection/Summary, thresholds, ownership, trial, variation, and UI behavior unchanged.

Final verification should compare Git status against the pre-audit accepted dirty working tree and show only this new Phase 7A document as the audit's repository change.

Windows V1 is feasible with the current shared architecture, but it requires a native Windows 11 x64 build environment, a Windows Runner/process-lifecycle implementation, clean-machine DLL/runtime validation, and the accepted OpenCL-primary/non-AVX2-Eigen-fallback hardware policy. No Windows runtime or E2E success can be claimed until those constraints are validated on Windows.

**B. READY FOR WINDOWS IMPLEMENTATION WITH CONSTRAINTS**
