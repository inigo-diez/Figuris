"""Content-addressed blob storage. Local filesystem now; S3/MinIO later (M3)."""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from typing import Protocol


class BlobStore(Protocol):
    def put(self, data: bytes, extension: str) -> tuple[str, str]:
        """Store bytes; return (sha256, storage_key). Idempotent."""
        ...

    def path(self, key: str) -> Path: ...

    def exists(self, key: str) -> bool: ...


class LocalBlobStore:
    def __init__(self, root: Path):
        self.root = root

    def put(self, data: bytes, extension: str) -> tuple[str, str]:
        digest = hashlib.sha256(data).hexdigest()
        key = f"{digest[:2]}/{digest}.{extension.lstrip('.')}"
        target = self.root / key
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            # Write atomically so a crash never leaves a truncated blob behind.
            fd, tmp = tempfile.mkstemp(dir=target.parent)
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
            os.replace(tmp, target)
        return digest, key

    def path(self, key: str) -> Path:
        return self.root / key

    def exists(self, key: str) -> bool:
        return (self.root / key).is_file()
