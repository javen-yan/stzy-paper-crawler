#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

APP_NAME="STZY Paper Crawler"
VENV_DIR=".venv"
PIP_INDEX_URL="https://pypi.tuna.tsinghua.edu.cn/simple"
PLAYWRIGHT_DOWNLOAD_HOST="https://npmmirror.com/mirrors/playwright"

export PIP_INDEX_URL
export PLAYWRIGHT_DOWNLOAD_HOST

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

install_poppler_hint() {
  if command -v apt-get >/dev/null 2>&1; then
    echo "可运行：sudo apt-get update && sudo apt-get install -y poppler-utils"
  elif command -v dnf >/dev/null 2>&1; then
    echo "可运行：sudo dnf install -y poppler-utils"
  elif command -v yum >/dev/null 2>&1; then
    echo "可运行：sudo yum install -y poppler-utils"
  elif command -v pacman >/dev/null 2>&1; then
    echo "可运行：sudo pacman -S --needed poppler"
  elif command -v zypper >/dev/null 2>&1; then
    echo "可运行：sudo zypper install -y poppler-tools"
  else
    echo "请用系统包管理器安装 Poppler/pdftoppm。"
  fi
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

say_step "安装 Playwright Chromium 及系统依赖"
if ! "${VENV_PYTHON}" -m playwright install --with-deps chromium; then
  echo "Playwright 系统依赖自动安装失败，改为只安装 Chromium。"
  "${VENV_PYTHON}" -m playwright install chromium
fi

say_step "检查 PDF 转图片依赖"
if command -v pdftoppm >/dev/null 2>&1; then
  echo "已找到 pdftoppm。"
else
  echo "未找到 pdftoppm。完整 PDF 转 PNG 需要 Poppler。"
  install_poppler_hint
fi

say_step "生成启动脚本"
cat > start-linux.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export PIP_INDEX_URL="https://pypi.tuna.tsinghua.edu.cn/simple"
export PLAYWRIGHT_DOWNLOAD_HOST="https://npmmirror.com/mirrors/playwright"
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
echo "      首次启动需要初始化页面资源，通常等待几秒到几十秒。"
echo "[3/4] 程序会自动选择可用端口；如果 8080 被占用，会自动换到 8081、8082..."
echo "[4/4] 请稍等，下面会显示实际访问地址。"
echo ""
echo "提示：浏览器未自动打开时，请复制终端里的 http://127.0.0.1:xxxx 地址到浏览器。"
echo "提示：请保持这个终端窗口打开；关闭窗口会停止本地服务。"
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
