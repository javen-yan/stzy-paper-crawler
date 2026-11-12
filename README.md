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

### Word / ZIP 转 PDF（保留原件）

新建任务默认「文件类型：不限（含 Word / ZIP）」。历史 PDF 筛选不自动修改；此前仅保存原件并已完成的任务不会自动重新处理，需要新建相应任务。

- 下载原件保存在资源目录 `源文件.docx` / `源文件.zip` 等，可用于失败后重试。
- 成功输出与原有流程一致：资源同名 PDF（资源目录旁）和资源目录内 `练习N.png`，并生成 `conversion-report.json`。
- ZIP 内已有 PDF：直接合并页面，保留字体、图片和页面尺寸，不重排文字。优先按站点 `fileList` 顺序合并，缺少目录时按文件名自然顺序；PDF 添加子文件书签。ZIP 顶层 `pageNum` 通常仅代表首个文件，不用它判断整包页数。
- ZIP 内文件逐个按实际内容识别（不只看扩展名），支持纯 Word、纯 PDF 和两者混合。转换报告记录每个成员的真实类型、页数和合并起始页；混合包只要含 Word，就标为需要视觉核对，不能当作 PDF 无损合并。
- ZIP 内 Word：同样经过下述 Word 字体与页数检查；图片按原尺寸加入。任何成员失败都不发布整个新结果。加密包、嵌套包、RAR/7z 或不支持的成员目前保留原件并报告部分完成，不静默丢弃。
- ZIP 拒绝越界路径、符号链接，限制 500 个条目、解压后 512 MiB。转换先在临时目录完成，检查通过后再替换旧 PDF 和图片。

**Word 所需依赖和验证边界**

1. 服务机器安装稳定版 LibreOffice Writer 和 fontconfig。`STZY_SOFFICE_PATH` 可指定 soffice 可执行文件。
2. 字体自动补齐（`stzy_app/crawler/fonts.py`）：
   - 先找本机已安装的原版字体，包括 `STZY_WORD_FONT_DIR` 指向的授权字体目录（通过转换进程独立 Fontconfig 配置加载，不修改系统字体）。
   - 仍缺时下载开源且**度量一致**的替代字体到数据目录 `fonts/`：Calibri→Carlito、Cambria→Caladea、Times New Roman→Tinos/Liberation Serif、Arial→Arimo、Courier New→Cousine。这些字体与原字体的字符宽度和行高完全相同，分页不会变化，只有字形轮廓不同，因此可以视为排版等价。
   - 中文字体没有开源同度量替代（宋体→Noto Serif CJK SC / Songti SC、黑体→Noto Sans CJK SC、楷体→AR PL UKai 等全角宽度一致但行高不同），替代后文字覆盖校验照旧，页数按实际结果发布，并在转换报告 `fonts.visual_review` 标记需要视觉验收。选字顺序是本机原版 → 度量一致的开源字体 → 候选中文字体，先用页面接近原字体的，再退到候选。
   - 微软原版字体不会自动下载（不可再分发）。需要 100% 原版字形时，把有授权的字体放进 `STZY_WORD_FONT_DIR`，或设置 `STZY_WORD_FONT_POLICY=strict` 关闭替代。
   - 相关开关：`STZY_WORD_FONT_POLICY`（`substitute` 默认／`strict`）、`STZY_WORD_FONT_AUTO_INSTALL`（默认 `1`）、`STZY_FONT_INSTALL_DIR`（默认 `STZY_DATA_DIR/fonts`）。设置页「Word 字体」标签提供自检和一键补齐。
3. DOCX 检查声明字体和主题字体；旧 DOC 先转临时 DOCX 检查字体。既没有原版也没有可用替代时列出缺失项，保留原件并标记部分完成。实际用了哪些字体、哪些是替代，会写进 `conversion-report.json` 的 `fonts` 字段。
4. Word 转换后检查文字覆盖、非空输出；有站点页数时要求页数一致——除非有字体被替代。替代字体（尤其中文）会改变行高，站点页数不再是可靠参照，此时按实际转换页数发布，并在 `conversion-report.json` 的 `page_check` 写明 `expected` / `actual` / `tolerated`，任务日志也会提示「PDF 已按实际页数发布，排版请人工核对」。字体全部为原版时仍严格比对页数，不一致视为排版异常不发布。检查失败不发布新 PDF，也不标记完成。没有完整原版参照时，这些检查**不等于**已经证明排版完全一致；公式、浮动对象、复杂表格和分页仍需视觉验收。要求严格复刻 Word 版面时，应使用源站完整 PDF 或具备相同字体的原 Word 排版环境。
5. 转换总超时默认 180 秒，可用 `STZY_DOCUMENT_TIMEOUT_SECONDS` 配置；PDF 转 PNG 沿用 `STZY_PREVIEW_TIMEOUT_SECONDS`。

已验证样本：ZIP `773614591691493376` 中试卷 7 页、答题卡 2 页、答案 4 页，合并后 13 页，所有页面在 72 DPI 下与原 PDF 渲染像素一致。Word `773569953530155008` 登录后仍只提供 10/11 页预览；服务器已安装 LibreOffice 7.4.7 和开源替代字体，独立测试输出 11 页且文字覆盖通过，但标题字重、行距和分页位置仍与站点预览不同；启用替代策略后可发布，但 `fonts.visual_review` 会标为需要视觉验收，不能宣称原样验收。
