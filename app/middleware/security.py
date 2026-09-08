# Security middleware: input validation, prompt injection defense, path traversal guard.
from __future__ import annotations

import re
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request, Response, status
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import get_settings
from app.core.logger import get_logger

settings = get_settings()
logger = get_logger("security")

# ── PROMPT INJECTION PATTERNS ──────────────────────────────────────────────────
# Known injection triggers to sanitize from natural-language input before
# sending to the agent orchestrator. Expand this list as new patterns emerge.
_INJECTION_PATTERNS: list[re.Pattern] = [
    re.compile(r"ignore previous instructions", re.IGNORECASE),
    re.compile(r"you are now", re.IGNORECASE),
    re.compile(r"disregard (all|your|the)", re.IGNORECASE),
    re.compile(r"system prompt", re.IGNORECASE),
    re.compile(r"jailbreak", re.IGNORECASE),
    re.compile(r"<\|.*?\|>"),           # Token injection patterns
    re.compile(r"\[INST\]|\[/INST\]"),  # LLaMA instruction markers
]

_APPROVED_UPLOAD_DIRS = frozenset(["data/raw", "data/derived", "data/tiles", "data/reports"])
_MAX_QUERY_LENGTH = 4096


def log_audit_event(event_type: str, actor: str | None = None, details: dict[str, Any] | None = None) -> None:
    """Structured audit logger for security-relevant operations."""
    logger.info(
        "security_audit_event",
        event_type=event_type,
        actor=actor or "anonymous",
        **(details or {}),
    )


def sanitize_query(text: str) -> str:
    """Strips prompt injection patterns from user natural-language input and enforces max length."""
    if len(text) > _MAX_QUERY_LENGTH:
        logger.warning("query_length_exceeded", length=len(text), max_allowed=_MAX_QUERY_LENGTH)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Query exceeds maximum allowed length of {_MAX_QUERY_LENGTH} characters.",
        )

    sanitized = text
    detected_patterns = []
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(sanitized):
            detected_patterns.append(pattern.pattern)
            sanitized = pattern.sub("[REDACTED]", sanitized)
    if sanitized != text:
        log_audit_event(
            event_type="prompt_injection_detected",
            details={"patterns": detected_patterns, "original_length": len(text)},
        )
    return sanitized


def validate_file_path(path: str | Path) -> Path:
    """Ensures file path stays within approved storage directories."""
    p = Path(path)
    for approved in _APPROVED_UPLOAD_DIRS:
        try:
            p.relative_to(Path(settings.storage_local_root) / approved.split("/", 1)[-1])
            return p
        except ValueError:
            continue
    # Check if within storage root at all
    try:
        p.resolve().relative_to(Path(settings.storage_local_root).resolve())
        return p
    except ValueError:
        raise ValueError(f"Path traversal blocked: '{path}' is outside the approved storage root.")


def validate_upload_size(size_bytes: int) -> None:
    """Raises HTTP 413 if the upload exceeds the configured max size."""
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    if size_bytes > max_bytes:
        status_code = getattr(status, "HTTP_413_CONTENT_TOO_LARGE", status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        raise HTTPException(
            status_code=status_code,
            detail=f"File exceeds maximum allowed size of {settings.max_upload_size_mb} MB.",
        )


def validate_image_format(filename: str) -> str:
    """Returns the file extension or raises HTTP 415 for unsupported formats."""
    ext = Path(filename).suffix.lstrip(".").lower()
    if ext not in settings.allowed_image_formats:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported format '.{ext}'. Allowed: {settings.allowed_image_formats}",
        )
    return ext


class SecurityMiddleware(BaseHTTPMiddleware):
    """Request-level security middleware applied globally to all routes."""

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        start_time = time.perf_counter()
        request.state.request_id = request_id

        response: Response = await call_next(request)

        duration = time.perf_counter() - start_time

        # Attach defensive security headers
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time"] = f"{duration:.4f}s"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"

        if settings.app_env == "production" or request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"

        logger.info(
            "http_request_complete",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration=f"{duration:.4f}s",
        )
        return response
