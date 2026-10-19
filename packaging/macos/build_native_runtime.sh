#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT_DIR="${SCRIPT_DIR}/dist/logosgo-runtime"
WORK_DIR="${SCRIPT_DIR}/build/native-runtime"

usage() {
  cat <<'EOF'
Usage: build_native_runtime.sh \
  --katago /absolute/path/to/katago \
  --backend-dir /absolute/path/to/logosgo-backend \
  --model /absolute/path/to/model.bin.gz \
  --config /absolute/path/to/analysis.cfg \
  --corpus /absolute/path/to/logosgo_corpus_full.csv

Creates packaging/macos/dist/logosgo-runtime. All inputs are copied; source
binaries and assets are never edited.
EOF
}

KATAGO_SOURCE=""
BACKEND_SOURCE=""
MODEL_SOURCE=""
CONFIG_SOURCE=""
CORPUS_SOURCE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --katago) KATAGO_SOURCE="${2:-}"; shift 2 ;;
    --backend-dir) BACKEND_SOURCE="${2:-}"; shift 2 ;;
    --model) MODEL_SOURCE="${2:-}"; shift 2 ;;
    --config) CONFIG_SOURCE="${2:-}"; shift 2 ;;
    --corpus) CORPUS_SOURCE="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "error: unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "arm64" ]]; then
  echo "error: native runtime must be staged on Apple Silicon macOS" >&2
  exit 1
fi

for tool in otool install_name_tool codesign lipo file shasum ditto realpath; do
  if ! command -v "${tool}" >/dev/null 2>&1; then
    echo "error: required tool not found: ${tool}" >&2
    exit 1
  fi
done

if [[ ! -x "${KATAGO_SOURCE}" ]]; then
  echo "error: --katago must name an executable file" >&2
  exit 1
fi
if [[ ! -d "${BACKEND_SOURCE}" || ! -x "${BACKEND_SOURCE}/logosgo-backend" ]]; then
  echo "error: --backend-dir must contain executable logosgo-backend" >&2
  exit 1
fi
for item in "${MODEL_SOURCE}" "${CONFIG_SOURCE}" "${CORPUS_SOURCE}"; do
  if [[ ! -f "${item}" ]]; then
    echo "error: required asset is missing: ${item}" >&2
    exit 1
  fi
done

case "${OUTPUT_DIR}" in
  "${SCRIPT_DIR}/dist/logosgo-runtime") ;;
  *) echo "error: refusing to clean unexpected output path: ${OUTPUT_DIR}" >&2; exit 1 ;;
esac

rm -rf "${OUTPUT_DIR}" "${WORK_DIR}"
mkdir -p \
  "${OUTPUT_DIR}/backend" \
  "${OUTPUT_DIR}/katago/lib" \
  "${OUTPUT_DIR}/model" \
  "${OUTPUT_DIR}/config" \
  "${OUTPUT_DIR}/data" \
  "${OUTPUT_DIR}/manifest" \
  "${WORK_DIR}"

ditto "${BACKEND_SOURCE}" "${OUTPUT_DIR}/backend"
cp -L "${KATAGO_SOURCE}" "${OUTPUT_DIR}/katago/katago"
cp -L "${MODEL_SOURCE}" "${OUTPUT_DIR}/model/model.bin.gz"
cp -L "${CONFIG_SOURCE}" "${OUTPUT_DIR}/config/analysis.cfg"
cp -L "${CORPUS_SOURCE}" "${OUTPUT_DIR}/data/logosgo_corpus_full.csv"
chmod u+w "${OUTPUT_DIR}/katago/katago"

QUEUE="${WORK_DIR}/queue.tsv"
MAPPING="${WORK_DIR}/mapping.tsv"
GRAPH="${WORK_DIR}/dependency-graph.tsv"
: > "${QUEUE}"
: > "${MAPPING}"
: > "${GRAPH}"
printf '%s\t%s\t%s\n' "${KATAGO_SOURCE}" "${OUTPUT_DIR}/katago/katago" "executable" >> "${QUEUE}"
printf '%s\t%s\t%s\n' "${KATAGO_SOURCE}" "${OUTPUT_DIR}/katago/katago" "executable" >> "${MAPPING}"

