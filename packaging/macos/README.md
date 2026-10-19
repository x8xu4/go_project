# LogosGo V1.0.0 private macOS build

This directory contains the reproducible private-build pipeline for the
Apple Silicon/macOS 26 LogosGo app. The lower-level scripts remain independently
usable for validating the standalone backend and portable KataGo runtime.

## Build environment

Use Apple Silicon macOS 26+, Xcode command-line tools, Flutter 3.38.x, Python
3.14, and a KataGo v1.16.4 Metal executable. Create a dedicated build
environment if the repository development venv is not being used:

```bash
python3.14 -m venv /private/tmp/logosgo-packaging-venv
/private/tmp/logosgo-packaging-venv/bin/python -m pip install \
  -r packaging/macos/requirements-backend.txt \
  -r packaging/macos/requirements-build.txt
```

## Clean onedir build

The script deletes only its ignored `build/` and `dist/` directories before
every build. It defaults to `venv/bin/python`; override that interpreter for a
dedicated packaging environment:

```bash
PYTHON_EXECUTABLE=/private/tmp/logosgo-packaging-venv/bin/python \
  packaging/macos/build_backend.sh
```

Output:

```text
packaging/macos/dist/logosgo-backend/logosgo-backend
```

The entire `logosgo-backend/` onedir directory is one component and must stay
together.

## Standalone startup

Supply resources and KataGo explicitly. The runtime command invokes the frozen
binary directly; it does not invoke Python or activate a venv.

```bash
packaging/macos/dist/logosgo-backend/logosgo-backend \
  --port 53124 \
  --instance-token replace-with-runner-token \
  --resource-root /absolute/path/to/runtime-resources \
  --katago-executable /absolute/path/to/katago
```

The resource root must contain one of each supported path:

```text
model.bin.gz                 or model/model.bin.gz
analysis.cfg                 or config/analysis.cfg
logosgo_corpus_full.csv      or data/logosgo_corpus_full.csv
```

## Portable KataGo runtime staging

Phase 6B-3 copies the backend, KataGo, its recursively discovered non-system
libraries, and immutable runtime assets into one portable staging tree. Inputs
are deliberately explicit; the script never edits the source Homebrew files.

```bash
packaging/macos/build_native_runtime.sh \
  --katago /absolute/path/to/katago \
  --backend-dir /absolute/path/to/logosgo-backend \
  --model /absolute/path/to/model.bin.gz \
  --config /absolute/path/to/analysis.cfg \
  --corpus /absolute/path/to/logosgo_corpus_full.csv
```

Output:

```text
packaging/macos/dist/logosgo-runtime/
├── backend/
├── katago/katago
├── katago/lib/*.dylib
├── model/model.bin.gz
├── config/analysis.cfg
├── data/logosgo_corpus_full.csv
└── manifest/
```

The staged native binaries use relative Mach-O load paths and are ad-hoc
signed after rewriting. The build fails if a staged load command or text file
contains a developer-machine `/opt/homebrew`, `/usr/local`, or `/Users/...`
path.

## First self-contained private app

Build and validate the complete app with the KataGo executable used as the
source for portable native staging:

```bash
packaging/macos/build_app.sh --katago /absolute/path/to/katago
```

The pipeline builds the PyInstaller backend, recursively stages KataGo and its
libraries, generates the checked-in AppIcon representations from
`assets/logosgo_icon_master.png`, builds Flutter Release, embeds the immutable
runtime at `Contents/Resources/LogosGoRuntime`, signs nested Mach-O components
before the outer bundle, and validates architecture, load paths, identities,
permissions, and asset hashes.

Output:

```text
packaging/macos/dist/LogosGo.app
```

This private ad-hoc build is not notarized and is not a Mac App Store build.
It requires neither system Python nor Homebrew at runtime.

## Validation performed by the app build

`build_app.sh` fails unless the final bundle has the expected identity,
resources, executable permissions, arm64-only Mach-O files, matching
model/config/corpus hashes, no bundled Python source, no developer-machine
load paths, and a valid deepest-first ad-hoc signature. It also runs `plutil`
and strict/deep `codesign` verification. The output is a private build; the
script does not use Developer ID, notarize, create an installer, or publish.

Run the source regressions separately before freezing a release:

```bash
PYTHONDONTWRITEBYTECODE=1 ./venv/bin/python -m unittest -q
(cd flutter_application_1 && flutter test && flutter analyze)
xcodebuild -workspace flutter_application_1/macos/Runner.xcworkspace \
  -scheme Runner -configuration Debug \
  -derivedDataPath /private/tmp/logosgo-runner-tests test
```

## Private V1 archive

After `build_app.sh` succeeds and the release manifest exists, create the
macOS-safe private archive and checksum file with:

```bash
packaging/macos/package_release.sh
```

The script validates the accepted app again, creates the ZIP with macOS
`ditto --sequesterRsrc --keepParent`, checks ZIP integrity, and writes:

```text
release/v1.0.0/LogosGo-v1.0.0-macOS-arm64.zip
release/v1.0.0/SHA256SUMS.txt
```

For acceptance, extract the ZIP with `ditto -x -k` to a new directory outside
the repository, repeat structural/Mach-O/codesign checks, launch that extracted
copy through LaunchServices, perform a minimal UI smoke test, then verify no
Runner/backend/KataGo process remains after closing it.
