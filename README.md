# PaperDesk · 试卷下载器原生桌面客户端 (`Rust + Tauri v2`)

跨平台原生桌面客户端（支持 **macOS Apple Silicon / Intel** 与 **Windows x64**），按学段、学科、地区、年级、学期、场景等条件筛选并下载试卷资源，在本地完成 PDF / Word / ZIP / SVG 解析转换、逐页高清图片预览与一键归档导出。

> **分支说明**：
> - `main` 分支（当前主分支）：纯 **Rust + Tauri v2 + Vue 3** 原生桌面客户端，无 Python 或外部 HTTP Server 依赖。
> - `server` 分支：历史 **Python + FastAPI + Web Server** 版本完整归档保留。

完整图文级使用流程请参考 [`操作手册.md`](./操作手册.md)。

---

## 直接下载安装（GitHub Releases）

前往 [**Releases 页面**](https://github.com/javen-yan/stzy-paper-crawler/releases) 下载对应系统的安装包：

- **macOS（Apple Silicon M1/M2/M3/M4）**：`PaperDesk_<版本>_aarch64.dmg`
- **macOS（Intel 芯片）**：`PaperDesk_<版本>_x64.dmg`
- **Windows 10 / 11（64 位）**：`PaperDesk_<版本>_x64-setup.exe`（推荐）或 `PaperDesk_<版本>_x64_en-US.msi`

> **macOS 首次打开提示「“PaperDesk”已损坏，无法打开」说明**：
> 由于安装包由 GitHub Actions 自动构建（未附加付费 Apple Developer ID 公证），通过浏览器下载后会被 macOS 自动标记 `com.apple.quarantine` 隔离属性。
> 1. 双击打开 `.dmg`，**先将 `PaperDesk.app` 拖入 `Applications`（应用程序）文件夹**（不要直接在磁盘映像内双击打开）。
> 2. 在「终端（Terminal）」执行以下命令清除隔离属性后即可正常启动：
>    ```bash
>    xattr -cr "/Applications/PaperDesk.app"
>    ```

---

## 核心特性

1. **零服务端纯本地架构**
   - 移除 FastAPI / Uvicorn / Web 会话鉴权，前后端通过 **Tauri v2 Typed IPC (`invoke` + 实时事件流 `task:updated` / `task:progress` / `task:log`)** 通信。
   - 内置安全流式协议 **`stzyfile://`**（Windows 下自动映射 `http://stzyfile.localhost/`，支持 HTTP `206 Partial Content` 字节范围流式读取），毫秒级加载本地多页 PDF 与高清试卷图片。
   - 原生系统目录选择器、另存为对话框与 Finder / Explorer 一键定位。

2. **Rust 高并发采集与智能账号/代理调度**
   - 完整实现接口签名与 `AES-128-CBC` 响应解密，支持手机号密码一键登录（未填密码默认使用手机号后六位）及浏览器 `fetch` / `cURL` / `Cookie` / `Token` / Console JSON 导入。
   - **VIP 与健康度优先账号池**：本地凭据通过 `AES-256-GCM` 加密持久化，自动识别账号剩余额度与 VIP 等级，按冷却状态、连续失败次数与可用配额动态轮换。
   - **严格租约代理池**：支持直连、固定代理池、通用提取 API 与神龙 HTTP（含本机公网出口 IP 自动探测与白名单一键绑定），单链路失败自动冷却切换。

3. **原生文档转换与排版校验管线**
   - **PDF 渲染与无损合并**：基于预编译 `Pdfium (chromium/6721)` + `lopdf`，支持高清 PNG 逐页渲染、多图合成 PDF、多 PDF 合并及 `UTF-16BE` 书签目录（TOC Outlines）写入。
   - **残缺子集字体 SVG 修复渲染**：通过 `usvg` + `resvg` + `svg2pdf` + `fontdb` 系统/内置 CJK 字体回退，修复源站 SVG 内嵌残缺子集字体导致的缺字空白。
   - **Word / ZIP 复合资源处理（保留原件）**：
     - **Windows**：按 `Microsoft Word COM` -> `WPS 文字 COM` -> `LibreOffice Headless` 优先级静默转 PDF（全程无控制台黑框闪烁）。
     - **macOS**：自动调用本机 `LibreOffice` 转 PDF，支持一键下载开源度量一致替代字体（`Carlito` / `Caladea` / `Tinos` / `Arimo` / `Cousine`）并校验文字覆盖率与页数。
     - 原始 `源文件.docx` / `源文件.doc` / `源文件.zip` 始终完整保留，并输出 `conversion-report.json` 转换审计报告。

4. **Obsidian Slate 现代桌面工作台**
   - 深色玻璃拟态视觉设计、左侧工作空间导航栏、Bento 实时指标看板与底部可折叠实时日志控制台。

---

## 仓库目录结构

```text
.
├── .github/workflows/
│   └── build-desktop.yml       # macOS (arm64/x64) & Windows (x64) 自动测试与安装包构建流水线
├── desktop/
│   ├── package.json            # Tauri CLI 工作区入口
│   ├── frontend/               # Vue 3 + TypeScript + Element Plus 桌面前端
│   │   ├── src/api/            # Tauri IPC invoke 封装与 stzyfile:// 预览协议
│   │   ├── src/components/     # 侧边栏、日志台、新建任务向导、文件浏览与设置组件
│   │   ├── src/styles/         # Obsidian Slate + Indigo 桌面主题样式
│   │   └── src/views/          # 任务中心、任务详情、文件库、账号池、系统设置
│   ├── scripts/
│   │   ├── fetch_pdfium.sh     # 跨平台拉取预编译 Pdfium 动态库 (macOS / Windows / Linux)
│   │   ├── build_frontend.cjs  # Tauri 构建前置前端编译脚本
│   │   └── package_macos.sh    # macOS 本地免 tauri-cli 快速打包 .app / .dmg 脚本
│   └── src-tauri/              # Rust 核心引擎与 Tauri v2 宿主
│       ├── Cargo.toml
│       ├── tauri.conf.json
│       ├── icons/              # macOS (.icns) 与 Windows (.ico) 应用图标
│       ├── resources/          # 随包分发的 Pdfium 动态库目录
│       └── src/
│           ├── auth/           # 手机号登录、fetch/cURL 凭据解析与 JWT 校验
│           ├── commands/       # Tauri #[tauri::command] IPC 接口层
│           ├── converter/      # Pdfium / SVG / lopdf / Office 转换管线与字体自检补齐
│           ├── crawler/        # 站点加密 API 客户端、分类目录缓存与 VIP 账号调度器
│           ├── proxy/          # 代理租约池、冷却隔离与神龙白名单绑定
│           ├── store/          # SQLite (WAL) 存储层与 AES-256-GCM 凭据保险箱
│           ├── task_engine/    # 异步多任务队列、多学科聚合、断点续传与单资源管线
│           ├── artifacts.rs    # 本地目录安全浏览、递归搜索、另存为与 ZIP 导出
│           └── protocol.rs     # stzyfile:// 原生流式协议处理器
├── README.md
└── 操作手册.md
```

---

## 本地开发与构建

### 1. 环境要求

- **Rust**：`1.80+`（推荐通过 `rustup` 安装最新 `stable`）
- **Node.js**：`20+` 或 `22+`
- **系统依赖**：
  - **macOS**：Xcode Command Line Tools（`xcode-select --install`）
  - **Windows**：Microsoft C++ Build Tools + WebView2 Runtime（Windows 10/11 系统默认内置）

### 2. 拉取 Pdfium 动态库（首次构建必做）

```bash
# 自动识别当前系统架构（或显式传入 mac-arm64 | mac-x64 | win-x64）
bash desktop/scripts/fetch_pdfium.sh
```

### 3. 启动开发模式

```bash
npm --prefix desktop install
npm --prefix desktop/frontend ci
npm --prefix desktop run tauri dev
```

### 4. 运行前后端检查与单元测试

```bash
# 前端 TypeScript 类型检查 + Vite 打包验证
npm --prefix desktop/frontend run build

# Rust 核心库单元测试
cargo test --lib --manifest-path desktop/src-tauri/Cargo.toml
```

### 5. 构建生产安装包（macOS `.dmg` / Windows `.exe` & `.msi`）

**通用方式（macOS & Windows）：**

```bash
npm --prefix desktop run tauri build
```

产物位于 `desktop/src-tauri/target/release/bundle/`：
- **macOS**：`dmg/PaperDesk_<version>_<arch>.dmg` 与 `macos/PaperDesk.app`
- **Windows**：`nsis/PaperDesk_<version>_x64-setup.exe` 与 `msi/PaperDesk_<version>_x64_en-US.msi`

**macOS 快速本地打包脚本（无需安装 `@tauri-apps/cli`）：**

```bash
npm --prefix desktop/frontend run build
cargo build --release --features custom-protocol --manifest-path desktop/src-tauri/Cargo.toml
bash desktop/scripts/package_macos.sh
```

---

## GitHub Actions 跨平台自动构建与发布

仓库内置工作流 [`.github/workflows/build-desktop.yml`](./.github/workflows/build-desktop.yml)：

- **日常提交 / PR / 手动触发（`workflow_dispatch`）**：自动在 GitHub 云端并行编译并运行测试，构建产出：
  - `stzy-desktop-macos-arm64`（Apple Silicon `.dmg`）
  - `stzy-desktop-macos-x64`（Intel Mac `.dmg`）
  - `stzy-desktop-windows-x64`（Windows x64 `-setup.exe` 与 `.msi`）
  可直接从 Actions 运行页面的 **Artifacts** 区域下载。
- **版本标签发布（推送 `v*` 或 `desktop-v*` Tag）**：自动构建三端安装包并创建对应的 **GitHub Release** 挂载全部安装附件。
