from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from stzy_app.crawler import fonts as font_support
from stzy_app.crawler.conversion_pool import configure_conversion_pool, shutdown_conversion_pool
from stzy_app.auth import COOKIE_TOKEN_CONSOLE_SCRIPT
from stzy_app.domain.context import AppContext
from stzy_app.domain.identity import IdentityService, Session
from stzy_app.domain.proxy_status import bind_local_ip, proxy_status
from stzy_app.domain.tasks import TaskConflict
from stzy_app.runtime import RuntimeAdapter
from stzy_app.local import choose_directory, open_path

SESSION_COOKIE = "stzy_session"
CSRF_HEADER = "x-csrf-token"


class LoginRequest(BaseModel):
    password: str


class BootstrapRequest(BaseModel):
    token: str


class TaskCreateRequest(BaseModel):
    mode: str = "crawl"
    filters: dict[str, Any] = Field(default_factory=dict)
    filter_labels: dict[str, Any] = Field(default_factory=dict)
    subjects: list[dict[str, str]] = Field(default_factory=list)
    settings: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = None
    title: str = ""


class AccountRequest(BaseModel):
    name: str
    cookie: str = ""
    access_token: str = ""
    user_agent: str = ""
    request_headers_json: str = ""
    login_phone: str = ""
    login_password: str = ""
    enabled: bool = True


class ImportRequest(BaseModel):
    raw: str
    name: str = ""


class PhoneLoginRequest(BaseModel):
    phone: str
    password: str = ""
    name: str = ""


class EnabledRequest(BaseModel):
    enabled: bool


class ExportRequest(BaseModel):
    task_id: str
    file_paths: list[str] = Field(default_factory=list)


class FontCheckRequest(BaseModel):
    fonts: list[str] = Field(default_factory=list)


