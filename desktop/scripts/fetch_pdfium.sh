#!/usr/bin/env bash
set -euo pipefail

# Downloads official prebuilt Pdfium dynamic libraries (BSD-3-Clause)
# from https://github.com/bblanchon/pdfium-binaries into desktop/src-tauri/resources/

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RES_DIR="${SCRIPT_DIR}/../src-tauri/resources"
mkdir -p "${RES_DIR}"

if [ "$#" -ge 2 ]; then
  TARGET_PLATFORM="${1}-${2}"
else
  TARGET_PLATFORM="${1:-auto}"
fi
PDFIUM_TAG="${PDFIUM_TAG:-chromium/6721}"

if [ "${TARGET_PLATFORM}" = "auto" ]; then
  OS_NAME="$(uname -s)"
  ARCH_NAME="$(uname -m)"
  case "${OS_NAME}-${ARCH_NAME}" in
    Darwin-arm64)  TARGET_PLATFORM="mac-arm64" ;;
    Darwin-x86_64) TARGET_PLATFORM="mac-x64" ;;
    Linux-x86_64)  TARGET_PLATFORM="linux-x64" ;;
    Linux-aarch64) TARGET_PLATFORM="linux-arm64" ;;
    MINGW*-x86_64|MSYS*-x86_64|CYGWIN*-x86_64) TARGET_PLATFORM="win-x64" ;;
    *)
      echo "Unsupported auto-detected platform: ${OS_NAME}-${ARCH_NAME}" >&2
      echo "Pass explicit target: mac-arm64 | mac-x64 | win-x64 | linux-x64" >&2
      exit 1
      ;;
  esac
fi

ARCHIVE="pdfium-${TARGET_PLATFORM}.tgz"
ENCODED_TAG="${PDFIUM_TAG//\//%2F}"
URL="https://github.com/bblanchon/pdfium-binaries/releases/download/${ENCODED_TAG}/${ARCHIVE}"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

echo "==> Fetching Pdfium (${TARGET_PLATFORM}) from ${URL}"
curl -fL --retry 3 --connect-timeout 15 -o "${TMP_DIR}/${ARCHIVE}" "${URL}"
(
  cd "${TMP_DIR}"
  tar -xzf "${ARCHIVE}"
)

# Clean any stale cross-platform Pdfium binaries before copying target library
rm -f "${RES_DIR}/libpdfium.dylib" "${RES_DIR}/pdfium.dll" "${RES_DIR}/libpdfium.so"

if [ -f "${TMP_DIR}/lib/libpdfium.dylib" ]; then
  cp -f "${TMP_DIR}/lib/libpdfium.dylib" "${RES_DIR}/libpdfium.dylib"
  chmod 755 "${RES_DIR}/libpdfium.dylib"
  echo "==> Installed ${RES_DIR}/libpdfium.dylib"
elif [ -f "${TMP_DIR}/bin/pdfium.dll" ]; then
  cp -f "${TMP_DIR}/bin/pdfium.dll" "${RES_DIR}/pdfium.dll"
  echo "==> Installed ${RES_DIR}/pdfium.dll"
elif [ -f "${TMP_DIR}/lib/libpdfium.so" ]; then
  cp -f "${TMP_DIR}/lib/libpdfium.so" "${RES_DIR}/libpdfium.so"
  chmod 755 "${RES_DIR}/libpdfium.so"
  echo "==> Installed ${RES_DIR}/libpdfium.so"
else
  echo "Failed to locate Pdfium shared library in archive" >&2
  exit 1
fi
