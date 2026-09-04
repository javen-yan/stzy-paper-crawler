#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REMOTE_USER="${STZY_DEPLOY_USER:-yanzongzhen}"
REMOTE_HOST="${STZY_DEPLOY_HOST:-192.168.1.32}"
REMOTE_DIR="${STZY_DEPLOY_DIR:-/vol1/1000/service/stzy-paper-crawler/app}"
SERVICE_NAME="${STZY_DEPLOY_SERVICE:-stzy-crawler}"
REMOTE_NODE_DIR="${STZY_REMOTE_NODE_DIR:-/root/.nvm/versions/node/v24.14.0/bin}"
FRONTEND_BUILD_MODE="${STZY_FRONTEND_BUILD_MODE:-auto}"

if ! command -v rsync >/dev/null 2>&1; then
  echo "未找到 rsync。"
  exit 1
fi

SSH_CMD=(ssh -o StrictHostKeyChecking=accept-new)
RSYNC_SSH="ssh -o StrictHostKeyChecking=accept-new"

if command -v sshpass >/dev/null 2>&1 && [ -n "${SSHPASS:-}" ]; then
  SSH_CMD=(sshpass -e "${SSH_CMD[@]}")
  RSYNC_SSH="sshpass -e ${RSYNC_SSH}"
fi

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
  if [ -f package-lock.json ]; then
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
  "${SSH_CMD[@]}" "${REMOTE_USER}@${REMOTE_HOST}" "cd '${REMOTE_DIR}/stzy_app/frontend' && if [ -f package-lock.json ]; then npm ci; else npm install; fi && npm run build"
elif [ -n "${SSHPASS:-}" ] && printf '%s\n' "${SSHPASS}" | "${SSH_CMD[@]}" "${REMOTE_USER}@${REMOTE_HOST}" "sudo -S test -x '${REMOTE_NODE_DIR}/npm'"; then
  echo "==> 使用 sudo Node 路径远端构建前端"
  printf '%s\n' "${SSHPASS}" | "${SSH_CMD[@]}" "${REMOTE_USER}@${REMOTE_HOST}" "cd '${REMOTE_DIR}/stzy_app/frontend' && sudo -S env PATH='${REMOTE_NODE_DIR}':\$PATH sh -c 'if [ -f package-lock.json ]; then npm ci; else npm install; fi && npm run build'"
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
