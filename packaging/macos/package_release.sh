#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
VERSION="1.0.0"
APP="${SCRIPT_DIR}/dist/LogosGo.app"
RELEASE_DIR="${PROJECT_ROOT}/release/v${VERSION}"
ARCHIVE_NAME="LogosGo-v${VERSION}-macOS-arm64.zip"
ARCHIVE="${RELEASE_DIR}/${ARCHIVE_NAME}"
MANIFEST_NAME="logosgo-v${VERSION}-manifest.json"
MANIFEST="${RELEASE_DIR}/${MANIFEST_NAME}"
CHECKSUMS="${RELEASE_DIR}/SHA256SUMS.txt"

fail() {
  echo "error: $*" >&2
  exit 1
}

[[ -d "${APP}" ]] || fail "accepted app not found: ${APP}"
[[ -f "${MANIFEST}" ]] || fail "release manifest not found: ${MANIFEST}"
[[ "$(plutil -extract CFBundleIdentifier raw "${APP}/Contents/Info.plist")" == "com.logosgo.desktop" ]] \
  || fail "unexpected bundle identifier"
[[ "$(plutil -extract CFBundleShortVersionString raw "${APP}/Contents/Info.plist")" == "${VERSION}" ]] \
  || fail "unexpected app version"
[[ "$(plutil -extract CFBundleVersion raw "${APP}/Contents/Info.plist")" == "1" ]] \
  || fail "unexpected app build number"
[[ "$(plutil -extract LSMinimumSystemVersion raw "${APP}/Contents/Info.plist")" == "26.0" ]] \
  || fail "unexpected minimum macOS version"

codesign --verify --deep --strict --verbose=2 "${APP}"

mach_o_list="$(mktemp /private/tmp/logosgo-v1-mach-o.XXXXXX)"
trap 'rm -f "${mach_o_list}"' EXIT
find "${APP}" -type f -print | sort | while IFS= read -r candidate; do
  if file "${candidate}" | grep -q 'Mach-O'; then
    printf '%s\n' "${candidate}"
  fi
done > "${mach_o_list}"

while IFS= read -r candidate; do
  [[ "$(lipo -archs "${candidate}")" == "arm64" ]] \
    || fail "non-arm64 Mach-O in app: ${candidate}"
  if otool -L "${candidate}" 2>/dev/null | tail -n +2 | grep -E '/opt/homebrew|/usr/local|/Users/' >/dev/null; then
    fail "forbidden dependency in app: ${candidate}"
  fi
  if otool -l "${candidate}" 2>/dev/null | tail -n +2 | grep -E '/opt/homebrew|/usr/local|/Users/' >/dev/null; then
    fail "forbidden load-command path in app: ${candidate}"
  fi
done < "${mach_o_list}"

mkdir -p "${RELEASE_DIR}"
case "${ARCHIVE}" in
  "${PROJECT_ROOT}/release/v${VERSION}/${ARCHIVE_NAME}") ;;
  *) fail "refusing to replace unexpected archive path: ${ARCHIVE}" ;;
esac
rm -f "${ARCHIVE}"
ditto -c -k --sequesterRsrc --keepParent "${APP}" "${ARCHIVE}"
unzip -tq "${ARCHIVE}"

(
  cd "${RELEASE_DIR}"
  shasum -a 256 \
    "${ARCHIVE_NAME}" \
    "${MANIFEST_NAME}" \
    ../../model.bin.gz \
    ../../analysis.cfg > "${CHECKSUMS}"
)

echo "Private release archive: ${ARCHIVE}"
du -h "${ARCHIVE}"
shasum -a 256 "${ARCHIVE}"
echo "Checksums: ${CHECKSUMS}"
