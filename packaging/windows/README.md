# LogosGo V1.0.0 native Windows build preparation

This directory contains source inputs for a future native Windows 11 x64
build. Phase 7B was prepared on macOS, so no Windows executable or runtime
validation is claimed here.

## Required native environment

- Windows 11 x64
- Flutter SDK matching the accepted V1 source line
- Visual Studio 2022 with **Desktop development with C++** and a Windows SDK
- Git
- Windows x64 Python 3.14
- the packages pinned in `requirements-backend.txt` and
  `requirements-build.txt`
- official KataGo v1.16.4 Windows x64 OpenCL and non-AVX2 Eigen archives
- current GPU driver for OpenCL testing

PyInstaller is not a cross-compiler. Do not run this pipeline on macOS and
label the output as Windows-compatible.

## Standalone backend

Create a dedicated Windows x64 virtual environment at any path outside the
runtime package, then run in PowerShell:

```powershell
py -3.14 -m venv .venv-packaging-windows
.\.venv-packaging-windows\Scripts\python.exe -m pip install `
  -r packaging\windows\requirements-backend.txt `
  -r packaging\windows\requirements-build.txt
packaging\windows\build_backend.ps1 `
  -PythonExecutable .\.venv-packaging-windows\Scripts\python.exe
```

Expected onedir output:

```text
packaging/windows/dist/logosgo_backend/
├── logosgo_backend.exe
└── _internal/...
```

The backend remains console-capable so stdout/stderr diagnostics can be
redirected by the owning Runner. The Runner should launch it with no visible
console window. The build intentionally excludes the model, config, corpus,
and KataGo; they are immutable runtime assets staged separately.

## Planned application layout

```text
LogosGo/
├── LogosGo.exe
├── flutter_windows.dll
├── data/...
└── runtime/
    ├── backend/logosgo_backend/...
    ├── katago/opencl/katago.exe
    ├── katago/eigen/katago.exe
    ├── model/model.bin.gz
    ├── config/analysis.cfg
    ├── data/logosgo_corpus_full.csv
    ├── licenses/...
    └── manifest/...
```

The Windows Runner must pass absolute `--resource-root` and
`--katago-executable` paths. It must never use the install directory as a
writable location.

## KataGo selection contract

The required order is official v1.16.4 OpenCL first, then official v1.16.4
non-AVX2 Eigen. Path discovery only establishes preference; it does not prove
OpenCL works. The native Runner must perform a bounded real initialization
probe with the frozen model/config in a writable directory, retain diagnostics,
and select Eigen after a definite OpenCL failure. Phase 7B does not download or
stage either Windows binary.

## Windows Runner contract for Phase 7C

The existing Flutter Windows Runner is still the default template. Native
implementation must:

1. use wide-character Win32 paths and `CreateProcessW`;
2. allocate `127.0.0.1:0` and retry a bounded launch race;
3. generate a random URL-safe token and place it in the child environment;
4. launch the selected backend/runtime with explicit absolute paths;
5. assign the backend to a Job Object with kill-on-close before it can spawn
   descendants;
6. redirect stdout/stderr to `%LOCALAPPDATA%\LogosGo\Logs`;
7. poll authenticated `/health` and verify service/API/instance identity;
8. implement MethodChannel `logosgo/backend`, method
   `getBackendConfiguration`;
9. POST authenticated `/shutdown`, wait a bounded interval, then terminate the
   Job Object if required; and
10. prove normal close and abnormal Runner death leave no backend/KataGo child.

The shared Flutter endpoint map remains `{host, port, instanceToken}`. Do not
fall back to port 5001 in a packaged Release build.

## Native dependency validation

Keep all DLLs from each official KataGo archive beside its matching executable
until a Windows dependency and license inventory proves otherwise. Do not copy
DLLs from a developer machine or bundle GPU drivers/OpenCL ICDs. Inspect all
final EXE/DLL imports, decide the Microsoft Visual C++ runtime strategy, and
validate on a clean Windows 11 x64 VM without Python, Flutter, or Visual Studio.
