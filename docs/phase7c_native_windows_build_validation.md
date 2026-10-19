# Phase 7C — Native Windows Build & Runtime Validation

Date: 2026-10-14  
Required target: Windows 11 x64  
Actual execution host: macOS 26.5.2 arm64  
Validation status: blocked before native Windows execution

This report uses three explicit evidence labels:

- **EXECUTED:** directly observed during Phase 7C.
- **INHERITED:** evidence from the accepted Phase 7B report; not reclassified as Windows validation.
- **NOT EXECUTED:** requires a real Windows 11 x64 environment and was not attempted on macOS.

## 1. Executive summary

Phase 7C could not begin native Windows build or runtime validation because the available host is an Apple M4 MacBook Air running macOS arm64, not Windows 11 x64. No usable Windows VM or remote Windows host was available. The installed VMware Fusion application contained only its internal template `.vmx` files; no user Windows VM was discovered, and `vmrun list` could not start.

Following the non-negotiable instruction not to claim Windows validation from macOS, no PyInstaller Windows build, Flutter Windows build, Windows KataGo execution, mocked Windows E2E, or cross-compilation was attempted. No product code or frozen analysis behavior was changed during Phase 7C.

**EXECUTED:** host/platform audit, repository status capture, frozen macOS archive verification, and blocker documentation.  
**NOT EXECUTED:** every Windows-native build, runtime, OpenCL, fallback, Runner, E2E, lifecycle, and clean-machine test.

## 2. Phase 7B starting state

**INHERITED:** Phase 7B ended with `B. READY WITH OPEN WINDOWS RISKS` and prepared:

- cross-platform runtime path and process abstractions;
- Windows PyInstaller spec and PowerShell build script;
- planned OpenCL-first/non-AVX2-Eigen-fallback layout;
- Windows writable-path and dependency policies;
- a detailed native Windows Runner contract;
- macOS regression evidence: 271 Python tests, 59 Flutter tests, 5 Runner tests, real backend/analysis/ownership/shutdown smoke, and no orphan process.

Phase 7B explicitly left the default Windows Runner lifecycle integration, native PyInstaller output, Windows DLL closure, Job Object behavior, OpenCL/Eigen execution, and clean-machine E2E unimplemented or unvalidated.

## 3. Windows environment

**NOT EXECUTED:** no Windows environment was available to audit.

The actual host was verified as:

- OS: macOS 26.5.2, build 25F84
- kernel/architecture: Darwin arm64
- hardware: MacBook Air, Apple M4, 10 CPU cores, 16 GB RAM
- GPU: integrated Apple M4, 8 GPU cores, Metal supported

No Windows edition/version/build, x64 CPU environment, Windows GPU driver, or Windows OpenCL platform could be recorded. VMware Fusion was present, but no user `.vmx` existed outside the application bundle templates. This host therefore cannot satisfy the required Windows 11 x64 evidence boundary.

## 4. Toolchain

**NOT EXECUTED:** the required native Windows toolchain audit could not be performed. There was no Windows PowerShell, Windows x64 Python, PyInstaller-for-Windows environment, Visual Studio/MSVC, Windows SDK, or Windows Flutter desktop toolchain.

macOS installations of CMake, Flutter, and Python were detected, but they are not substitutes for the required Windows versions and were not reported as Windows toolchain evidence. `flutter doctor -v` was not run and relabeled as a Windows audit because the host platform was already definitively invalid for Phase 7C.

## 5. Source baseline

**EXECUTED:** `git status --short` was captured before any Phase 7C write. The repository already contained the accepted dirty working tree from Phases 1–7B. No reset, restore, checkout, clean, stash, or broad refactor was performed.

**NOT EXECUTED:** Python, Flutter, and runtime/path tests were not run on Windows. The Phase 7B macOS counts remain inherited evidence only and do not establish a Windows baseline.

No Windows-specific failure could be classified as product bug, portability bug, test assumption, or environment problem because the native test process never started. The absence of the mandated platform is an environment blocker.

## 6. Runtime path validation

**INHERITED/DESIGN ONLY:** Phase 7B source defines Windows executable names, `%LOCALAPPDATA%\LogosGo`, `%TEMP%\LogosGo`, packaged `runtime/` discovery, and deterministic OpenCL/Eigen candidates. Injected-platform tests passed on macOS.

**NOT EXECUTED:** no real Windows filesystem validated `%LOCALAPPDATA%`, Unicode paths, spaces, `.exe` discovery, DLL lookup, writable logs, temporary state, or repository-independent resource resolution. No claim is made that Win32 path handling works until Phase 7C is resumed on Windows.

## 7. PyInstaller backend build

**NOT EXECUTED:** `packaging/windows/build_backend.ps1` and `packaging/windows/backend.spec` were not run. PyInstaller is not a cross-compiler, and producing a macOS-built artifact would violate the task.

