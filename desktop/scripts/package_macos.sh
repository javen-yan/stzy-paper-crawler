#!/usr/bin/env bash
set -euo pipefail

# Packages the release stzy-desktop binary + Pdfium + icons into a signed macOS .app and .dmg

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TAURI_DIR="${SCRIPT_DIR}/../src-tauri"
RELEASE_BIN="${TAURI_DIR}/target/release/stzy-desktop"

if [ ! -f "${RELEASE_BIN}" ]; then
  echo "Error: release binary not found at ${RELEASE_BIN}" >&2
  echo "Run: cargo build --release --features custom-protocol --manifest-path desktop/src-tauri/Cargo.toml" >&2
  exit 1
fi

APP_NAME="STZY Paper Crawler"
VERSION="0.3.0"
ARCH="$(uname -m)"
if [ "${ARCH}" = "arm64" ]; then
  ARCH_LABEL="aarch64"
else
  ARCH_LABEL="${ARCH}"
fi

MACOS_BUNDLE_DIR="${TAURI_DIR}/target/release/bundle/macos"
DMG_BUNDLE_DIR="${TAURI_DIR}/target/release/bundle/dmg"
APP_DIR="${MACOS_BUNDLE_DIR}/${APP_NAME}.app"
CONTENTS_DIR="${APP_DIR}/Contents"
MACOS_EXE_DIR="${CONTENTS_DIR}/MacOS"
RESOURCES_DIR="${CONTENTS_DIR}/Resources"

rm -rf "${APP_DIR}"
mkdir -p "${MACOS_EXE_DIR}" "${RESOURCES_DIR}/resources" "${DMG_BUNDLE_DIR}"

cp -f "${RELEASE_BIN}" "${MACOS_EXE_DIR}/stzy-desktop"
chmod 755 "${MACOS_EXE_DIR}/stzy-desktop"

if [ -f "${TAURI_DIR}/icons/icon.icns" ]; then
  cp -f "${TAURI_DIR}/icons/icon.icns" "${RESOURCES_DIR}/icon.icns"
fi

if [ -d "${TAURI_DIR}/resources" ]; then
  cp -R "${TAURI_DIR}/resources/." "${RESOURCES_DIR}/resources/"
  if [ -f "${TAURI_DIR}/resources/libpdfium.dylib" ]; then
    cp -f "${TAURI_DIR}/resources/libpdfium.dylib" "${RESOURCES_DIR}/libpdfium.dylib"
    chmod 755 "${RESOURCES_DIR}/libpdfium.dylib" "${RESOURCES_DIR}/resources/libpdfium.dylib"
  fi
fi

cat > "${CONTENTS_DIR}/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key>
  <string>zh_CN</string>
  <key>CFBundleDisplayName</key>
  <string>试卷下载器</string>
  <key>CFBundleName</key>
  <string>${APP_NAME}</string>
  <key>CFBundleExecutable</key>
  <string>stzy-desktop</string>
  <key>CFBundleIdentifier</key>
  <string>com.stzy.desktop</string>
  <key>CFBundleIconFile</key>
  <string>icon.icns</string>
  <key>CFBundleInfoDictionaryVersion</key>
  <string>6.0</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>${VERSION}</string>
  <key>CFBundleVersion</key>
  <string>${VERSION}</string>
  <key>LSMinimumSystemVersion</key>
  <string>11.0</string>
  <key>NSHighResolutionCapable</key>
  <true/>
  <key>NSSupportsAutomaticGraphicsSwitching</key>
  <true/>
</dict>
</plist>
EOF

# Ad-hoc sign dynamic libraries and the .app bundle (required on Apple Silicon)
if command -v codesign >/dev/null 2>&1; then
  if [ -f "${RESOURCES_DIR}/libpdfium.dylib" ]; then
    codesign --force --sign - "${RESOURCES_DIR}/libpdfium.dylib"
  fi
  if [ -f "${RESOURCES_DIR}/resources/libpdfium.dylib" ]; then
    codesign --force --sign - "${RESOURCES_DIR}/resources/libpdfium.dylib"
  fi
  codesign --force --deep --sign - "${APP_DIR}"
fi

echo "==> Built macOS App Bundle: ${APP_DIR}"

DMG_PATH="${DMG_BUNDLE_DIR}/${APP_NAME}_${VERSION}_${ARCH_LABEL}.dmg"
ZIP_PATH="${DMG_BUNDLE_DIR}/${APP_NAME}_${VERSION}_${ARCH_LABEL}.app.zip"
rm -f "${DMG_PATH}" "${ZIP_PATH}"

STAGING_DIR="$(mktemp -d)"
trap 'rm -rf "${STAGING_DIR}"' EXIT
cp -R "${APP_DIR}" "${STAGING_DIR}/"
ln -s /Applications "${STAGING_DIR}/Applications"

if command -v hdiutil >/dev/null 2>&1 && hdiutil create -volname "${APP_NAME}" -srcfolder "${STAGING_DIR}" -ov -format UDZO "${DMG_PATH}" >/dev/null 2>&1; then
  echo "==> Built macOS DMG Installer: ${DMG_PATH}"
else
  ditto -c -k --sequesterRsrc --keepParent "${APP_DIR}" "${ZIP_PATH}"
  echo "==> Built macOS ZIP Archive: ${ZIP_PATH}"
fi
