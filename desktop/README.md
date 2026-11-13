# PaperDesk · Native Desktop Client (`Rust + Tauri v2`)

完全独立于 Python Web/Server 版的原生跨平台桌面客户端（支持 **macOS Apple Silicon / Intel** 与 **Windows x64**）。无外部 HTTP Server 依赖，所有采集调度、网络请求、AES 加解密、文档渲染转换、SQLite 存储与系统交互均在本地 Rust 进程内完成。

---

## 核心特性

1. **零服务端纯本地架构**
   - 移除 FastAPI / Uvicorn / Web 登录会话与 CSRF，前后端通过 **Tauri v2 Typed IPC (`invoke` + 实时事件流 `task:updated` / `task:progress` / `task:log`)** 通信。
   - 内置自定义安全协议 **`stzyfile://`**（支持 HTTP `206 Partial Content` 字节范围流式读取），毫秒级加载本地多页 PDF 与高清试卷图片预览。
   - 原生系统目录选择器、另存为对话框与 Finder / Explorer 一键定位。

2. **Rust 高并发采集与智能调度引擎**
   - 完整对齐站点签名与 `AES-128-CBC` 响应解密，支持手机号密码登录及 `fetch` / `cURL` / `Cookie` / `Token` 一键解析导入。
   - **VIP 与健康度优先账号池**：自动识别账号剩余额度与 VIP 状态，按冷却状态、连续失败次数与可用配额动态轮换。
   - **严格单链路代理池**：支持固定代理池、通用提取 API 与神龙 HTTP（含本机出口 IP 检测与白名单自动绑定），失败自动冷却隔离。

3. **原生文档转换与排版引擎**
   - **PDF 渲染与合成**：基于预编译 `Pdfium (chromium/6721)` + `lopdf`，支持高清 PNG 逐页导出、多图合成 PDF 及 `UTF-16BE` 书签目录（TOC Outlines）写入。
   - **残缺子集字体 SVG 修复渲染**：通过 `usvg` + `resvg` + `svg2pdf` + 系统/内置 CJK 字体回退，解决源站 SVG 内嵌残缺子集字体导致的缺字空白问题。
   - **Word / ZIP 复合资源处理**：
     - **Windows**：自动按 `Microsoft Word COM` -> `WPS 文字 COM` -> `LibreOffice Headless` 优先级无感转 PDF。
     - **macOS**：自动调用本机 `LibreOffice` 转 PDF，并内置开源度量兼容字体（`Carlito` / `Caladea` / `Tinos` / `Arimo` / `Cousine`）降低跨平台页数漂移。
     - 转换同时始终保留原始 `源文件.docx` / `源文件.doc` / `源文件.zip` 供随时编辑。

4. **现代桌面工作台 UI**
   - 采用 Obsidian Slate 深色玻璃拟态设计体系、左侧原生工作空间导航栏、Bento 指标看板与底部可折叠实时日志控制台。

---

## 目录结构

```text
desktop/
├── frontend/               # Vue 3 + TypeScript + Element Plus 桌面前端
│   ├── src/api/            # Tauri IPC invoke 封装层与 stzyfile:// 协议构造
│   ├── src/components/     # 侧边栏、实时日志台、任务向导、文件树与设置表单
│   ├── src/styles/         # Obsidian Slate + Indigo 现代桌面主题系统
│   └── src/views/          # 任务中心、任务详情、文件库、账号池、系统设置
├── scripts/
│   └── fetch_pdfium.sh     # 按目标平台自动拉取预编译 Pdfium 动态库与开源兼容字体
└── src-tauri/              # Rust 核心引擎与 Tauri v2 宿主
    ├── resources/          # 打包随附的 Pdfium 动态库与兼容字体目录
    └── src/
        ├── auth/           # 登录、凭据解析与账号验证
        ├── commands/       # Tauri #[tauri::command] IPC 接口层
        ├── converter/      # Pdfium / SVG / lopdf / Office 转换管线与字体检测
        ├── crawler/        # 站点加密 API 客户端、分类目录与账号调度器
        ├── proxy/          # 代理租约池、冷却隔离与神龙白名单绑定
        ├── store/          # SQLite (WAL) 存储层与 AES-256-GCM 凭据保险箱
        ├── task_engine/    # 异步任务队列、断点恢复与单资源下载管线
        ├── artifacts.rs    # 本地目录安全浏览、搜索与 ZIP 打包导出
        └── protocol.rs     # stzyfile:// 原生流式协议处理器
```

---

## 本地开发指南

### 1. 环境准备

- **Rust**：`1.80+`（推荐使用 `rustup` 安装最新 stable）
- **Node.js**：`20+` 或 `22+`
- **系统依赖**：
  - **macOS**：Xcode Command Line Tools（`xcode-select --install`）
  - **Windows**：Microsoft C++ Build Tools + WebView2 Runtime（Windows 10/11 默认内置）

### 2. 拉取 Pdfium 动态库（首次构建必做）

```bash
# macOS Apple Silicon
bash desktop/scripts/fetch_pdfium.sh mac-arm64

# macOS Intel
bash desktop/scripts/fetch_pdfium.sh mac-x64

# Windows x64 (Git Bash / MSYS2)
bash desktop/scripts/fetch_pdfium.sh win-x64
```

### 3. 安装前端依赖并启动开发模式

```bash
npm --prefix desktop/frontend install
cargo tauri dev --manifest-path desktop/src-tauri/Cargo.toml
```

> 若尚未全局安装 `tauri-cli`，可执行 `cargo install tauri-cli --version "^2.0.0"`，或直接使用前端 `npm --prefix desktop/frontend run build` + `cargo run --manifest-path desktop/src-tauri/Cargo.toml`。

### 4. 运行后端单元测试

```bash
cargo test --lib --manifest-path desktop/src-tauri/Cargo.toml
```

### 5. 构建生产安装包

**方式一：直接使用内置脚本打包 macOS `.app` 与 `.dmg`（无需额外安装 `tauri-cli`）**

```bash
npm --prefix desktop/frontend run build
cargo build --release --features custom-protocol --manifest-path desktop/src-tauri/Cargo.toml
bash desktop/scripts/package_macos.sh
```

**方式二：使用 Tauri CLI 打包**

```bash
cargo tauri build --manifest-path desktop/src-tauri/Cargo.toml
```

产物位于 `desktop/src-tauri/target/release/bundle/`（macOS `.dmg` / `.app`，Windows `.msi` / `-setup.exe`）。

---

## GitHub Actions 自动打包

仓库已内置跨平台自动构建工作流 [`.github/workflows/build-desktop.yml`](../.github/workflows/build-desktop.yml)：
- 推送到 `main` 分支、发起 PR、手动触发 `workflow_dispatch`，或推送 `v*` / `desktop-v*` 标签，即可在 GitHub 云端并行构建 **macOS (Apple Silicon & Intel `.dmg`)** 与 **Windows x64 (`-setup.exe` & `.msi`)** 安装包。
