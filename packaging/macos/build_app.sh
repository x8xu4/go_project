#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
FLUTTER_PROJECT="${PROJECT_ROOT}/flutter_application_1"
DIST_DIR="${SCRIPT_DIR}/dist"
RUNTIME_DIR="${DIST_DIR}/logosgo-runtime"
FLUTTER_APP="${FLUTTER_PROJECT}/build/macos/Build/Products/Release/LogosGo.app"
FINAL_APP="${DIST_DIR}/LogosGo.app"
KATAGO_SOURCE=""
FLUTTER_EXECUTABLE="${FLUTTER_EXECUTABLE:-flutter}"

usage() {
  cat <<'EOF'
Usage: build_app.sh --katago /absolute/path/to/katago

Builds the standalone backend and portable native runtime, generates AppIcon
representations from the checked-in master, builds Flutter Release, embeds the
runtime, signs deepest components first with an ad-hoc identity, validates the
bundle, and outputs packaging/macos/dist/LogosGo.app.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --katago) KATAGO_SOURCE="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "error: unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "arm64" ]]; then
  echo "error: LogosGo.app must be built on Apple Silicon macOS" >&2
  exit 1
fi
if [[ ! -x "${KATAGO_SOURCE}" ]]; then
  echo "error: --katago must name an executable file" >&2
  exit 1
fi
for tool in codesign ditto file find install_name_tool lipo otool plutil shasum sips; do
  if ! command -v "${tool}" >/dev/null 2>&1; then
    echo "error: required tool not found: ${tool}" >&2
    exit 1
  fi
done
if ! command -v "${FLUTTER_EXECUTABLE}" >/dev/null 2>&1; then
  echo "error: Flutter executable not found: ${FLUTTER_EXECUTABLE}" >&2
  exit 1
fi

"${SCRIPT_DIR}/build_backend.sh"
"${SCRIPT_DIR}/build_native_runtime.sh" \
  --katago "${KATAGO_SOURCE}" \
  --backend-dir "${DIST_DIR}/logosgo-backend" \
  --model "${PROJECT_ROOT}/model.bin.gz" \
  --config "${PROJECT_ROOT}/analysis.cfg" \
  --corpus "${PROJECT_ROOT}/logosgo_corpus_full.csv"
"${SCRIPT_DIR}/generate_app_icons.sh"

(
  cd "${FLUTTER_PROJECT}"
  "${FLUTTER_EXECUTABLE}" build macos --release
)

if [[ ! -d "${FLUTTER_APP}" || ! -x "${FLUTTER_APP}/Contents/MacOS/LogosGo" ]]; then
  echo "error: Flutter Release build did not produce ${FLUTTER_APP}" >&2
  exit 1
fi

case "${FINAL_APP}" in
  "${SCRIPT_DIR}/dist/LogosGo.app") ;;
  *) echo "error: refusing to replace unexpected app path: ${FINAL_APP}" >&2; exit 1 ;;
esac
rm -rf "${FINAL_APP}"
ditto "${FLUTTER_APP}" "${FINAL_APP}"
mkdir -p "${FINAL_APP}/Contents/Resources/LogosGoRuntime"
ditto "${RUNTIME_DIR}" "${FINAL_APP}/Contents/Resources/LogosGoRuntime"

chmod 755 \
  "${FINAL_APP}/Contents/MacOS/LogosGo" \
  "${FINAL_APP}/Contents/Resources/LogosGoRuntime/backend/logosgo-backend" \
  "${FINAL_APP}/Contents/Resources/LogosGoRuntime/katago/katago"

MACHO_LIST="${SCRIPT_DIR}/build/final-app-mach-o.txt"
find "${FINAL_APP}" -type f -print | sort | while IFS= read -r candidate; do
  if file "${candidate}" | grep -q 'Mach-O'; then
    printf '%s\n' "${candidate}"
  fi
done > "${MACHO_LIST}"

