$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

$AppName = "STZY Paper Crawler"
$VenvDir = ".venv"
$PipIndexUrl = "https://pypi.tuna.tsinghua.edu.cn/simple"

$env:PIP_INDEX_URL = $PipIndexUrl

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message"
}

function Find-Python {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        return @{ Exe = "py"; Args = @("-3") }
    }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        return @{ Exe = "python"; Args = @() }
    }
    $python3 = Get-Command python3 -ErrorAction SilentlyContinue
    if ($python3) {
        return @{ Exe = "python3"; Args = @() }
    }
    return $null
}

function Invoke-Python {
    param(
        [hashtable]$PythonCommand,
        [string[]]$Arguments
    )
    & $PythonCommand.Exe @($PythonCommand.Args) @Arguments
}

$PythonCommand = Find-Python
if (-not $PythonCommand) {
    Write-Host "未找到 Python 3。请先安装 Python 3.10 或更新版本："
    Write-Host "https://www.python.org/downloads/"
    Read-Host "按回车退出"
    exit 1
}

Write-Step "检查 Python 版本"
$versionScript = @"
import sys
if sys.version_info < (3, 10):
    raise SystemExit("需要 Python 3.10 或更新版本，当前版本是 " + sys.version.split()[0])
print("Python", sys.version.split()[0])
"@
Invoke-Python -PythonCommand $PythonCommand -Arguments @("-c", $versionScript)

Write-Step "创建虚拟环境"
Invoke-Python -PythonCommand $PythonCommand -Arguments @("-m", "venv", $VenvDir)
$VenvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

Write-Step "升级 pip"
& $VenvPython -m pip install -i $PipIndexUrl --upgrade pip

Write-Step "安装 Python 依赖"
& $VenvPython -m pip install -i $PipIndexUrl -r requirements.txt

Write-Step "生成启动脚本"
$StartWindowsBat = @"
@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
set PYTHONUNBUFFERED=1
cls
echo ========================================
echo  STZY Paper Crawler
echo ========================================
echo.
echo [1/4] 正在检查本地运行环境...
if not exist ".venv\Scripts\python.exe" (
  echo 未找到 .venv\Scripts\python.exe，请先运行 install-windows.bat 完成安装。
  pause
  exit /b 1
)
echo [2/4] 正在启动本地 Web 控制台...
echo       首次启动需要初始化页面资源，通常等待几秒到几十秒。
echo [3/4] 程序会自动选择可用端口；如果 8080 被占用，会自动换到 8081、8082...
echo [4/4] 请稍等，下面会显示实际访问地址。
echo.
echo 提示：浏览器未自动打开时，请复制终端里的 http://127.0.0.1:xxxx 地址到浏览器。
echo 提示：请保持这个终端窗口打开；关闭窗口会停止本地服务。
echo.
echo ---------- 应用内部日志开始 ----------
echo.
".venv\Scripts\python.exe" -m stzy_app.main
pause
"@
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText((Join-Path $PSScriptRoot "start-windows.bat"), $StartWindowsBat, $Utf8NoBom)

@"
`$ErrorActionPreference = "Stop"
Set-Location -LiteralPath `$PSScriptRoot
`$env:PIP_INDEX_URL = "https://pypi.tuna.tsinghua.edu.cn/simple"
`$env:PYTHONUNBUFFERED = "1"
Clear-Host
Write-Host "========================================"
Write-Host " STZY Paper Crawler"
Write-Host "========================================"
Write-Host ""
Write-Host "[1/4] 正在检查本地运行环境..."
if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) {
    Write-Host "未找到 .venv\Scripts\python.exe，请先运行 install-windows.bat 完成安装。"
    Read-Host "按回车退出"
    exit 1
}
Write-Host "[2/4] 正在启动本地 Web 控制台..."
Write-Host "      首次启动需要初始化页面资源，通常等待几秒到几十秒。"
Write-Host "[3/4] 程序会自动选择可用端口；如果 8080 被占用，会自动换到 8081、8082..."
Write-Host "[4/4] 请稍等，下面会显示实际访问地址。"
Write-Host ""
Write-Host "提示：浏览器未自动打开时，请复制终端里的 http://127.0.0.1:xxxx 地址到浏览器。"
Write-Host "提示：请保持这个终端窗口打开；关闭窗口会停止本地服务。"
Write-Host ""
Write-Host "---------- 应用内部日志开始 ----------"
Write-Host ""
& ".venv\Scripts\python.exe" -m stzy_app.main
"@ | Set-Content -LiteralPath "start-windows.ps1" -Encoding UTF8

Write-Step "安装完成"
Write-Host "以后双击 start-windows.bat 即可启动 $AppName。"
$launch = Read-Host "是否现在启动？[Y/n]"
if ([string]::IsNullOrWhiteSpace($launch) -or $launch -match "^[Yy]$") {
    & cmd /c start-windows.bat
}
