# Phase 6D — LogosGo V1.0.0 Release Freeze

Freeze date: 2026-10-13

## 1. Release identity

- Product: LogosGo
- Release: V1.0.0
- Build: 1
- Channel: private macOS release
- Accepted source base: `ad270fccb4f881897e8a8d8ec7924601b42f10b2`
- Deliverable: self-contained `LogosGo.app` archived as a macOS-safe ZIP

This is the first specifically identified, reproducible, archived, checksummed, documented, and regression-tested LogosGo release. It preserves the accepted Phase 1–6D working tree without rewriting or discarding earlier work.

## 2. Files changed

Phase 6D changed or added only release-preparation material:

- `README.md`: V1 user guide, system requirements, usage, safety/limitations, and exit behavior.
- `.gitignore`: ignores runtime logs, generated packaging trees, and local release ZIPs while retaining packaging source, manifests, checksums, and release notes.
- `packaging/macos/README.md`: reproducible backend, native runtime, app assembly, validation, regression, and archive instructions.
- `packaging/macos/package_release.sh`: validates the accepted app, creates the private ZIP, verifies ZIP integrity, and writes checksums.
- `release/v1.0.0/RELEASE_NOTES.md`: user-facing V1 release notes.
- `release/v1.0.0/logosgo-v1.0.0-manifest.json`: machine-readable release identity, runtime components, frozen settings, tests, and limitations.
- `release/v1.0.0/SHA256SUMS.txt`: artifact and immutable-runtime hashes.
- `release/v1.0.0/LogosGo-v1.0.0-macOS-arm64.zip`: private executable deliverable; intentionally ignored by Git because of its size.
- `docs/school_submission_mapping.md`: current school-deliverable status and source-delivery recommendation.
- `docs/phase6d_v1_release_freeze.md`: this freeze record.

No production feature, analysis, commentary, Flutter behavior, or KataGo setting was changed in Phase 6D.

## 3. Version metadata

- `flutter_application_1/pubspec.yaml`: `version: 1.0.0+1`
- `CFBundleShortVersionString`: `1.0.0`
- `CFBundleVersion`: `1`
- `PRODUCT_NAME`: `LogosGo`
- `PRODUCT_BUNDLE_IDENTIFIER`: `com.logosgo.desktop`
- `MACOSX_DEPLOYMENT_TARGET` / `LSMinimumSystemVersion`: `26.0`

The source metadata, built bundle metadata, release manifest, archive name, and release notes all identify the same V1.0.0 build.

## 4. Final app identity

Accepted app:

`packaging/macos/dist/LogosGo.app`

- Bundle identifier: `com.logosgo.desktop`
- Version/build: `1.0.0 (1)`
- Uncompressed size: `355616 KiB` (about `347 MiB`)
- Architecture: arm64 only
- Backend: bundled PyInstaller onedir runtime
- KataGo: bundled KataGo `v1.16.4`, Metal backend
- Signature: private ad-hoc signature; `codesign --verify --deep --strict` passes
- Runtime: no system Python or Homebrew dependency is required

The final and round-trip-extracted app each contain 130 arm64 Mach-O files and 13 symbolic links. The model hash is identical in source, accepted app, and extracted app.

## 5. Supported platform

- Apple Silicon Mac only
- macOS 26.0 or later
- Private distribution only

Intel Macs, older macOS releases, Windows, public App Store distribution, Developer ID signing, and notarization are outside V1.0.0 scope.

## 6. User README status

`README.md` is complete for V1 private delivery. It explains requirements, first launch/Gatekeeper expectations, SGF import, whole-game analysis, navigation, whole-game review, reliable recommendation variations, trial mode, position judgment, ask/why commentary, evidence limitations, and normal shutdown.

## 7. Technical build documentation status

`packaging/macos/README.md` documents:

1. Apple Silicon/macOS 26 build requirements;
2. standalone PyInstaller backend creation;
3. portable KataGo/native-library staging;
4. Flutter Release app assembly;
5. embedded runtime layout and signing;
6. static and regression validation;
7. accepted app output location; and
8. private V1 archive and round-trip acceptance procedure.

The build scripts use explicit inputs, keep generated output under ignored packaging directories, and reject unexpected architecture, signatures, assets, or developer-machine load paths.

## 8. Release archive path

`release/v1.0.0/LogosGo-v1.0.0-macOS-arm64.zip`

The archive was created with macOS `ditto -c -k --sequesterRsrc --keepParent` so bundle metadata and symbolic links survive round trip. ZIP integrity passes `unzip -tq`.

## 9. Archive size

