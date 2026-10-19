#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
PYTHON_EXECUTABLE="${PYTHON_EXECUTABLE:-${PROJECT_ROOT}/venv/bin/python}"
WORK_DIR="${SCRIPT_DIR}/build"
DIST_DIR="${SCRIPT_DIR}/dist"
SPEC_FILE="${SCRIPT_DIR}/backend.spec"
OUTPUT_EXECUTABLE="${DIST_DIR}/logosgo-backend/logosgo-backend"

if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "arm64" ]]; then
  echo "error: LogosGo backend must be built on Apple Silicon macOS" >&2
  exit 1
fi

if [[ ! -x "${PYTHON_EXECUTABLE}" ]]; then
  echo "error: Python executable not found: ${PYTHON_EXECUTABLE}" >&2
  exit 1
fi

if ! "${PYTHON_EXECUTABLE}" -c "import PyInstaller"; then
  echo "error: install packaging/macos/requirements-build.txt first" >&2
  exit 1
fi

rm -rf "${WORK_DIR}" "${DIST_DIR}"

"${PYTHON_EXECUTABLE}" -m PyInstaller \
  --noconfirm \
  --clean \
  --workpath "${WORK_DIR}" \
  --distpath "${DIST_DIR}" \
  "${SPEC_FILE}"

if [[ ! -x "${OUTPUT_EXECUTABLE}" ]]; then
  echo "error: backend build did not produce ${OUTPUT_EXECUTABLE}" >&2
  exit 1
fi

echo "Standalone backend: ${OUTPUT_EXECUTABLE}"
