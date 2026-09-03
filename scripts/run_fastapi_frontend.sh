#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_DIR="${ROOT_DIR}/stzy_app/frontend"
DIST_INDEX="${FRONTEND_DIR}/dist/index.html"
PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"

if [ ! -x "${PYTHON_BIN}" ]; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3)"
  elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python)"
  else
    echo "未找到 Python。请先安装 Python 3.10+，或运行项目安装脚本。"
    exit 1
  fi
fi

if [ ! -f "${DIST_INDEX}" ] || [ "${1:-}" = "--rebuild-frontend" ]; then
  if [ "${1:-}" = "--rebuild-frontend" ]; then
    shift
  fi
  if ! command -v npm >/dev/null 2>&1; then
    echo "前端 dist 不存在且未找到 npm。请先安装 Node.js，或在 stzy_app/frontend 执行 npm run build。"
    exit 1
  fi

  echo "==> 构建 Vue 前端"
  cd "${FRONTEND_DIR}"
  if [ -f "package-lock.json" ]; then
    npm ci
  else
    npm install
  fi
  npm run build
fi

echo "==> 启动 FastAPI，并由 FastAPI 托管 stzy_app/frontend/dist"
cd "${ROOT_DIR}"
exec "${PYTHON_BIN}" -m stzy_app.main "$@"
