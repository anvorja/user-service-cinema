# app/main.py
import asyncio
import logging
import time
import uuid

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import engine, SessionLocal
from app.api.routes import router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

_consumer_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global _consumer_task
    logger.info("User Service starting...")

    # Crear solo la tabla users en cinema_users (los modelos de booking son
    # read-only y viven en cinema_booking — no se deben crear aquí).
    from app.models.user import User
    User.__table__.create(bind=engine, checkfirst=True)

    # Kafka: producer (publica user.deactivated) + consumer (recibe user.registered)
    from app.kafka.producer import start_producer, stop_producer
    from app.kafka.consumer import start_consumer
    await start_producer()
    _consumer_task = asyncio.create_task(start_consumer(SessionLocal))

    yield

    if _consumer_task:
        _consumer_task.cancel()
        try:
            await _consumer_task
        except asyncio.CancelledError:
            pass
    await stop_producer()
    logger.info("User Service shutting down")


app = FastAPI(
    title="User Service",
    description="Perfil de usuario — DB propia cinema_users",
    version=settings.VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Métricas de Prometheus (latencia/conteo por endpoint) en /metrics
Instrumentator().instrument(app).expose(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def logging_middleware(request: Request, call_next):
    request_id = str(uuid.uuid4())[:8]
    start = time.time()
    logger.info("[%s] %s %s", request_id, request.method, request.url.path)
    response = await call_next(request)
    logger.info("[%s] %s | %.2fs", request_id, response.status_code, time.time() - start)
    response.headers["X-Request-ID"] = request_id
    return response


app.include_router(router)


@app.get("/health", tags=["Health"])
async def health_check():
    try:
        with Session(engine) as db:
            db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as err:
        logger.error("DB health check failed: %s", err)
        db_status = "disconnected"

    consumer_running = _consumer_task is not None and not _consumer_task.done()

    return {
        "status": "healthy" if db_status == "connected" else "degraded",
        "version": settings.VERSION,
        "database": db_status,
        "kafka_consumer": "running" if consumer_running else "stopped",
    }