Consequently there is no `logosgo_backend.exe`, PE architecture result, output-size measurement, bundled dependency inventory, startup-time measurement, missing-DLL result, or proof that the backend runs without installed Python.

## 8. KataGo OpenCL runtime

**NOT EXECUTED:** no official KataGo v1.16.4 Windows OpenCL executable or DLL set was staged or launched. No Windows OpenCL device, driver, model initialization, analysis query, result, diagnostic log, or shutdown was observed.

The OpenCL-primary policy remains a Phase 7B design, not runtime evidence.

## 9. Eigen fallback

**NOT EXECUTED:** no official v1.16.4 Windows non-AVX2 Eigen runtime was staged or launched. OpenCL failure detection, recorded diagnostics, deterministic Eigen selection, real fallback analysis, UI continuity, and clean fallback shutdown remain unvalidated.

No broad exception swallowing or artificial fallback simulation was added.

## 10. Backend endpoint/token validation

**INHERITED:** the loopback/dynamic-port/instance-token architecture and authenticated `/health` and `/shutdown` behavior were validated on macOS in Phase 7B.

**NOT EXECUTED:** no Windows Runner launched the backend, obtained its dynamic endpoint, verified its token/identity, or proved the absence of a fixed-port-5001 packaged dependency. Windows binding, firewall interaction, and endpoint propagation remain unknown.

## 11. Windows Runner

**INHERITED/DESIGN ONLY:** the repository contains Flutter Windows Runner sources and a documented contract for `CreateProcessW`, a Job Object, dynamic port/token handshake, log redirection, MethodChannel `logosgo/backend`, authenticated health, graceful shutdown, and forced descendant cleanup.

**NOT EXECUTED:** that lifecycle integration was not implemented or built during this blocked Phase 7C run. The Windows Runner remains a release-blocking implementation task; no shell-based substitute was introduced.

## 12. First native staging build

**NOT EXECUTED:** no native Windows staging directory or `LogosGo.exe` was produced. There is no evidence yet for automatic backend startup, model/config resolution, user log placement, or operation outside a developer environment.

No Windows release archive or installer was created.

## 13. SGF E2E

**NOT EXECUTED:** no real SGF was imported into a Windows build. Board reconstruction, progressive analysis, winrate display, important/review positions, commentary, review UI, and whole-game summary were not tested on Windows.

## 14. Whole-game analysis

**NOT EXECUTED:** no Windows whole-game analysis query was run, so runtime diagnostics cannot confirm the frozen values on Windows.

Current source remains frozen at:

- `maxVisits = 100`
- `numAnalysisThreads = 16`
- `numSearchThreadsPerAnalysisThread = 4`
- `analysisPVLen = 8`
- `includeOwnership = false`

These are source observations, not Windows execution evidence.

## 15. Position judgment

**NOT EXECUTED:** foreground preemption/yield/restart behavior was not exercised on Windows. There is no Windows proof that completed background positions are preserved, only remaining positions resume, or simultaneous KataGo processes are avoided.

Current source remains frozen at 500 visits, 1×16, ownership enabled, and ownership stdev enabled. Again, this is a source observation only.

## 16. Ownership

**NOT EXECUTED:** Windows ownership data return, territory rendering, black/white values, dead-stone markers, overlay clearing, and position-panel lifecycle were not tested.

## 17. PV/trial

**NOT EXECUTED:** Windows recommended variation availability, trial-mode reuse, relative numbering, manual continuation, state restoration, SGF immutability, and no-PV hiding behavior were not tested.

## 18. Black/white parity

**INHERITED:** accepted source semantics remain canonical black perspective, with `whiteWinrate = 1 - blackWinrate` and `whiteScoreLead = -blackScoreLead`.

**NOT EXECUTED:** parity tests and representative black/white positions were not run on Windows. No perspective code was modified to mask this missing evidence.

## 19. Lifecycle/orphan matrix

The release-blocking Windows lifecycle matrix could not run:

| Case | Windows result | Reason |
|---|---|---|
| A. Normal idle exit | NOT EXECUTED | No Windows staging app |
| B. Exit after completed analysis | NOT EXECUTED | No Windows staging app/KataGo |
| C. Exit during whole-game analysis | NOT EXECUTED | No Windows staging app/KataGo |
| D. Exit during position judgment | NOT EXECUTED | No Windows staging app/KataGo |
| E. Cancel whole-game analysis | NOT EXECUTED | No Windows staging app/KataGo |
| F. OpenCL → Eigen fallback then exit | NOT EXECUTED | No Windows runtimes/OpenCL host |
| G. Backend startup failure | NOT EXECUTED | No Windows backend/Runner |
| H. KataGo startup failure | NOT EXECUTED | No Windows KataGo/Runner |
| I. Abnormal Runner termination | NOT EXECUTED | No Windows Runner/Job Object |

