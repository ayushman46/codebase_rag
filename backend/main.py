import asyncio
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI
from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from config import get_cors_origins, should_run_local_ingestion_worker
from api.ingest_router import router as ingest_router
from api.query_router import router as query_router
from api.repos_router import router as repos_router
from api.billing_router import router as billing_router
from agent.nemotron import close_async_client
from ingest.local_worker import process_queue_forever


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
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(ingest_router, prefix="/api")
app.include_router(query_router, prefix="/api")
app.include_router(repos_router, prefix="/api")
app.include_router(billing_router, prefix="/api")


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    # The SPA uses only same-origin scripts and API calls. Supabase is needed
    # for OAuth/session traffic and remote HTTPS avatars are permitted.
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; connect-src 'self' https://*.supabase.co https://checkout.razorpay.com https://api.razorpay.com; "
        "img-src 'self' https: data:; style-src 'self'; "
        "script-src 'self' https://checkout.razorpay.com; "
        "frame-src https://checkout.razorpay.com https://api.razorpay.com; "
        "base-uri 'self'; frame-ancestors 'none'; form-action 'self'",
    )
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    return response

@app.get("/api/health", include_in_schema=False)
def health_check():
    return {"status": "ok"}


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
