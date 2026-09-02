# STZY Paper Crawler

本地 Web 控制台，用于按学段、地区、年级、学期、场景等条件抓取 STZY 试卷 PDF 的逐页预览图片。

完整使用说明见 `操作手册.md`。

## 安装

普通用户可以直接运行对应系统的一键安装脚本：

安装脚本默认使用国内源：

- Python 依赖：清华 PyPI 镜像 `https://pypi.tuna.tsinghua.edu.cn/simple`

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

## 手动安装

```bash
python -m venv .venv
source .venv/bin/activate
export PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
```

PDF 转图片和 SVG 转图片都由 PyMuPDF 处理，不需要额外安装浏览器内核、Poppler 或 Cairo 原生库。

## 账号登录

推荐在右上角“账号配置”里使用手机号登录。密码不填时默认使用手机号后六位。

如果已经在官网浏览器里登录，也可以使用“高级导入”：打开官网 Network，复制 `user/detail`
请求的 `fetch` 或 `cURL`，粘贴到工具里验证并保存。工具会保存真实请求里的
Token、Cookie、User-Agent、Referer、Origin 和必要浏览器请求头；Token 过期时会先尝试
用 Cookie 刷新。

## 启动

```bash
python -m stzy_app.main
```

默认会在本机启动 NiceGUI 控制台。输出目录为 `output`，任务和索引数据记录在
`stzy.db`。

终端同步显示运行日志：

```bash
STZY_CONSOLE_LOG=1 STZY_NO_BROWSER=1 python -m stzy_app.main
```

固定代理可以在“采集策略”里填写，也可以通过环境变量传入：

```bash
STZY_PROXY_MODE=fixed STZY_PROXY_POOL="socks5://user:pass@host:443" python -m stzy_app.main
```

也可以使用提取接口：

```bash
STZY_PROXY_MODE=api STZY_PROXY_PROVIDER=shenlong STZY_PROXY_API_URL="http://api.shenlongip.com/ip?key=...&pattern=json&count=1&sign=..." python -m stzy_app.main
```

提取接口返回神龙 HTTP 的 `{"code":200,"data":[{"ip":"...","port":...}]}` 格式时会自动拼成 `http://ip:port`。接口代理会复用到失败后再刷新，不会每个请求都提取。

使用神龙 HTTP 时，可在“采集策略”里填写白名单账号和签名，点击“绑定本机 IP”。任务开始前也会自动检查一次。

筛选项里的“不限”表示不向接口传该字段，例如选择“安徽 + 七年级上 + 期末”，年份保持“不限”时会一次查询全部年份。

## 命令行小样本

```bash
python -m stzy_app.cli sample
```

该命令会用 `2026 + 免费 + 河南 + 高二 + 高二上` 跑 1 页验证接口与下载链路。
