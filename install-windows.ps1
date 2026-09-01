$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

$AppName = "STZY Paper Crawler"
$VenvDir = ".venv"
$PipIndexUrl = "https://pypi.tuna.tsinghua.edu.cn/simple"
$PlaywrightDownloadHost = "https://npmmirror.com/mirrors/playwright"

$env:PIP_INDEX_URL = $PipIndexUrl
$env:PLAYWRIGHT_DOWNLOAD_HOST = $PlaywrightDownloadHost

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

Write-Step "安装 Playwright Chromium"
& $VenvPython -m playwright install chromium

Write-Step "检查 PDF 转图片依赖"
$PdfToPpm = Get-Command pdftoppm -ErrorAction SilentlyContinue
if ($PdfToPpm) {
    Write-Host "已找到 pdftoppm。"
} else {
    Write-Host "未找到 pdftoppm。完整 PDF 转 PNG 需要 Poppler。"
    Write-Host "如果安装了 winget，可以运行：winget install oschwartz10612.Poppler"
    Write-Host "安装后重新打开终端，确认 pdftoppm 可用。"
}

Write-Step "生成启动脚本"
@"
@echo off
cd /d "%~dp0"
set PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
set PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright
".venv\Scripts\python.exe" -m stzy_app.main
pause
"@ | Set-Content -LiteralPath "start-windows.bat" -Encoding ASCII

@"
`$ErrorActionPreference = "Stop"
Set-Location -LiteralPath `$PSScriptRoot
`$env:PIP_INDEX_URL = "https://pypi.tuna.tsinghua.edu.cn/simple"
`$env:PLAYWRIGHT_DOWNLOAD_HOST = "https://npmmirror.com/mirrors/playwright"
& ".venv\Scripts\python.exe" -m stzy_app.main
"@ | Set-Content -LiteralPath "start-windows.ps1" -Encoding UTF8

Write-Step "安装完成"
Write-Host "以后双击 start-windows.bat 即可启动 $AppName。"
$launch = Read-Host "是否现在启动？[Y/n]"
if ([string]::IsNullOrWhiteSpace($launch) -or $launch -match "^[Yy]$") {
    & $VenvPython -m stzy_app.main
}