- Exact size: `312464516` bytes
- Display size: `305 MiB`
- Contained app size after extraction: `355616 KiB` (about `347 MiB`)

## 10. Archive round-trip result

PASS.

The archive was extracted to `/private/tmp/logosgo-v1-roundtrip.HCe8fd/LogosGo.app`, outside the repository. Verification covered:

- expected `.app` structure and executable permissions;
- version `1.0.0`, build `1`, bundle identifier `com.logosgo.desktop`, minimum macOS `26.0`;
- strict/deep code-signature verification;
- 130 arm64-only Mach-O files;
- absence of `/opt/homebrew`, `/usr/local`, or developer `/Users/...` Mach-O load paths;
- 13 symbolic links before and after extraction;
- bundled model hash equality;
- LaunchServices startup to the normal LogosGo board UI;
- indirect backend readiness through successful normal UI startup;
- successful import of the real 59-move `game-3.sgf`;
- cancellation of the automatically started smoke analysis; and
- clean close with no remaining Runner, `logosgo-backend`, KataGo, or test Flask process.

The smoke test intentionally did not repeat a long whole-game analysis already accepted in Phase 6B-4.

## 11. Manifest

Manifest: `release/v1.0.0/logosgo-v1.0.0-manifest.json`

It records product/version/build identity, release channel/date, supported architecture and OS, bundle identity, KataGo version/backend, backend packaging, app size, accepted source state, frozen analytical settings, regression counts, runtime components, round-trip pass status, and known limitations. JSON parsing and checksum verification pass.

## 12. Hashes

`release/v1.0.0/SHA256SUMS.txt` verifies successfully:

| Artifact | SHA-256 |
|---|---|
| `LogosGo-v1.0.0-macOS-arm64.zip` | `28892525cf3373d82ecddb445ae059fb177d1e39a9f41ca923e101bb4a334509` |
| `logosgo-v1.0.0-manifest.json` | `4351d21ff995b2c09b6891aa12331f3e743fd6994919cabcdaa4b96364937058` |
| `model.bin.gz` | `93abbeea4b4b38a6b5fda83e58927b588e2ca195ef9816b831db9d629c029efa` |
| `analysis.cfg` | `194839bbac3ffef48830e79fa05167a93b3f1b8b602a6b184b954fd72517e796` |

## 13. Release notes

`release/v1.0.0/RELEASE_NOTES.md` describes the stable V1 capabilities, self-contained runtime, supported system, private ad-hoc signature, evidence-grounded commentary limits, and excluded public-distribution/Windows work. It does not present research prototypes as production features.

## 14. Source-delivery audit

Recommended source delivery includes:

- Flutter production source and macOS Runner source/config/assets;
- Python backend, analysis, explanation, review, SGF, and runtime-path source;
- automated tests and deterministic fixtures;
- `analysis.cfg`, required production corpus, and an agreed method for delivering the large model;
- packaging scripts, PyInstaller spec, dependency manifests, and icon master; and
- project, packaging, validation, and release documentation.

Generated PyInstaller/Flutter builds, portable staging trees, caches, logs, temporary SGFs, virtual environments, duplicate extraction directories, and the local 305 MiB archive are not source code. Benchmark/research artifacts should be submitted only when needed to support the methodology and should remain clearly separated from production source. No historical research artifact was deleted in Phase 6D.

## 15. School-deliverable mapping

`docs/school_submission_mapping.md` records:

- source code: available;
- executable: available as `LogosGo.app` in the private V1 archive;
- SQL/database: not applicable;
- final report: not yet supplied;
- PPT: not yet supplied;
- poster source/JPG: not yet supplied.

No unfinished school artifact was fabricated.

## 16. Known backlog

Non-blocking post-V1 items:

- 13 existing Flutter analyzer diagnostics;
- public Developer ID signing and notarization;
- Windows packaging;
- future evidence-grounded commentary/research improvements;
- optional source refactoring;
- optional analysis/cache work; and
- owner selection of which historical benchmark/validation artifacts belong in the eventual release commit.

None is required for the accepted private Apple Silicon V1 executable.

## 17. Git status classification

The working tree is intentionally large because it contains accepted Phase 1–6D work on top of base commit `ad270fccb4f881897e8a8d8ec7924601b42f10b2`.

