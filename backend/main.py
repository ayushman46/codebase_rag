import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request as UrlRequest, urlopen

from fastapi import FastAPI
from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from config import get_cors_origins, should_run_local_ingestion_worker, settings
from api.ingest_router import router as ingest_router
from api.query_router import router as query_router
from api.repos_router import router as repos_router
from api.billing_router import router as billing_router
from api.github_router import router as github_router
from agent.nemotron import close_async_client
from database import DatabaseConfigurationError, assert_turso_schema, get_turso_store
from ingest.local_worker import process_queue_forever

logger = logging.getLogger("codebase_intel")
_dependency_cache: dict[bool, tuple[float, dict]] = {}
_dependency_cache_lock = asyncio.Lock()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Start the automatic ingestion worker with the application."""
    worker_task = None
    if should_run_local_ingestion_worker():
        worker_task = asyncio.create_task(process_queue_forever(), name="local-ingestion-worker")
    try:
        yield
    finally:
        if worker_task:
            worker_task.cancel()
            with suppress(asyncio.CancelledError):
                await worker_task
        with suppress(Exception):
            await close_async_client()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"

app = FastAPI(
    title="Codebase Intelligence System",
    lifespan=lifespan,
    # Reserve the public /docs route for the React marketing page when the
    # application is deployed as one Render web service.
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    # The editing review endpoint carries a short-lived, file-scoped ticket
    # in this header. Without it, the browser rejects the cross-origin
    # preflight before FastAPI can validate the ticket or call GitHub.
    allow_headers=["Authorization", "Content-Type", "X-Editing-Ticket"],
)

app.include_router(ingest_router, prefix="/api")
app.include_router(query_router, prefix="/api")
app.include_router(repos_router, prefix="/api")
app.include_router(billing_router, prefix="/api")
app.include_router(github_router, prefix="/api")


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    request_id = request.headers.get("x-request-id", "").strip()
    if len(request_id) > 96 or not request_id.replace("-", "").replace("_", "").isalnum():
        request_id = uuid.uuid4().hex
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("request failed method=%s path=%s request_id=%s", request.method, request.url.path, request_id)
        raise
    # The SPA uses only same-origin scripts and API calls. Supabase is needed
    # for OAuth/session traffic and remote HTTPS avatars are permitted.
    # The transient GitHub OAuth popup supplies its own nonce-based CSP. The
    # SPA itself uses only bundled self-hosted scripts.
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; "
        "connect-src 'self' https://*.supabase.co https://checkout.razorpay.com https://api.razorpay.com https://api.github.com https://github.com; "
        "img-src 'self' https: data:; "
        "style-src 'self' 'unsafe-inline'; "
        "script-src 'self' https://checkout.razorpay.com; "
        "frame-src https://checkout.razorpay.com https://api.razorpay.com https://github.com; "
        "base-uri 'self'; frame-ancestors 'none'; form-action 'self'",
    )
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "request completed method=%s path=%s status=%s latency_ms=%s request_id=%s",
        request.method,
        request.url.path,
        response.status_code,
        int((time.perf_counter() - started) * 1000),
        request_id,
    )
    return response

@app.get("/api/health", include_in_schema=False)
async def health_check():
    """Fast operational snapshot: liveness plus dependency configuration."""
    checks = await _dependency_checks(probe_nvidia=False)
    healthy = checks["turso"]["status"] == "ok" and checks["nvidia"]["status"] in {"ok", "configured"}
    return {"status": "ok" if healthy else "degraded", "dependencies": checks}


def _probe_nvidia_sync() -> str:
    """Perform a bounded provider probe without creating a chat/embedding job."""
    base_url = settings.nvidia_base_url.strip().rstrip("/")
    request = UrlRequest(f"{base_url}/models", headers={"Authorization": f"Bearer {settings.nvidia_api_key.strip()}"})
    try:
        with urlopen(request, timeout=3.0) as response:
            return "ok" if 200 <= response.status < 300 else "unavailable"
    except HTTPError as error:
        # A healthy API can reject a model-list permission while still being
        # reachable; only transport/server failures make readiness fail.
        return "ok" if 400 <= error.code < 500 else "unavailable"
    except (URLError, TimeoutError, OSError):
        return "unavailable"


async def _dependency_checks(*, probe_nvidia: bool) -> dict:
    cache_ttl = 3.0 if probe_nvidia else 10.0
    cached = _dependency_cache.get(probe_nvidia)
    if cached and time.monotonic() - cached[0] < cache_ttl:
        return cached[1]

    async def check_turso() -> dict:
        try:
            await assert_turso_schema()
            row = await get_turso_store().fetch_one("SELECT 1 AS ok")
            return {"status": "ok" if row and int(row.get("ok", 0)) == 1 else "unavailable"}
        except DatabaseConfigurationError:
            return {"status": "unconfigured"}
        except Exception:
            logger.warning("Turso health probe failed", exc_info=True)
            return {"status": "unavailable"}

    async def check_nvidia() -> dict:
        if not settings.nvidia_api_key.strip():
            return {"status": "unconfigured"}
        if not settings.nvidia_base_url.strip().lower().startswith("https://"):
            return {"status": "invalid_configuration"}
        if not probe_nvidia:
            return {"status": "configured"}
        return {"status": await asyncio.to_thread(_probe_nvidia_sync)}

    # Serialize refreshes so a burst of deployment probes does not open many
    # Turso streams or provider sockets at once. Callers still receive the
    # cached snapshot during the normal probe interval.
    async with _dependency_cache_lock:
        cached = _dependency_cache.get(probe_nvidia)
        if cached and time.monotonic() - cached[0] < cache_ttl:
            return cached[1]
        turso, nvidia = await asyncio.gather(check_turso(), check_nvidia())
        result = {"turso": turso, "nvidia": nvidia}
        _dependency_cache[probe_nvidia] = (time.monotonic(), result)
        return result


@app.get("/api/ready", include_in_schema=False)
async def readiness_check():
    """Dependency readiness probe for deployment checks and incident diagnosis."""
    checks = await _dependency_checks(probe_nvidia=True)
    ready = checks["turso"]["status"] == "ok" and checks["nvidia"]["status"] == "ok"
    payload = {"status": "ready" if ready else "not_ready", "dependencies": checks}
    return JSONResponse(status_code=200 if ready else 503, content=payload)


if FRONTEND_DIST.is_dir():
    # Render builds the Vite site before starting FastAPI. Serve assets directly
    # and send all remaining non-API paths to the SPA for client-side routing.
    assets_dir = FRONTEND_DIST / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="frontend-assets")

    @app.get("/{frontend_path:path}", include_in_schema=False)
    def serve_frontend(frontend_path: str):
        requested_file = (FRONTEND_DIST / frontend_path).resolve()
        if frontend_path and requested_file.is_relative_to(FRONTEND_DIST.resolve()) and requested_file.is_file():
            return FileResponse(requested_file)
        return FileResponse(FRONTEND_DIST / "index.html")
else:
    # Local API-only startup does not package frontend/dist.
    @app.get("/")
    def read_root():
        return {"status": "ok", "message": "Codebase Intelligence System API v2"}
