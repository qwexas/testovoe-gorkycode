"""Все маршруты `/api`."""

from fastapi import APIRouter

from app.api.errors import error_responses
from app.api.routes import calendar, dialog, events, health, profiles
from app.core.errors import ErrorCode

api_router = APIRouter(prefix="/api", responses=error_responses(ErrorCode.INTERNAL_ERROR))
api_router.include_router(health.router)
api_router.include_router(profiles.router)
api_router.include_router(dialog.router)
api_router.include_router(events.router)
api_router.include_router(calendar.router)
