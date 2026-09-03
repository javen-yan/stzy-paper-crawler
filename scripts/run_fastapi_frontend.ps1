$ErrorActionPreference = "Stop"

$RootDir = Resolve-Path (Join-Path $PSScriptRoot "..")
$FrontendDir = Join-Path $RootDir "stzy_app\frontend"
$DistIndex = Join-Path $FrontendDir "dist\index.html"
$VenvPython = Join-Path $RootDir ".venv\Scripts\python.exe"
$ArgsToForward = [System.Collections.Generic.List[string]]::new()
$RebuildFrontend = $false

foreach ($Arg in $args) {
    if ($Arg -eq "--rebuild-frontend") {
        $RebuildFrontend = $true
    }
    else {
        $ArgsToForward.Add($Arg)
    }
}

if (Test-Path -LiteralPath $VenvPython) {
    $PythonBin = $VenvPython
}
else {
    $PythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $PythonCommand) {
        $PythonCommand = Get-Command py -ErrorAction SilentlyContinue
    }
    if (-not $PythonCommand) {
        Write-Host "未找到 Python。请先安装 Python 3.10+，或运行项目安装脚本。"
        exit 1
    }
    $PythonBin = $PythonCommand.Source
}

if ($RebuildFrontend -or -not (Test-Path -LiteralPath $DistIndex)) {
    $NpmCommand = Get-Command npm -ErrorAction SilentlyContinue
    if (-not $NpmCommand) {
        Write-Host "前端 dist 不存在且未找到 npm。请先安装 Node.js，或在 stzy_app/frontend 执行 npm run build。"
        exit 1
    }

    Write-Host "==> 构建 Vue 前端"
    Push-Location $FrontendDir
    try {
        if (Test-Path -LiteralPath "package-lock.json") {
            & npm ci
        }
        else {
            & npm install
        }
        & npm run build
    }
    finally {
        Pop-Location
    }
}

Write-Host "==> 启动 FastAPI，并由 FastAPI 托管 stzy_app/frontend/dist"
Set-Location -LiteralPath $RootDir
& $PythonBin -m stzy_app.main @ArgsToForward