No Windows process inventory for `LogosGo.exe`, `logosgo_backend.exe`, or `katago.exe` exists. Phase 7B macOS orphan checks do not satisfy this matrix.

## 20. Repository-independent test

**NOT EXECUTED:** no staging build was copied to a Windows path containing spaces or Unicode. Startup, SGF import, analysis, position judgment, logging, and shutdown outside the repository remain unvalidated.

## 21. Dependency audit

**INHERITED/PLANNED:** the intended package bundles the PyInstaller backend, Flutter DLLs/plugins, both official KataGo distributions with their shipped DLLs, the frozen model/config/corpus, licenses, and a manifest. End users should not need Python, Flutter, Git, the repository, or a virtualenv.

**NOT EXECUTED:** PE imports, app-local DLL closure, Microsoft Visual C++ runtime policy, OpenCL driver dependency, GPU driver behavior, and clean-machine operation were not audited on Windows. The distinction among bundled dependencies, normal OS/driver dependencies, and developer-only dependencies therefore remains provisional.

## 22. Regression results

**NOT EXECUTED:** no Windows Python, Flutter, Runner, `py_compile`, PowerShell, or E2E regression suite was run.

**EXECUTED ON MACOS ONLY:** the repository diff was left untouched except for this report, and the frozen archive hash was recomputed. No Phase 7C compatibility fix was attempted because there was no native failure evidence to justify one.

The Phase 7B regression results remain available in `docs/phase7b_windows_runtime_preparation.md`; they must not be presented as Phase 7C Windows results.

## 23. macOS freeze verification

The frozen archive was present and verified before Phase 7C documentation:

```text
release/v1.0.0/LogosGo-v1.0.0-macOS-arm64.zip
SHA-256 28892525cf3373d82ecddb445ae059fb177d1e39a9f41ca923e101bb4a334509
```

It matches the required value. Phase 7C did not rebuild, overwrite, or launch the frozen archive.

## 24. Changes made during Phase 7C

Only this report was added:

- `docs/phase7c_native_windows_build_validation.md`

No production Python, Flutter, Runner, packaging, model, config, SGF, branding, analysis, explanation, review, perspective, or frozen release file was changed.

## 25. Remaining Windows risks

- Windows Runner lifecycle integration is not implemented or compiled.
- No native `logosgo_backend.exe` exists.
- OpenCL hardware/driver/model execution is untested.
- The non-AVX2 Eigen fallback is untested.
- Job Object descendant cleanup and abnormal-exit behavior are untested.
- Windows path, Unicode, spaces, `%LOCALAPPDATA%`, TEMP, and repository independence are untested.
- PE/DLL closure and Visual C++ runtime requirements are unknown.
- Firewall, Defender/antivirus, SmartScreen, school-device policy, sleep/resume, and repeated-launch behavior are unknown.
- All Windows product E2E behavior remains unvalidated.

## 26. Blockers for self-contained Windows V1

1. Provide a native Windows 11 x64 machine or remote build/test host with administrative access appropriate for the agreed toolchain.
2. Install/verify Flutter Windows desktop dependencies, Visual Studio 2022 C++ workload, Windows SDK, Windows x64 Python, PyInstaller, CMake, Git, and PowerShell.
3. Provide and inventory official KataGo v1.16.4 Windows OpenCL and non-AVX2 Eigen archives and their licenses/hashes.
4. Implement the Phase 7B Windows Runner contract, including `CreateProcessW`, Job Object, handshake MethodChannel, authenticated shutdown, logging, and fallback selection.
5. Build and validate the native backend and Flutter staging app.
6. Complete the full sections 3–19 test matrix on real Windows, including clean-machine/repository-independent execution.

Phase 7C should resume from environment audit on that host. The macOS repository must be transferred without discarding the accepted dirty working tree or frozen assets.

## 27. Evidence/log paths

Evidence created or consulted:

- Phase 7B report: `docs/phase7b_windows_runtime_preparation.md`
- Phase 7C blocker report: `docs/phase7c_native_windows_build_validation.md`
- Frozen macOS archive: `release/v1.0.0/LogosGo-v1.0.0-macOS-arm64.zip`
- Windows packaging inputs: `packaging/windows/`
- Windows Runner source: `flutter_application_1/windows/runner/`

Executed command evidence included `uname -a`, `sw_vers`, `uname -m`, `system_profiler` (non-identifying hardware fields only), `git status --short`, archive `shasum -a 256`, Windows-tool lookup, VMware `vmrun list`, and a search for user VM configuration files outside application-bundle templates.

There are no Windows build logs, KataGo logs, Runner logs, E2E screenshots, or process-matrix logs because no native Windows execution occurred.

## 28. Final gate

The mandatory native Windows 11 x64 environment was unavailable, so none of the release-defining Windows evidence exists. Phase 7B preparation remains intact, but Phase 7C validation has not begun and cannot receive a partial-validation gate.

C. WINDOWS RUNTIME NOT READY
