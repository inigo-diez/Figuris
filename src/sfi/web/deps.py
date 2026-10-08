"""Pieces shared by the web routers: per-request repository and the render lock."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request

from sfi.storage.repository import SQLiteRepository

render_lock = threading.Lock()  # pdfium is not thread-safe
PAGE_DPI = 150
THUMB_DPI = 30  # page thumbnails of the document view


def _repository(request: Request) -> Iterator[SQLiteRepository]:
    """One SQLite connection per request (the worker thread has its own)."""
    repo = SQLiteRepository(request.app.state.settings.database_path, check_same_thread=False)
    try:
        yield repo
    finally:
        repo.close()


Repo = Annotated[SQLiteRepository, Depends(_repository)]


def short_id(document_id: str) -> str:
    return document_id.split(":")[-1][:12]
