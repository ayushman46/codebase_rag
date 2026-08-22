import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from config import get_cors_origins, should_run_local_ingestion_worker
from api.ingest_router import router as ingest_router
from api.ingestion_worker import router as ingestion_worker_router
from api.query_router import router as query_router
from api.repos_router import router as repos_router
from ingest.local_worker import process_queue_forever


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Start an automatic queue worker locally; Vercel uses its cron route."""
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

app = FastAPI(title="Codebase Intelligence System", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ingest_router, prefix="/api")
app.include_router(query_router, prefix="/api")
app.include_router(repos_router, prefix="/api")
app.include_router(ingestion_worker_router, prefix="/api/internal")

@app.get("/")
def read_root():
    return {"status": "ok", "message": "Codebase Intelligence System API v2"}


@app.get("/api/health", include_in_schema=False)
def health_check():
    return {"status": "ok"}