- **A. Production source:** existing Python analysis/backend/explanation/review/runtime modules; Flutter `main.dart` and `game_review.dart`; macOS Runner lifecycle/config/assets.
- **B. Tests:** Python `test_*.py`, Flutter widget/review tests, Runner tests, and `testdata/` fixtures.
- **C. Packaging:** `.gitignore`, `packaging/macos/` source scripts/spec/dependency manifests/icon master, and native app metadata.
- **D. Documentation:** root README, Phase reports, school mapping, release notes, manifest, and checksums.
- **E. Validation/research:** `benchmark/` calibration/validation data and tools plus the counterfactual prototype.
- **F. Generated/ignored:** Python/Dart caches, CocoaPods/generated Flutter files, Flutter build output, packaging `build/` and `dist/`, runtime logs, local venv, `.DS_Store`, model policy ignore, and the private release ZIP.
- **G. Accidental/unwanted:** none identified. No source deletion, secret, temporary extraction directory, or unexpected executable was found in Git status.

No reset, restore, checkout, clean, stash, history rewrite, or deletion of prior work was performed.

## 18. Gitignore result

PASS. Generated backend/app staging (`/packaging/macos/build/`, `/packaging/macos/dist/`), runtime logs (`/analysis_logs/`), Flutter-generated trees through existing rules, caches, local environments, system files, the model policy, and large private release ZIPs (`/release/**/*.zip`) are ignored. Packaging scripts/specs/assets, release notes, manifest, checksums, and documentation remain visible to Git.

## 19. Release commit/tag status

No local commit or tag was created, and nothing was pushed. The current repository workflow leaves ambiguity about whether all historical benchmark/validation artifacts should be included. Phase 6D therefore preserved the accepted working tree and documented the decision instead of making a destructive or incomplete selection.

When the owner selects that scope, the prepared local release identity is:

- commit message: `release: LogosGo v1.0.0`
- annotated tag: `v1.0.0`

Before creating them, rerun the regression/checksum checks and stage only the classified release source, tests, packaging, selected validation evidence, and documentation. Do not push without explicit authorization.

## 20. Final regression

| Check | Result |
|---|---|
| Full Python suite | PASS — 256 tests |
| Full Flutter suite | PASS — 59 tests |
| Native Runner suite | PASS — 4 tests |
| `flutter analyze` | Baseline preserved — 13 pre-existing diagnostics, no new diagnostic |
| Python `py_compile` | PASS across repository Python source, excluding generated/venv trees |
| Packaging shell syntax | PASS |
| `git diff --check` | PASS |
| Release checksums | PASS |
| ZIP integrity | PASS |
| Archive static round trip | PASS |
| Extracted-app launch/import/close smoke | PASS |

No final regression started a long KataGo analysis.

## 21. Frozen settings verification

Frozen production settings remain unchanged:

- Whole-game analysis: `maxVisits = 100`, `analysisPVLen = 8`, ownership disabled, `numAnalysisThreads = 16`, `numSearchThreadsPerAnalysisThread = 4`.
- Position judgment: `maxVisits = 500`, `numAnalysisThreads = 1`, `numSearchThreadsPerAnalysisThread = 16`, ownership and ownership stdev enabled.
- Canonical reported perspective: `BLACK`.
- Packaged model and `analysis.cfg` hashes match source.
- Executing the packaged KataGo binary reports `KataGo v1.16.4` and `Using Metal backend`.

Phase 6D did not change visits, concurrency, model, rules, komi, ownership behavior, thresholds, cache behavior, commentary, review selection, or trial/variation behavior.

## 22. Process cleanup

PASS. After closing the round-trip-extracted app, a filtered process check returned no LogosGo Runner, `logosgo-backend`, KataGo analysis, or test `server.py` process. The backend process that owned the dynamic loopback listener had exited, so its temporary listener was released. The Runner lifecycle tests also passed all four token, endpoint, and dynamic-port contract checks.

## 23. Remaining release limitations

- Private ad-hoc signature; no Developer ID signature or notarization.
- Apple Silicon and macOS 26.0+ only.
- No Windows build, installer/DMG, App Store package, automatic updater, or public distribution workflow.
- Commentary intentionally abstains or stays conservative when evidence is insufficient; it is not a proof of every local tactical claim.
- The 305 MiB private archive is retained locally and checksummed but ignored by Git.
- Final school report, presentation, and poster remain separate future deliverables.
- The local release commit/tag awaits the owner's historical-validation artifact selection.

These are documented, non-blocking limitations for the private V1 project executable.

## 24. Confirmation no new feature work occurred

Confirmed. Phase 6D performed only release identity/version verification, user/build documentation, packaging/archive creation, checksums, source-delivery/Git audits, round-trip smoke testing, settings verification, regression, and cleanup. It did not add a user feature, alter analytical behavior, begin V1.1, notarize, publish, push, or change accepted Phase 1–6 functionality.

A. LOGOSGO V1.0.0 RELEASE FREEZE PASS
