from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from config import get_cors_origins
from api.ingest_router import router as ingest_router
from api.query_router import router as query_router
from api.repos_router import router as repos_router

app = FastAPI(title="Codebase Intelligence System")

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

@app.get("/")
def read_root():
    return {"status": "ok", "message": "Codebase Intelligence System API v2"}
