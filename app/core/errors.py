"""Typed API errors (RFC 7807-style problem details)."""
from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse


class RHOBError(Exception):
    status = 400
    code = "RHOB_ERROR"

    def __init__(self, message: str, details=None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFound(RHOBError):
    status = 404
    code = "NOT_FOUND"


class Conflict(RHOBError):
    status = 409
    code = "CONFLICT"


class Forbidden(RHOBError):
    status = 403
    code = "FORBIDDEN"


class ValidationFailed(RHOBError):
    status = 422
    code = "VALIDATION_FAILED"


class PreconditionFailed(RHOBError):
    status = 412
    code = "PRECONDITION_FAILED"


class TooMany(RHOBError):
    status = 429
    code = "TOO_MANY_SESSIONS"


async def rhob_error_handler(request: Request, exc: RHOBError):
    return JSONResponse(status_code=exc.status, content={"type": exc.code, "title": exc.message,
                                                         "status": exc.status, "details": exc.details})
