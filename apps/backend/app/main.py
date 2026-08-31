from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import chat, health, medications, schedules, users
from app.config import get_settings
from app.errors import register_error_handlers

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description=(
        "프런티어 대화동행 시연용 API. X-Device-ID는 시연용 식별자이며 "
        "정식 인증 수단이 아닙니다."
    ),
)

if settings.is_development:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost", "http://localhost:3000"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

register_error_handlers(app)
app.include_router(health.router)
app.include_router(users.router)
app.include_router(medications.router)
app.include_router(schedules.router)
app.include_router(chat.router)

