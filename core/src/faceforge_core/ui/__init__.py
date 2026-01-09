"""Server-rendered Core Web UI (MVP).

This UI is intentionally lightweight:
- served by the Core FastAPI service
- no runtime Node dependency
- uses simple HTML forms + redirects

Auth: reuses the per-install token via an HttpOnly cookie.
"""
