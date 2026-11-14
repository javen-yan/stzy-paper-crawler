#!/usr/bin/env bash
set -euo pipefail

# Downloads open-source metric-compatible & math replacement fonts (OFL-1.1 / Apache-2.0)
# into desktop/src-tauri/resources/fonts/ so PaperDesk bundles them offline with 0ms latency.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FONTS_DIR="${SCRIPT_DIR}/../src-tauri/resources/fonts"
mkdir -p "${FONTS_DIR}"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

validate_font_file() {
  local file="$1"
  if [ ! -f "${file}" ]; then
    return 1
  fi
  local size
  size="$(wc -c < "${file}" | tr -d '[:space:]')"
  if [ "${size:-0}" -lt 4096 ]; then
    return 1
  fi
  local magic
  magic="$(od -An -tx1 -N4 "${file}" | tr -d '[:space:]' | tr '[:upper:]' '[:lower:]')"
  case "${magic}" in
    00010000|4f54544f|74727565|74746366)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

fetch_one_font() {
  local filename="$1"
  shift
  local target="${FONTS_DIR}/${filename}"

  if validate_font_file "${target}"; then
    echo "==> Cached valid font: ${filename}"
    return 0
  fi

  local tmp_file="${TMP_DIR}/${filename}"
  for url in "$@"; do
    echo "==> Fetching ${filename} from ${url}"
    if curl -fsSL --retry 2 --connect-timeout 10 --max-time 45 -o "${tmp_file}" "${url}"; then
      if validate_font_file "${tmp_file}"; then
        mv -f "${tmp_file}" "${target}"
        chmod 644 "${target}"
        echo "==> Installed ${filename}"
        return 0
      fi
    fi
    rm -f "${tmp_file}"
  done

  echo "Error: failed to download valid font ${filename}" >&2
  return 1
}

fetch_google_ofl_font() {
  local filename="$1"
  local rel_path="$2"
  fetch_one_font "${filename}" \
    "https://raw.githubusercontent.com/google/fonts/main/ofl/${rel_path}" \
    "https://cdn.jsdelivr.net/gh/google/fonts@main/ofl/${rel_path}" \
    "https://ghfast.top/https://raw.githubusercontent.com/google/fonts/main/ofl/${rel_path}"
}

fetch_google_ofl_font "Carlito-Regular.ttf" "carlito/Carlito-Regular.ttf"
fetch_google_ofl_font "Carlito-Bold.ttf"    "carlito/Carlito-Bold.ttf"
fetch_google_ofl_font "Caladea-Regular.ttf" "caladea/Caladea-Regular.ttf"
fetch_google_ofl_font "Caladea-Bold.ttf"    "caladea/Caladea-Bold.ttf"
fetch_google_ofl_font "Tinos-Regular.ttf"   "tinos/Tinos-Regular.ttf"
fetch_google_ofl_font "Tinos-Bold.ttf"      "tinos/Tinos-Bold.ttf"
fetch_google_ofl_font "Arimo-Variable.ttf"  "arimo/Arimo%5Bwght%5D.ttf"
fetch_google_ofl_font "Cousine-Regular.ttf" "cousine/Cousine-Regular.ttf"
fetch_google_ofl_font "Cousine-Bold.ttf"    "cousine/Cousine-Bold.ttf"

fetch_google_ofl_font "STIXTwoMath-Regular.ttf" "stixtwomath/STIXTwoMath-Regular.ttf"

cat > "${FONTS_DIR}/README.txt" <<'EOF'
内置开源替代字体说明
Carlito        SIL Open Font License 1.1  https://github.com/googlefonts/carlito
Caladea        Apache License 2.0         https://github.com/huertatipografica/Caladea
Tinos          Apache License 2.0         https://github.com/credmp/tinos
Arimo          Apache License 2.0         https://github.com/rsms/arimo
Cousine        Apache License 2.0         https://github.com/googlefonts/cousine
STIX Two Math  SIL Open Font License 1.1  https://github.com/stipub/stixfonts
这些字体仅用于自动替代缺失字体以保证试卷排版与公式正常显示；原作者与商标权利归各自所有者。
EOF

echo "==> All 10 open-source replacement font files verified in ${FONTS_DIR}"
