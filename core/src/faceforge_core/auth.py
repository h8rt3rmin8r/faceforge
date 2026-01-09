from __future__ import annotations

from typing import Final

from fastapi import HTTPException, Request, Security
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

AUTHORIZATION_HEADER: Final[str] = "Authorization"
TOKEN_HEADER: Final[str] = "X-FaceForge-Token"
TOKEN_COOKIE: Final[str] = "ff_token"

_bearer_scheme = HTTPBearer(auto_error=False)
_token_header_scheme = APIKeyHeader(name=TOKEN_HEADER, auto_error=False)


def is_exempt_path(path: str) -> bool:
    if path == "/healthz":
        return True
    if path == "/openapi.json":
        return True
    if path.startswith("/docs"):
        return True
    if path.startswith("/redoc"):
        return True
    if path == "/ui/login":
        return True
    return False


def extract_token_from_request(request: Request) -> str | None:
    header_token = request.headers.get(TOKEN_HEADER)
    if header_token:
        return header_token

    cookie_token = request.cookies.get(TOKEN_COOKIE)
    if cookie_token:
        return cookie_token

    auth = request.headers.get(AUTHORIZATION_HEADER)
    if not auth:
        return None

    prefix = "Bearer "
    if auth.startswith(prefix):
        return auth[len(prefix) :].strip() or None
    return None


async def require_install_token(
    request: Request,
    bearer: HTTPAuthorizationCredentials | None = Security(_bearer_scheme),  # noqa: B008
    header_token: str | None = Security(_token_header_scheme),  # noqa: B008
) -> None:
    """Require the per-install token for protected endpoints.

    Accepts either:
    - Authorization: Bearer <token>
    - X-FaceForge-Token: <token>
    """

    expected = getattr(getattr(request.app.state, "faceforge_config", None), "auth", None)
    expected_token = getattr(expected, "install_token", None)

    # If no token exists, fail closed. Startup should ensure one exists.
    if not expected_token:
        raise HTTPException(status_code=500, detail="Server auth token not initialized")

    provided = header_token
    if not provided and bearer is not None:
        provided = bearer.credentials

    if not provided:
        provided = request.cookies.get(TOKEN_COOKIE)

    if not provided:
        raise HTTPException(status_code=401, detail="Missing token")

    if provided != expected_token:
        raise HTTPException(status_code=401, detail="Invalid token")
