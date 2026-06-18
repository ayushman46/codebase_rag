from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.ingest_router import router as ingest_router
from api.query_router import router as query_router
from api.repos_router import router as repos_router

app = FastAPI(title="Codebase Intelligence System")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ingest_router)
app.include_router(query_router)
app.include_router(repos_router)

@app.get("/")
def root():
    return {"status": "ok", "service": "Codebase Intelligence Backend"}