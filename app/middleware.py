"""
app/middleware.py
─────────────────
Production-grade middleware stack.

Applied (in order):
  1. RequestTracingMiddleware  — tags every request with a unique trace ID
  2. SecurityHeadersMiddleware — injects hardened HTTP security headers
  3. Rate limiting             — per-student_id (authenticated) + per-IP (public)
                                 via slowapi
"""
import uuid
import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)


class RequestTracingMiddleware(BaseHTTPMiddleware):
    """
    Attaches a unique X-Request-ID header to every request/response.
    Allows tracing a specific request through all log lines.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        trace_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())[:8]
        request.state.trace_id = trace_id

        response = await call_next(request)
        response.headers["X-Request-ID"] = trace_id
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Injects standard security headers into every response.
    These protect against common web vulnerabilities.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=()"
        # Only add HSTS in production (when behind HTTPS)
        # response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response
