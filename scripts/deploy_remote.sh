#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REMOTE_USER="${STZY_DEPLOY_USER:-yanzongzhen}"
REMOTE_HOST="${STZY_DEPLOY_HOST:-192.168.1.32}"
REMOTE_PORT="${STZY_DEPLOY_PORT:-22}"
REMOTE_DIR="${STZY_DEPLOY_DIR:-/vol1/1000/service/stzy-paper-crawler/app}"
SERVICE_NAME="${STZY_DEPLOY_SERVICE:-stzy-crawler}"
REMOTE_NODE_DIR="${STZY_REMOTE_NODE_DIR:-/root/.nvm/versions/node/v24.14.0/bin}"
FRONTEND_BUILD_MODE="${STZY_FRONTEND_BUILD_MODE:-auto}"
CJK_FONT_QUERY="${STZY_CJK_FONT_QUERY:-Noto Sans CJK SC}"
SKIP_NPM_INSTALL="${STZY_SKIP_NPM_INSTALL:-0}"
read -r -a EXTRA_SSH_OPTS <<< "${STZY_DEPLOY_SSH_OPTS:-}"

if ! command -v rsync >/dev/null 2>&1; then
  echo "未找到 rsync。"
  exit 1
fi

SSH_CMD=(ssh -p "${REMOTE_PORT}" -o StrictHostKeyChecking=accept-new "${EXTRA_SSH_OPTS[@]}")
RSYNC_SSH="ssh -p ${REMOTE_PORT} -o StrictHostKeyChecking=accept-new ${STZY_DEPLOY_SSH_OPTS:-}"

if command -v sshpass >/dev/null 2>&1 && [ -n "${SSHPASS:-}" ]; then
  SSH_CMD=(sshpass -e "${SSH_CMD[@]}")
  RSYNC_SSH="sshpass -e ${RSYNC_SSH}"
fi

check_remote_fonts() {
  echo "==> 检查远端中文字体"
  local font_check
  font_check="$("${SSH_CMD[@]}" "${REMOTE_USER}@${REMOTE_HOST}" "if command -v fc-match >/dev/null 2>&1; then fc-match -f '%{family}' '${CJK_FONT_QUERY}' || true; else echo ''; fi")"
  if [[ "${font_check}" == *"Noto Sans CJK"* || "${font_check}" == *"Noto Sans SC"* || "${font_check}" == *"Source Han Sans"* || "${font_check}" == *"WenQuanYi"* || "${font_check}" == *"Microsoft YaHei"* || "${font_check}" == *"PingFang"* || "${font_check}" == *"SimHei"* || "${font_check}" == *"SimSun"* ]]; then
    echo "    已找到中文字体：${font_check}"
    return
  fi
  echo "    未检测到可靠中文字体，SVG 转图片/PDF 可能出现方块字或排版偏移。"
  echo "    Debian/Ubuntu 可执行：sudo apt-get update && sudo apt-get install -y fonts-noto-cjk fontconfig && sudo fc-cache -fv"
}

check_remote_fonts

echo "==> 同步代码到 ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_DIR}"
rsync -az --delete \
  --exclude ".git/" \
  --exclude "/env" \
  --exclude "/.env" \
  --exclude ".venv/" \
  --exclude "__pycache__/" \
  --exclude ".pytest_cache/" \
  --exclude "stzy_app/frontend/node_modules/" \
  --exclude "stzy_app/frontend/dist/" \
  --exclude "output/" \
  -e "${RSYNC_SSH}" \
  "${ROOT_DIR}/" "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_DIR}/"

build_frontend_locally() {
  echo "==> 本地构建前端并同步 dist"
  cd "${ROOT_DIR}/stzy_app/frontend"
  if [ "${SKIP_NPM_INSTALL}" = "1" ]; then
    echo "    跳过 npm install/npm ci，复用当前 node_modules"
  elif [ -f package-lock.json ]; then
    npm ci
  else
    npm install
  fi
  npm run build
  rsync -az --delete \
    -e "${RSYNC_SSH}" \
    "${ROOT_DIR}/stzy_app/frontend/dist/" "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_DIR}/stzy_app/frontend/dist/"
}

if [ "${FRONTEND_BUILD_MODE}" = "local-dist" ]; then
  build_frontend_locally
elif "${SSH_CMD[@]}" "${REMOTE_USER}@${REMOTE_HOST}" "command -v npm >/dev/null 2>&1"; then
  echo "==> 远端构建前端"
  "${SSH_CMD[@]}" "${REMOTE_USER}@${REMOTE_HOST}" "cd '${REMOTE_DIR}/stzy_app/frontend' && if [ '${SKIP_NPM_INSTALL}' = '1' ]; then echo '    跳过 npm install/npm ci，复用当前 node_modules'; elif [ -f package-lock.json ]; then npm ci; else npm install; fi && npm run build"
elif [ -n "${SSHPASS:-}" ] && printf '%s\n' "${SSHPASS}" | "${SSH_CMD[@]}" "${REMOTE_USER}@${REMOTE_HOST}" "sudo -S test -x '${REMOTE_NODE_DIR}/npm'"; then
  echo "==> 使用 sudo Node 路径远端构建前端"
  printf '%s\n' "${SSHPASS}" | "${SSH_CMD[@]}" "${REMOTE_USER}@${REMOTE_HOST}" "cd '${REMOTE_DIR}/stzy_app/frontend' && sudo -S env PATH='${REMOTE_NODE_DIR}':\$PATH STZY_SKIP_NPM_INSTALL='${SKIP_NPM_INSTALL}' sh -c 'if [ \"\$STZY_SKIP_NPM_INSTALL\" = \"1\" ]; then echo \"    跳过 npm install/npm ci，复用当前 node_modules\"; elif [ -f package-lock.json ]; then npm ci; else npm install; fi && npm run build'"
else
  echo "==> 远端未找到 npm，改用本地 dist"
  build_frontend_locally
fi

echo "==> 重启 ${SERVICE_NAME}"
if [ -n "${SSHPASS:-}" ]; then
  printf '%s\n' "${SSHPASS}" | "${SSH_CMD[@]}" "${REMOTE_USER}@${REMOTE_HOST}" "sudo -S -p '' systemctl restart '${SERVICE_NAME}' && systemctl is-active '${SERVICE_NAME}'"
else
  "${SSH_CMD[@]}" "${REMOTE_USER}@${REMOTE_HOST}" "sudo systemctl restart '${SERVICE_NAME}' && systemctl is-active '${SERVICE_NAME}'"
fi

echo "==> 部署完成"
