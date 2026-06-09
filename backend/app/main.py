"""FastAPI entrypoint for Modular Orbit."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.chat import router as chat_router
from app.api.curious import router as curious_router
from app.api.documents import router as documents_router
from app.api.item_chat import router as item_chat_router
from app.api.logs import router as logs_router
from app.api.output_modules import router as output_modules_router
from app.api.plans import router as plans_router
from app.api.shell import router as shell_router
from app.api.story_weave import router as story_weave_router
from app.api.tasks import router as tasks_router
from app.api.user_model import router as user_model_router
from app.core.config import settings


app = FastAPI(title="Modular Orbit", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(chat_router)
app.include_router(curious_router)
app.include_router(documents_router)
app.include_router(item_chat_router)
app.include_router(logs_router)
app.include_router(output_modules_router)
app.include_router(plans_router)
app.include_router(shell_router)
app.include_router(story_weave_router)
app.include_router(tasks_router)
app.include_router(user_model_router)

for router in (
    chat_router,
    curious_router,
    documents_router,
    item_chat_router,
    logs_router,
    output_modules_router,
    plans_router,
    shell_router,
    story_weave_router,
    tasks_router,
    user_model_router,
):
    app.include_router(router, prefix="/api")

frontend_root = Path(__file__).resolve().parents[2] / "frontend"
frontend_dir = frontend_root / "dist" if (frontend_root / "dist").exists() else frontend_root
if frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=frontend_dir, html=True), name="static")


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "app": settings.app_name,
        "environment": settings.environment,
    }
