from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.routers import issues, meta, reports

app = FastAPI(title="UAT, Untangled")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = PROJECT_ROOT / "static"

# API routes live under /api; the HTML, CSS and JS are served from /static.
app.include_router(meta.router)
app.include_router(reports.router)
app.include_router(issues.router)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
async def home():
    return FileResponse(STATIC_DIR / "index.html")
