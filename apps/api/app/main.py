import sys
from pathlib import Path

# Ensure the project root (contains packages/) is always importable,
# regardless of how uvicorn is launched (e.g. without PYTHONPATH set).
_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent  # C:/Dealmind
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Load .env with override=True so values from the file always win over blank
# system-level environment variables (e.g. ANTHROPIC_API_KEY="" in os.environ).
# This must happen before any module that reads settings or os.environ is imported.
from dotenv import load_dotenv as _load_dotenv
_load_dotenv(
    dotenv_path=Path(__file__).parent.parent.parent / ".env",
    override=True,
)

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

from app.core.config import settings
from app.core.limiter import limiter
from app.api.routes import health, auth, deals, documents, workspaces


# Pure ASGI middleware: rewrites /workspaces → /workspaces/ and /deals → /deals/
# This avoids cross-origin 307 redirects that drop the Authorization header
# when Next.js normalises trailing slashes before the proxy rewrite.
class NormaliseSlashMiddleware:
    """Append trailing slash for list-endpoint paths, without issuing a redirect."""

    _REWRITE = frozenset({"/workspaces", "/deals"})

    def __init__(self, asgi_app):
        self._app = asgi_app

    # Delegate FastAPI-specific attributes so tests and tooling can reach them.
    @property
    def dependency_overrides(self):  # used by FastAPI TestClient fixtures
        return self._app.dependency_overrides

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http" and scope.get("path") in self._REWRITE:
            scope = dict(scope)
            scope["path"] += "/"
            scope["raw_path"] = scope["path"].encode()
        await self._app(scope, receive, send)


import logging
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

_DEFAULT_SECRET_KEY = "change-me-in-production"


def _validate_runtime_secrets() -> None:
    """Fail fast if the JWT signing key is left at its public default.

    The default ``SECRET_KEY`` is committed to the repo, so shipping it would
    let anyone forge a token for any user and defeat every tenancy check.
    We only enforce this in a production-like context (non-SQLite database and
    ``DEBUG`` off); local dev and the SQLite test suite keep working with the
    default.
    """
    is_sqlite = settings.DATABASE_URL.startswith("sqlite")
    production_like = not settings.DEBUG and not is_sqlite
    if not production_like:
        return
    if settings.SECRET_KEY == _DEFAULT_SECRET_KEY or len(settings.SECRET_KEY) < 32:
        raise RuntimeError(
            "SECRET_KEY must be set to a strong, unique value (>= 32 chars) in "
            "production. Refusing to start with the default/weak signing key — "
            "it would allow forging authentication tokens for any user."
        )


@asynccontextmanager
async def _lifespan(app_: FastAPI):
    """Open and close the Arq Redis pool when REDIS_URL is configured.

    Without REDIS_URL the app behaves exactly as before: routes fall back
    to FastAPI BackgroundTasks (see app.services.jobs.enqueue_or_run).
    """
    _validate_runtime_secrets()
    app_.state.arq_pool = None
    if settings.REDIS_URL:
        try:
            from arq import create_pool
            from arq.connections import RedisSettings
            app_.state.arq_pool = await create_pool(
                RedisSettings.from_dsn(settings.REDIS_URL)
            )
            logger.info("Arq pool ready — jobs will be enqueued for the worker.")
        except Exception:
            logger.exception(
                "Failed to initialise Arq pool; the API will keep running "
                "but will fall back to in-process BackgroundTasks.",
            )
            app_.state.arq_pool = None
    yield
    if app_.state.arq_pool is not None:
        try:
            await app_.state.arq_pool.close()
        except Exception:
            logger.exception("Error while closing Arq pool")


_fastapi = FastAPI(
    title="Diligenx",
    description="AI-powered due diligence platform",
    version="0.1.0",
    lifespan=_lifespan,
)

# Rate limiting
_fastapi.state.limiter = limiter

@_fastapi.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"detail": f"Too many requests. Limit: {exc.detail}"},
    )

_fastapi.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_fastapi.include_router(health.router)
_fastapi.include_router(auth.router, prefix="/auth", tags=["auth"])
_fastapi.include_router(deals.router, prefix="/deals", tags=["deals"])
_fastapi.include_router(documents.router, prefix="/documents", tags=["documents"])
_fastapi.include_router(workspaces.router, prefix="/workspaces", tags=["workspaces"])

# Uvicorn entry point: wrap FastAPI with the slash-normalisation ASGI middleware
app = NormaliseSlashMiddleware(_fastapi)
