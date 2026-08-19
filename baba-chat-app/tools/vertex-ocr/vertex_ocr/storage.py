"""Atomic, credential-safe persistence helpers for resumable OCR runs."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    """Return an ISO 8601 timestamp in UTC."""

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    """Hash a file in bounded memory."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write bytes through a sibling temporary file and replace atomically."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as handle:
            temp_name = handle.name
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
        temp_name = None
    finally:
        if temp_name:
            Path(temp_name).unlink(missing_ok=True)


def atomic_write_text(path: Path, text: str) -> None:
    """Write UTF-8 text atomically."""

    atomic_write_bytes(path, text.encode("utf-8"))


def atomic_write_json(path: Path, value: Any) -> None:
    """Write readable JSON atomically."""

    rendered = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    atomic_write_text(path, rendered)


def read_json(path: Path) -> Any:
    """Read JSON with a useful path in the error message."""

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc


def safe_error_message(error: BaseException) -> str:
    """Return an error message with common bearer and API-key forms redacted."""

    message = str(error).strip() or error.__class__.__name__
    patterns = (
        (r"(?i)(authorization\s*:\s*bearer\s+)[^\s,;]+", r"\1<redacted>"),
        (r"(?i)(access_token\s*[=:]\s*)[^\s,;&]+", r"\1<redacted>"),
        (r"(?i)(api[_-]?key\s*[=:]\s*)[^\s,;&]+", r"\1<redacted>"),
        (r"(?i)(x-goog-api-key\s*[=:]\s*)[^\s,;&]+", r"\1<redacted>"),
    )
    for pattern, replacement in patterns:
        message = re.sub(pattern, replacement, message)
    return f"{error.__class__.__name__}: {message}"

