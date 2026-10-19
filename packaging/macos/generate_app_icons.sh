#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
MASTER="${SCRIPT_DIR}/assets/logosgo_icon_master.png"
APPICON_DIR="${PROJECT_ROOT}/flutter_application_1/macos/Runner/Assets.xcassets/AppIcon.appiconset"

if [[ ! -f "${MASTER}" ]]; then
  echo "error: icon master is missing: ${MASTER}" >&2
  exit 1
fi

dimensions="$(sips -g pixelWidth -g pixelHeight "${MASTER}" 2>/dev/null)"
if ! grep -q 'pixelWidth: 2048' <<<"${dimensions}" || ! grep -q 'pixelHeight: 2048' <<<"${dimensions}"; then
  echo "error: icon master must be a square 2048x2048 image" >&2
  exit 1
fi

mkdir -p "${APPICON_DIR}"
for size in 16 32 64 128 256 512 1024; do
  sips -s format png -z "${size}" "${size}" "${MASTER}" \
    --out "${APPICON_DIR}/app_icon_${size}.png" >/dev/null
done

echo "Generated macOS AppIcon representations from ${MASTER}"
