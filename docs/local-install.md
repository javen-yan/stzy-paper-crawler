# Local Installation

Release archives are source packages. After extracting the archive, install and run the
app locally with the platform script.

## Requirements

- Python 3.10 or newer
- Node.js/npm when `stzy_app/frontend/dist/index.html` is missing

The install scripts use the Tsinghua PyPI mirror by default:

```text
https://pypi.tuna.tsinghua.edu.cn/simple
```

## macOS

```bash
chmod +x install-macos.command
./install-macos.command
```

After installation, start the app with:

```bash
./start-macos.command
```

## Linux

```bash
chmod +x install-linux.sh
./install-linux.sh
```

After installation, start the app with:

```bash
./start-linux.sh
```

## Windows

Double-click `install-windows.bat`.

After installation, start the app with `start-windows.bat`.

## What The Installer Does

- Creates `.venv`
- Installs Python dependencies from `requirements.txt`
- Builds the Vue frontend when `stzy_app/frontend/dist` is missing
- Generates the platform startup script

The startup script launches FastAPI in local GUI mode, opens the browser, and serves the
Vue frontend from the local FastAPI process.
