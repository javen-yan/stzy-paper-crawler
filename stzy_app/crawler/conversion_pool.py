from __future__ import annotations

import atexit
from concurrent.futures import ProcessPoolExecutor, TimeoutError
from pathlib import Path
from typing import Any

_POOL: ProcessPoolExecutor | None = None
_MAX_WORKERS = 2


def configure_conversion_pool(max_workers: int, *, restart: bool = False) -> None:
    global _MAX_WORKERS, _POOL
    _MAX_WORKERS = max(1, int(max_workers or 1))
    if restart and _POOL is not None:
        _POOL.shutdown(wait=False, cancel_futures=False)
        _POOL = None


def shutdown_conversion_pool() -> None:
    global _POOL
    if _POOL is not None:
        _POOL.shutdown(wait=True, cancel_futures=True)
        _POOL = None


def run_conversion(method: str, *args: Any, timeout: float | None = None) -> Any:
    pool = _pool()
    future = pool.submit(_dispatch, method, *[str(arg) if isinstance(arg, Path) else arg for arg in args])
    return future.result(timeout=timeout)


def _pool() -> ProcessPoolExecutor:
    global _POOL
    if _POOL is None:
        _POOL = ProcessPoolExecutor(max_workers=_MAX_WORKERS)
    return _POOL


def _dispatch(method: str, *args: Any) -> Any:
    from stzy_app.crawler.converters import DocumentConverter

    if method == "source_to_pdf":
        from stzy_app.crawler.source_documents import source_to_pdf

        return source_to_pdf(Path(args[0]), Path(args[1]), float(args[2]), int(args[3]), args[4])
    if method == "pdf_to_pngs":
        return DocumentConverter.convert_pdf_to_pngs_with_pymupdf(Path(args[0]), Path(args[1]))
    if method == "svg_to_png":
        DocumentConverter.convert_svg_to_png(Path(args[0]), Path(args[1]))
        return None
    if method == "originals_to_pdf":
        DocumentConverter.convert_originals_to_pdf([Path(value) for value in args[0]], Path(args[1]))
        return None
    if method == "image_to_png":
        DocumentConverter.convert_image_to_png(Path(args[0]), Path(args[1]))
        return None
    raise ValueError(f"Unknown conversion method: {method}")


atexit.register(shutdown_conversion_pool)