while IFS= read -r candidate; do
  architectures="$(lipo -archs "${candidate}")"
  if [[ "${architectures}" != "arm64" ]]; then
    if ! tr ' ' '\n' <<<"${architectures}" | grep -qx 'arm64'; then
      echo "error: final Mach-O does not contain arm64 (${architectures}): ${candidate}" >&2
      exit 1
    fi
    mode="$(stat -f '%Lp' "${candidate}")"
    thin_file="${SCRIPT_DIR}/build/$(basename "${candidate}").thin"
    lipo "${candidate}" -thin arm64 -output "${thin_file}"
    chmod "${mode}" "${thin_file}"
    mv "${thin_file}" "${candidate}"
    architectures="$(lipo -archs "${candidate}")"
  fi
  if [[ "${architectures}" != "arm64" ]]; then
    echo "error: failed to produce arm64-only Mach-O: ${candidate}" >&2
    exit 1
  fi
  RPATH_LIST="${SCRIPT_DIR}/build/final-rpaths.txt"
  otool -l "${candidate}" | awk \
    '$1 == "cmd" && $2 == "LC_RPATH" {want=1; next} want && $1 == "path" {print $2; want=0}' \
    > "${RPATH_LIST}"
  while IFS= read -r rpath; do
    case "${rpath}" in
      /opt/homebrew*|/usr/local*|/Users/*)
        chmod u+w "${candidate}"
        install_name_tool -delete_rpath "${rpath}" "${candidate}"
        ;;
    esac
  done < "${RPATH_LIST}"
  if otool -L "${candidate}" 2>/dev/null | tail -n +2 | grep -E '/opt/homebrew|/usr/local|/Users/' >/dev/null; then
    echo "error: forbidden dependency remains in final app: ${candidate}" >&2
    exit 1
  fi
  if otool -l "${candidate}" 2>/dev/null | tail -n +2 | grep -E '/opt/homebrew|/usr/local|/Users/' >/dev/null; then
    echo "error: forbidden load-command path remains in final app: ${candidate}" >&2
    exit 1
  fi
  chmod u+w "${candidate}"
  codesign --force --sign - "${candidate}"
done < "${MACHO_LIST}"

find "${FINAL_APP}/Contents/Frameworks" -depth -type d -name '*.framework' -print | sort -r | while IFS= read -r framework; do
  codesign --force --sign - "${framework}"
done
codesign --force --deep --sign - "${FINAL_APP}"

plutil -lint "${FINAL_APP}/Contents/Info.plist"
if [[ "$(plutil -extract CFBundleIdentifier raw "${FINAL_APP}/Contents/Info.plist")" != "com.logosgo.desktop" ]]; then
  echo "error: unexpected final bundle identifier" >&2
  exit 1
fi
if [[ "$(plutil -extract CFBundleExecutable raw "${FINAL_APP}/Contents/Info.plist")" != "LogosGo" ]]; then
  echo "error: unexpected final bundle executable" >&2
  exit 1
fi
codesign --verify --deep --strict --verbose=2 "${FINAL_APP}"

for relative in \
  backend/logosgo-backend \
  katago/katago \
  model/model.bin.gz \
  config/analysis.cfg \
  data/logosgo_corpus_full.csv; do
  if [[ ! -e "${FINAL_APP}/Contents/Resources/LogosGoRuntime/${relative}" ]]; then
    echo "error: final app is missing runtime resource: ${relative}" >&2
    exit 1
  fi
done

if find "${FINAL_APP}/Contents/Resources/LogosGoRuntime" -type f -name '*.py' -print -quit | grep -q .; then
  echo "error: final app unexpectedly requires Python source files" >&2
  exit 1
fi
if grep -R -I -E '/Users/ouo1010/Desktop/go_project|/opt/homebrew|/usr/local' \
  "${FINAL_APP}/Contents/Resources/LogosGoRuntime" >/dev/null; then
  echo "error: final runtime contains a forbidden developer-machine path" >&2
  exit 1
fi

for asset in model/model.bin.gz config/analysis.cfg data/logosgo_corpus_full.csv; do
  case "${asset}" in
    model/model.bin.gz) source_asset="${PROJECT_ROOT}/model.bin.gz" ;;
    config/analysis.cfg) source_asset="${PROJECT_ROOT}/analysis.cfg" ;;
    data/logosgo_corpus_full.csv) source_asset="${PROJECT_ROOT}/logosgo_corpus_full.csv" ;;
  esac
  source_hash="$(shasum -a 256 "${source_asset}" | awk '{print $1}')"
  bundled_hash="$(shasum -a 256 "${FINAL_APP}/Contents/Resources/LogosGoRuntime/${asset}" | awk '{print $1}')"
  if [[ "${source_hash}" != "${bundled_hash}" ]]; then
    echo "error: final bundled asset differs from source: ${asset}" >&2
    exit 1
  fi
done

echo "Self-contained private app: ${FINAL_APP}"
du -sh "${FINAL_APP}"
