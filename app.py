"""Точка входа FastAPI: подключение маршрутов и общих компонентов."""

from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from config import BASE_DIR
from routers import pages, imports, reports, devices


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with httpx.AsyncClient(timeout=15) as client:
        app.state.http_client = client
        yield

app = FastAPI(lifespan=lifespan, title="Мои финансы")
app.add_middleware(SessionMiddleware, secret_key="local-finance-service-secret")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

app.include_router(devices.router)
app.include_router(pages.router)
app.include_router(imports.router)
app.include_router(reports.router)
