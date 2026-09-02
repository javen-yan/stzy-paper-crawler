#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

APP_NAME="STZY Paper Crawler"
VENV_DIR=".venv"
PIP_INDEX_URL="https://pypi.tuna.tsinghua.edu.cn/simple"

export PIP_INDEX_URL

say_step() {
  printf "\n==> %s\n" "$1"
}

find_python() {
  if command -v python3 >/dev/null 2>&1; then
    command -v python3
    return
  fi
  if command -v python >/dev/null 2>&1; then
    command -v python
    return
  fi
  return 1
}

PYTHON_BIN="$(find_python || true)"
if [ -z "${PYTHON_BIN}" ]; then
  echo "未找到 Python 3。请先安装 Python 3.10 或更新版本。"
  exit 1
fi

say_step "检查 Python 版本"
"${PYTHON_BIN}" - <<'PY'
import sys
if sys.version_info < (3, 10):
    raise SystemExit("需要 Python 3.10 或更新版本，当前版本是 " + sys.version.split()[0])
print("Python", sys.version.split()[0])
PY

say_step "创建虚拟环境"
"${PYTHON_BIN}" -m venv "${VENV_DIR}"
VENV_PYTHON="${VENV_DIR}/bin/python"

say_step "升级 pip"
"${VENV_PYTHON}" -m pip install -i "${PIP_INDEX_URL}" --upgrade pip

say_step "安装 Python 依赖"
"${VENV_PYTHON}" -m pip install -i "${PIP_INDEX_URL}" -r requirements.txt

say_step "生成启动脚本"
cat > start-linux.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export PIP_INDEX_URL="https://pypi.tuna.tsinghua.edu.cn/simple"
export PYTHONUNBUFFERED=1
clear 2>/dev/null || true
echo "========================================"
echo " STZY Paper Crawler"
echo "========================================"
echo ""
echo "[1/4] 正在检查本地运行环境..."
if [ ! -x ".venv/bin/python" ]; then
  echo "未找到 .venv/bin/python，请先运行 install-linux.sh 完成安装。"
  read -r -p "按回车退出..."
  exit 1
fi
echo "[2/4] 正在启动本地 Web 控制台..."
echo "[3/4] 正在选择端口..."
echo "[4/4] 启动完成后会显示访问地址。"
echo ""
echo "浏览器未自动打开时，使用终端里的本地地址。"
echo "关闭此窗口会停止服务。"
echo ""
echo "---------- 应用内部日志开始 ----------"
echo ""
".venv/bin/python" -m stzy_app.main
EOF
chmod +x start-linux.sh

say_step "安装完成"
echo "以后运行 ./start-linux.sh 即可启动 ${APP_NAME}。"
read -r -p "是否现在启动？[Y/n] " launch
launch="${launch:-Y}"
if [[ "${launch}" =~ ^[Yy]$ ]]; then
  exec ./start-linux.sh
fi