def create_app(context: AppContext) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        try:
            yield
        finally:
            context.exports.shutdown()
            shutdown_conversion_pool()

    app = FastAPI(title="STZY Paper Crawler", version="0.2.0", lifespan=lifespan)
    identity = IdentityService(
        context.store,
        admin_password_hash=context.settings.admin_password_hash,
        bootstrap_token=context.runtime.bootstrap_token,
    )
    app.state.context = context
    app.state.identity = identity

    @app.middleware("http")
    async def security_middleware(request: Request, call_next):
        if request.url.path.startswith("/api/"):
            _validate_host_origin(request, context.runtime)
            session = identity.session(request.cookies.get(SESSION_COOKIE))
            request.state.session = session
            public = request.url.path in {
                "/api/v1/runtime",
                "/api/v1/health",
                "/api/v1/auth/login",
                "/api/v1/auth/bootstrap",
                "/api/v1/auth/session",
            }
            if not public and session is None:
                return JSONResponse({"detail": "未登录"}, status_code=401)
            if request.method not in {"GET", "HEAD", "OPTIONS"} and not public:
                if request.headers.get(CSRF_HEADER) != session.csrf_token:
                    return JSONResponse({"detail": "CSRF 校验失败"}, status_code=403)
        return await call_next(request)

    @app.exception_handler(FileNotFoundError)
    async def not_found_handler(_: Request, exc: FileNotFoundError) -> JSONResponse:
        return JSONResponse({"detail": str(exc) or "Not found"}, status_code=404)

    @app.exception_handler(PermissionError)
    async def permission_handler(_: Request, exc: PermissionError) -> JSONResponse:
        return JSONResponse({"detail": str(exc) or "Forbidden"}, status_code=403)

    @app.exception_handler(TaskConflict)
    async def conflict_handler(_: Request, exc: TaskConflict) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(ValueError)
    async def value_error_handler(_: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.get("/api/v1/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "mode": context.runtime.mode}

    @app.get("/api/v1/runtime")
    def runtime() -> dict[str, Any]:
        info = context.runtime.info()
        return {
            "mode": info.mode,
            "host": info.host,
            "port": info.port,
            "public_base_url": info.public_base_url,
            "capabilities": info.capabilities.__dict__,
            "preview": {
                "max_pages": context.settings.preview_max_pages,
                "max_pixels": context.settings.preview_max_pixels,
                "timeout_seconds": context.settings.preview_timeout_seconds,
            },
        }

    @app.post("/api/v1/auth/bootstrap")
    def bootstrap(payload: BootstrapRequest, response: Response) -> dict[str, Any]:
        if context.runtime.mode != "gui":
            raise HTTPException(status_code=404, detail="Not found")
        session = identity.login_bootstrap(payload.token)
        _set_session_cookie(response, session, secure=False)
        return _session_payload(session)

    @app.post("/api/v1/auth/login")
    def login(payload: LoginRequest, request: Request, response: Response) -> dict[str, Any]:
        if context.runtime.mode != "server":
            raise HTTPException(status_code=404, detail="Not found")
        session = identity.login_admin(payload.password, remote=request.client.host if request.client else "")
        _set_session_cookie(response, session, secure=False)
        return _session_payload(session)

    @app.post("/api/v1/auth/logout")
    def logout(request: Request, response: Response, session: Session = Depends(require_session)) -> dict[str, Any]:
        identity.revoke(session.id)
        response.delete_cookie(SESSION_COOKIE, path="/")
        return {"ok": True}

    @app.get("/api/v1/auth/session")
    def session(request: Request) -> dict[str, Any]:
        current = getattr(request.state, "session", None)
        if current is None:
            return {"authenticated": False}
        return _session_payload(current)

    @app.get("/api/v1/accounts")
    def accounts() -> dict[str, Any]:
        return {"items": context.accounts.list_accounts()}

    @app.post("/api/v1/accounts")
    def save_account(payload: AccountRequest) -> dict[str, Any]:
        return context.accounts.upsert(payload.model_dump())

    @app.post("/api/v1/accounts/import")
    def import_account(payload: ImportRequest) -> dict[str, Any]:
        return context.accounts.import_credential(payload.raw, name=payload.name)

    @app.post("/api/v1/accounts/phone-login")
    def phone_login(payload: PhoneLoginRequest) -> dict[str, Any]:
        return context.accounts.phone_login(payload.phone, payload.password, name=payload.name)

    @app.get("/api/v1/accounts/auth-script")
    def auth_script() -> dict[str, Any]:
        return {"script": COOKIE_TOKEN_CONSOLE_SCRIPT}

    @app.post("/api/v1/accounts/{name}/enabled")
    def set_account_enabled(name: str, payload: EnabledRequest) -> dict[str, Any]:
        return context.accounts.set_enabled(name, payload.enabled)

    @app.post("/api/v1/accounts/{name}/verify")
    def verify_account(name: str) -> dict[str, Any]:
        return context.accounts.verify(name)

    @app.delete("/api/v1/accounts/{name}")
    def delete_account(name: str) -> dict[str, Any]:
        context.accounts.delete(name)
        return {"ok": True}

    @app.get("/api/v1/catalogs")
    def catalogs() -> dict[str, Any]:
        return context.catalogs.current()

    @app.post("/api/v1/catalogs/refresh")
    def refresh_catalogs() -> dict[str, Any]:
        return context.catalogs.refresh()

    @app.get("/api/v1/settings")
    def get_settings() -> dict[str, Any]:
        return context.settings_service.get_public_settings()

    @app.put("/api/v1/settings")
    def update_settings(payload: dict[str, Any]) -> dict[str, Any]:
        updated = context.settings_service.update_settings(payload)
        effective = context.settings_service.effective_settings()
        context.artifacts.settings = effective
        if "max_active_tasks" in payload or "max_download_workers" in payload:
            context.tasks.apply_runtime_limits()
        if "max_convert_workers" in payload:
            configure_conversion_pool(effective.max_convert_workers, restart=True)
        if "max_export_workers" in payload:
            context.exports.apply_max_workers(effective.max_export_workers)
        return updated

    @app.get("/api/v1/proxy/status")
    def get_proxy_status() -> dict[str, Any]:
        return proxy_status(context.settings, context.store)

    @app.post("/api/v1/proxy/bind-local-ip")
    def proxy_bind_local_ip() -> dict[str, Any]:
        return bind_local_ip(context.settings, context.store)

    @app.get("/api/v1/fonts/status")
    def font_status() -> dict[str, Any]:
        return font_support.status()

    @app.post("/api/v1/fonts/check")
    def font_check(payload: FontCheckRequest | None = None) -> dict[str, Any]:
        declared = {name.strip() for name in (payload.fonts if payload else []) if name.strip()}
        return font_support.status(declared or None)

    @app.post("/api/v1/fonts/repair")
    def font_repair(payload: FontCheckRequest | None = None) -> dict[str, Any]:
        declared = {name for name in (payload.fonts if payload else []) if name.strip()}
        return font_support.repair(declared or None)

    @app.get("/api/v1/tasks")
    def list_tasks(archived: bool = False, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        return {"items": context.tasks.list_tasks(archived=archived, limit=limit, offset=offset)}

    @app.post("/api/v1/tasks/estimate")
    def estimate_task(payload: TaskCreateRequest) -> dict[str, Any]:
        return context.tasks.estimate_preview(
            filters=payload.filters,
            filter_labels=payload.filter_labels,
            subjects=payload.subjects,
            settings_overrides=payload.settings,
            title=payload.title,
        )

    @app.post("/api/v1/tasks")
    def create_task(payload: TaskCreateRequest) -> dict[str, Any]:
        return context.tasks.create_task(
            mode=payload.mode,
            filters=payload.filters,
            filter_labels=payload.filter_labels,
            subjects=payload.subjects,
            settings_overrides=payload.settings,
            idempotency_key=payload.idempotency_key,
            title=payload.title,
        )

    @app.get("/api/v1/tasks/{task_id}")
    def get_task(task_id: str) -> dict[str, Any]:
        return context.tasks.task(task_id)

    @app.post("/api/v1/tasks/{task_id}/pause")
    def pause_task(task_id: str) -> dict[str, Any]:
        return context.tasks.pause_task(task_id)

    @app.post("/api/v1/tasks/{task_id}/resume")
    def resume_task(task_id: str) -> dict[str, Any]:
        return context.tasks.resume_task(task_id)

    @app.post("/api/v1/tasks/{task_id}/cancel")
    def cancel_task(task_id: str) -> dict[str, Any]:
        return context.tasks.cancel_task(task_id)

    @app.post("/api/v1/tasks/{task_id}/archive")
    def archive_task(task_id: str) -> dict[str, Any]:
        return context.tasks.archive_task(task_id)

    @app.get("/api/v1/tasks/{task_id}/logs")
    def task_logs(task_id: str, after: int = 0, limit: int = 100, tail: bool = False) -> dict[str, Any]:
        items = context.tasks.logs(task_id, after=after, limit=limit, tail=tail)
        next_cursor = items[-1]["id"] if items else after
        return {"items": items, "next_cursor": next_cursor}

    @app.get("/api/v1/tasks/{task_id}/resources")
    def task_resources(task_id: str, limit: int = 100, offset: int = 0, status: str = "") -> dict[str, Any]:
        return context.tasks.resources(task_id, limit=limit, offset=offset, status=status)

    @app.get("/api/v1/artifacts/browser/list")
    def artifact_browser_list(path: str | None = None, task_id: str | None = None) -> dict[str, Any]:
        return context.artifacts.browser_list(task_id=task_id, path=path)

    @app.get("/api/v1/artifacts/browser/search")
    def artifact_browser_search(
        path: str | None = None,
        task_id: str | None = None,
        filter: str = "",
        deep: int = 1,
    ) -> dict[str, Any]:
        return context.artifacts.browser_search(task_id=task_id, path=path, filter_text=filter, deep=bool(deep))

    @app.get("/api/v1/artifacts/browser/preview")
    def artifact_browser_preview(path: str, task_id: str | None = None) -> FileResponse:
        item, file_path = context.artifacts.browser_file(path=path, task_id=task_id)
        media_type = str(item.get("media_type") or "")
        if item.get("kind") not in {"image", "pdf"} and not (media_type.startswith("image/") or media_type == "application/pdf"):
            raise ValueError("Artifact cannot be previewed inline")
        return FileResponse(
            file_path,
            media_type=media_type or None,
            filename=file_path.name,
            content_disposition_type="inline",
        )

    @app.get("/api/v1/artifacts/browser/download")
    def artifact_browser_download(path: str, task_id: str | None = None) -> FileResponse:
        item, file_path = context.artifacts.browser_file(path=path, task_id=task_id)
        return FileResponse(
            file_path,
            media_type=item.get("media_type") or None,
            filename=file_path.name,
            content_disposition_type="attachment",
        )

    @app.api_route(
        "/api/v1/artifacts/browser/{operation}",
        methods=["POST", "PUT", "PATCH", "DELETE"],
    )
    def artifact_browser_readonly(operation: str) -> JSONResponse:
        return JSONResponse({"detail": f"Artifact browser {operation} is read-only"}, status_code=405)

    @app.post("/api/v1/exports")
    def create_export(payload: ExportRequest) -> dict[str, Any]:
        return context.exports.create_zip_export(
            export_id=f"exp_{os.urandom(8).hex()}",
            task_id=payload.task_id,
            file_paths=payload.file_paths,
            ttl_hours=context.settings.export_ttl_hours,
        )

    @app.get("/api/v1/exports/{export_id}")
    def get_export(export_id: str) -> dict[str, Any]:
        item = context.store.export(export_id)
        if not item:
            raise FileNotFoundError("Export not found")
        return item

    @app.get("/api/v1/exports/{export_id}/download")
    def download_export(export_id: str) -> FileResponse:
        export, path = context.exports.export_path(export_id)
        return FileResponse(path, media_type="application/zip", filename=export.get("display_name") or path.name)

    if context.runtime.mode == "gui":
        @app.post("/api/v1/local/choose-directory")
        def local_choose_directory(payload: dict[str, Any]) -> dict[str, Any]:
            initial = Path(str(payload.get("initial_dir") or context.settings.output_dir))
            chosen = choose_directory(initial)
            return {"path": str(chosen) if chosen else ""}

        @app.post("/api/v1/local/open")
        def local_open(payload: dict[str, Any]) -> dict[str, Any]:
            artifact_id = str(payload.get("artifact_id") or "")
            if artifact_id:
                _, path = context.artifacts.get_artifact_path(artifact_id)
                target = path if path.is_dir() else path.parent
            else:
                target = context.artifacts.safe_path(Path(str(payload.get("path") or "")))
            return {"ok": open_path(target)}
    else:
        @app.api_route("/api/v1/local/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
        def local_disabled(path: str) -> None:
            raise HTTPException(status_code=404, detail="Local APIs are only available in GUI mode")

    _mount_frontend(app)
    return app


def require_session(request: Request) -> Session:
    session = getattr(request.state, "session", None)
    if session is None:
        raise HTTPException(status_code=401, detail="未登录")
    return session


def _set_session_cookie(response: Response, session: Session, *, secure: bool) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        session.id,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )


def _session_payload(session: Session) -> dict[str, Any]:
    return {
        "authenticated": True,
        "kind": session.kind,
        "csrf_token": session.csrf_token,
        "expires_at": session.expires_at,
    }


def _validate_host_origin(request: Request, runtime: RuntimeAdapter) -> None:
    allowed_hosts = {"127.0.0.1", "localhost"} if runtime.mode == "gui" else set()
    host = request.headers.get("host", "").split(":", 1)[0].lower()
    if allowed_hosts and host not in allowed_hosts:
        raise PermissionError("Host not allowed")
    origin = request.headers.get("origin") or ""
    if origin and runtime.mode == "gui":
        if not (origin.startswith("http://127.0.0.1:") or origin.startswith("http://localhost:")):
            raise PermissionError("Origin not allowed")


def _mount_frontend(app: FastAPI) -> None:
    frontend_dir = Path(__file__).resolve().parent / "frontend" / "dist"
    if frontend_dir.exists():
        assets_dir = frontend_dir / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(_: str = "") -> FileResponse:
            return FileResponse(frontend_dir / "index.html")

    else:
        @app.get("/", include_in_schema=False)
        def missing_frontend() -> JSONResponse:
            return JSONResponse(
                {
                    "detail": "Frontend assets are missing. Run npm install && npm run build in stzy_app/frontend."
                },
                status_code=503,
            )
