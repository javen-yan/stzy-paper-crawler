# STZY Paper Crawler

FastAPI + Vue Web 控制台，用于按学段、学科、地区、年级、学期、场景等条件静默下载 STZY 试卷，并在统一页面中预览图片/PDF、下载单文件或导出 ZIP。

桌面 GUI 模式和 Server 模式共用同一套 FastAPI API、领域服务、SQLite 存储和 Vue 前端。

完整使用说明见 `操作手册.md`。本地安装、架构和发布流程见 `docs/local-install.md`、`docs/gui-server-domain.md`、`docs/release-workflow.md`。

## 安装

Release 提供源码包。下载并解压源码包后，运行对应系统的一键安装脚本；脚本会创建 `.venv`、安装 Python 依赖，并在缺少 `stzy_app/frontend/dist` 时自动构建 Vue 前端。

本地安装需要 Python 3.10+。如果源码包中没有预构建前端，还需要 Node.js/npm 用于构建 Vue 前端。

源码安装脚本默认使用清华 PyPI 镜像 `https://pypi.tuna.tsinghua.edu.cn/simple`。

### macOS

双击 `install-macos.command`，或在终端运行：

```bash
chmod +x install-macos.command
./install-macos.command
```

安装完成后，双击 `start-macos.command` 启动。

### Windows

双击 `install-windows.bat`。

安装完成后，双击 `start-windows.bat` 启动。

### Linux

在终端运行：

```bash
chmod +x install-linux.sh
./install-linux.sh
```

安装完成后，运行：

```bash
./start-linux.sh
```

PDF/SVG 转图片能力由 PyMuPDF 这类 Python 依赖内置提供，三端无需额外安装 Poppler、Cairo 或浏览器内核。

## 开发运行

开发或源码调试时可以直接使用脚本自动补齐前端构建：

```bash
./scripts/run_fastapi_frontend.sh --rebuild-frontend
```

Windows:

```powershell
.\scripts\run_fastapi_frontend.ps1 --rebuild-frontend
```

也可以手动安装依赖并构建前端：

```bash
python -m venv .venv
source .venv/bin/activate
export PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
cd stzy_app/frontend
npm ci
npm run build
```

PDF 转图片和 SVG 转图片都由 PyMuPDF 处理，不需要额外安装浏览器内核、Poppler 或 Cairo 原生库。

## 账号登录

推荐在“账号池”页面使用手机号登录。密码不填时默认使用手机号后六位。

如果已经在官网浏览器里登录，也可以使用“高级导入”：打开官网 Network，复制 `user/detail`
请求的 `fetch` 或 `cURL`，粘贴到工具里验证并保存。工具会保存真实请求里的
Token、Cookie、User-Agent、Referer、Origin 和必要浏览器请求头；Token 过期时会先尝试
用 Cookie 刷新。

## 启动

```bash
python -m stzy_app.main
```

默认会在本机启动 GUI 模式：监听 `127.0.0.1` 自动端口，自动打开浏览器，并使用一次性本地启动凭证建立会话。输出目录、任务、账号池、产物和导出记录默认保存在 `output` 数据目录。

终端同步显示运行日志：

```bash
STZY_CONSOLE_LOG=1 STZY_NO_BROWSER=1 python -m stzy_app.main
```

Server 模式直接监听指定地址和端口，外层 HTTPS、域名、反向代理和证书由部署方独立配置：

```bash
STZY_ADMIN_PASSWORD_HASH='replace-with-hash' \
python -m stzy_app.main --mode server --host 0.0.0.0 --port 8080 --data-dir /opt/stzy-crawler/data
```

Server 模式必须配置管理员密码，否则会拒绝启动。推荐首次部署前生成管理员密码哈希，并写入 `STZY_ADMIN_PASSWORD_HASH`：

```bash
python -m stzy_app.main --hash-password 'your-admin-password'
```

也可以使用 `STZY_ADMIN_PASSWORD_FILE` 指向仅服务用户可读的密码文件；`STZY_ADMIN_PASSWORD` 明文环境变量仅作为临时方式，不建议长期使用。

Domain 拓扑、发布 workflow 和裸机示例见 `docs/gui-server-domain.md`、`docs/release-workflow.md`、`deploy/env.example` 和 `deploy/stzy-crawler.service.example`。

固定代理可以在“设置”页面填写，也可以通过环境变量传入：

```bash
STZY_PROXY_MODE=fixed STZY_PROXY_POOL="socks5://user:pass@host:443" python -m stzy_app.main
```

也可以使用提取接口：

```bash
STZY_PROXY_MODE=api STZY_PROXY_PROVIDER=shenlong STZY_PROXY_API_URL="http://api.shenlongip.com/ip?key=...&pattern=json&count=1&sign=..." python -m stzy_app.main
```

提取接口返回神龙 HTTP 的 `{"code":200,"data":[{"ip":"...","port":...}]}` 格式时会自动拼成 `http://ip:port`。接口代理会复用到失败后再刷新，不会每个请求都提取。

使用神龙 HTTP 时，可在“设置”页面填写白名单账号和签名，点击“绑定本机 IP”。任务开始前也会自动检查一次。

筛选项里的“不限”表示不向接口传该字段，例如选择“安徽 + 七年级上 + 期末”，年份保持“不限”时会一次查询全部年份。

## 命令行小样本

```bash
python -m stzy_app.cli sample
```

该命令会用 `2026 + 免费 + 河南 + 高二 + 高二上` 跑 1 页验证接口与下载链路。
