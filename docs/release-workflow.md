# Source Package Workflow

This project publishes source archives with GitHub Actions.

## Supported Triggers

- GitHub Release published: packages the repository source and uploads `.zip` and
  `.tar.gz` archives to the Release.
- Manual `workflow_dispatch`: packages the current workflow ref using the requested
  version string and keeps the archives as workflow artifacts.

## Archive Contents

The source package includes the files required for local installation and deployment:

- `stzy_app/`
- `requirements.txt`
- `pyproject.toml`
- `README.md`
- `操作手册.md`
- `docs/`
- `deploy/`
- `scripts/run_fastapi_frontend.sh`
- `scripts/run_fastapi_frontend.ps1`
- `install-macos.command`
- `install-linux.sh`
- `install-windows.bat`
- `install-windows.ps1`

The archive excludes local runtime and build output:

- `.venv/`
- `.pytest_cache/`
- `.env*`
- `.stzy-credentials.key`
- `__pycache__/`
- `*.pyc`
- `build/`
- `dist/`
- `output/`
- `stzy.db*`
- `stzy_app/frontend/node_modules/`
- `stzy_app/frontend/dist/`

## Local Installation

After downloading and extracting the source archive:

- macOS: run `chmod +x install-macos.command && ./install-macos.command`
- Linux: run `chmod +x install-linux.sh && ./install-linux.sh`
- Windows: double-click `install-windows.bat`

The install scripts create `.venv`, install Python dependencies, build the Vue frontend
when `stzy_app/frontend/dist` is missing, and generate the platform startup script.

See `docs/local-install.md` for the user-facing installation guide.
