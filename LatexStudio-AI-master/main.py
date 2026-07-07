from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="TeXStudio AI")

BASE_DIR = Path(__file__).parent
app.mount("/static", StaticFiles(directory=BASE_DIR), name="static")


# ── Page routes ────────────────────────────────────────────────────────


@app.get("/")
async def root():
    return FileResponse(BASE_DIR / "login.html")


@app.get("/firebase-init.js")
async def firebase_init():
    return FileResponse(
        BASE_DIR / "firebase-init.js", media_type="application/javascript"
    )


@app.get("/login")
async def login_page():
    return FileResponse(BASE_DIR / "login.html")


@app.get("/projects")
async def projects_page():
    return FileResponse(BASE_DIR / "projects.html")


@app.get("/editor")
async def editor_page():
    return FileResponse(BASE_DIR / "editor.html")


# Run with:  uvicorn main:app --reload --port 8001
# The AI/compile backend lives separately in LatexEditorBackEnd/LatexEditorBackend.py