queue_line=1
while [[ ${queue_line} -le $(wc -l < "${QUEUE}") ]]; do
  record="$(sed -n "${queue_line}p" "${QUEUE}")"
  source_file="$(printf '%s' "${record}" | cut -f1)"
  staged_file="$(printf '%s' "${record}" | cut -f2)"
  source_id="$(otool -D "${source_file}" 2>/dev/null | sed -n '2p' || true)"

  otool -L "${source_file}" | tail -n +2 | awk '{print $1}' > "${WORK_DIR}/deps.txt"
  while IFS= read -r dependency; do
    [[ -n "${dependency}" ]] || continue
    if [[ -n "${source_id}" && "${dependency}" == "${source_id}" ]]; then
      continue
    fi
    case "${dependency}" in
      /System/Library/*|/usr/lib/*)
        printf '%s\t%s\tsystem\n' "$(basename "${staged_file}")" "${dependency}" >> "${GRAPH}"
        ;;
      /*)
        if [[ ! -f "${dependency}" ]]; then
          echo "error: non-system dependency does not exist: ${dependency}" >&2
          exit 1
        fi
        dependency_name="$(basename "${dependency}")"
        dependency_target="${OUTPUT_DIR}/katago/lib/${dependency_name}"
        existing_source="$(awk -F '\t' -v target="${dependency_target}" '$2 == target {print $1; exit}' "${MAPPING}")"
        if [[ -n "${existing_source}" && "$(realpath "${existing_source}")" != "$(realpath "${dependency}")" ]]; then
          echo "error: dependency basename collision for ${dependency_name}" >&2
          exit 1
        fi
        if [[ -z "${existing_source}" ]]; then
          cp -L "${dependency}" "${dependency_target}"
          chmod u+w "${dependency_target}"
          printf '%s\t%s\t%s\n' "${dependency}" "${dependency_target}" "dylib" >> "${MAPPING}"
          printf '%s\t%s\t%s\n' "${dependency}" "${dependency_target}" "dylib" >> "${QUEUE}"
        fi
        printf '%s\t%s\tbundled\n' "$(basename "${staged_file}")" "${dependency_name}" >> "${GRAPH}"
        ;;
      @*)
        echo "error: unresolved source dependency requires explicit support: ${dependency}" >&2
        exit 1
        ;;
      *)
        echo "error: unrecognized dependency path: ${dependency}" >&2
        exit 1
        ;;
    esac
  done < "${WORK_DIR}/deps.txt"
  queue_line=$((queue_line + 1))
done

while IFS=$'\t' read -r source_file staged_file kind; do
  source_id="$(otool -D "${source_file}" 2>/dev/null | sed -n '2p' || true)"
  otool -L "${source_file}" | tail -n +2 | awk '{print $1}' > "${WORK_DIR}/deps.txt"
  while IFS= read -r dependency; do
    [[ -n "${dependency}" ]] || continue
    if [[ -n "${source_id}" && "${dependency}" == "${source_id}" ]]; then
      continue
    fi
    case "${dependency}" in
      /System/Library/*|/usr/lib/*) ;;
      /*)
        dependency_name="$(basename "${dependency}")"
        if [[ "${kind}" == "executable" ]]; then
          rewritten="@executable_path/lib/${dependency_name}"
        else
          rewritten="@loader_path/${dependency_name}"
        fi
        install_name_tool -change "${dependency}" "${rewritten}" "${staged_file}"
        ;;
      *)
        echo "error: cannot rewrite dependency: ${dependency}" >&2
        exit 1
        ;;
    esac
  done < "${WORK_DIR}/deps.txt"

  otool -l "${source_file}" | awk '$1 == "cmd" && $2 == "LC_RPATH" {want=1; next} want && $1 == "path" {print $2; want=0}' > "${WORK_DIR}/rpaths.txt"
  while IFS= read -r rpath; do
    [[ -n "${rpath}" ]] || continue
    install_name_tool -delete_rpath "${rpath}" "${staged_file}"
  done < "${WORK_DIR}/rpaths.txt"

  if [[ "${kind}" == "dylib" ]]; then
    install_name_tool -id "@rpath/$(basename "${staged_file}")" "${staged_file}"
  fi
done < "${MAPPING}"

chmod 755 "${OUTPUT_DIR}/katago/katago"
find "${OUTPUT_DIR}/katago/lib" -type f -name '*.dylib' -exec chmod 644 {} \;
chmod 644 \
  "${OUTPUT_DIR}/model/model.bin.gz" \
  "${OUTPUT_DIR}/config/analysis.cfg" \
  "${OUTPUT_DIR}/data/logosgo_corpus_full.csv"

find "${OUTPUT_DIR}" -type f -print | sort > "${WORK_DIR}/all-files.txt"
find "${OUTPUT_DIR}/backend" -type f -print | sort > "${WORK_DIR}/backend-files.txt"
while IFS= read -r candidate; do
  if file "${candidate}" | grep -q 'Mach-O'; then
    chmod u+w "${candidate}"
    codesign --force --sign - "${candidate}"
  fi
done < "${WORK_DIR}/backend-files.txt"

find "${OUTPUT_DIR}/katago/lib" -type f -name '*.dylib' -print | sort > "${WORK_DIR}/dylibs.txt"
while IFS= read -r dylib; do
  chmod u+w "${dylib}"
  codesign --force --sign - "${dylib}"
done < "${WORK_DIR}/dylibs.txt"
codesign --force --sign - "${OUTPUT_DIR}/katago/katago"

while IFS= read -r candidate; do
  if file "${candidate}" | grep -q 'Mach-O'; then
    if ! lipo -archs "${candidate}" | tr ' ' '\n' | grep -qx 'arm64'; then
      echo "error: staged Mach-O does not contain arm64: ${candidate}" >&2
      exit 1
    fi
    if otool -L "${candidate}" 2>/dev/null | tail -n +2 | grep -E '/opt/homebrew|/usr/local|/Users/' >/dev/null; then
      echo "error: forbidden runtime dependency remains: ${candidate}" >&2
      exit 1
    fi
    if otool -l "${candidate}" 2>/dev/null | tail -n +2 | grep -E '/opt/homebrew|/usr/local|/Users/' >/dev/null; then
      echo "error: forbidden load-command path remains: ${candidate}" >&2
      exit 1
    fi
    codesign --verify --strict "${candidate}"
  fi
done < "${WORK_DIR}/all-files.txt"

if grep -R -I -E '/opt/homebrew|/usr/local|/Users/' "${OUTPUT_DIR}" >/dev/null; then
  echo "error: staged runtime contains a forbidden developer-machine path" >&2
  exit 1
fi

for pair in \
  "${MODEL_SOURCE}|${OUTPUT_DIR}/model/model.bin.gz|model/model.bin.gz" \
  "${CONFIG_SOURCE}|${OUTPUT_DIR}/config/analysis.cfg|config/analysis.cfg" \
  "${CORPUS_SOURCE}|${OUTPUT_DIR}/data/logosgo_corpus_full.csv|data/logosgo_corpus_full.csv"; do
  source_asset="${pair%%|*}"
  remainder="${pair#*|}"
  staged_asset="${remainder%%|*}"
  relative_asset="${remainder#*|}"
  source_hash="$(shasum -a 256 "${source_asset}" | awk '{print $1}')"
  staged_hash="$(shasum -a 256 "${staged_asset}" | awk '{print $1}')"
  if [[ "${source_hash}" != "${staged_hash}" ]]; then
    echo "error: copied asset changed: ${relative_asset}" >&2
    exit 1
  fi
  printf '%s  %s\n' "${staged_hash}" "${relative_asset}" >> "${OUTPUT_DIR}/manifest/assets.sha256"
done

{
  printf 'binary\tdependency\tclassification\n'
  sort -u "${GRAPH}"
} > "${OUTPUT_DIR}/manifest/native-dependencies.tsv"

{
  printf 'KataGo runtime: portable Apple Silicon staging\n'
  printf 'KataGo version: '
  "${OUTPUT_DIR}/katago/katago" version 2>&1 | head -n 1
  printf 'Architecture: arm64\n'
  printf 'Assets: byte-identical copies verified by SHA-256\n'
} > "${OUTPUT_DIR}/manifest/runtime.txt"

echo "Portable runtime: ${OUTPUT_DIR}"
