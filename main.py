import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session, text

from app.database import engine, init_db
from app.routers.companies import router as companies_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("contador.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Inicializando banco de dados...")
    init_db()
    logger.info("Banco pronto.")
    yield


app = FastAPI(
    title="Contador MVP — Consulta CNPJ",
    description="Importa e persiste dados de empresas via CNPJ (BrasilAPI) com semáforo de situação cadastral.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_logger(request: Request, call_next):
    request_id = str(uuid.uuid4())[:8]
    request.state.request_id = request_id
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - start) * 1000)
    logger.info(
        f"[{request_id}] {request.method} {request.url.path} → {response.status_code} ({duration_ms}ms)"
    )
    response.headers["X-Request-ID"] = request_id
    return response


@app.get("/health", tags=["Sistema"])
def health():
    """Verifica se a API e o banco estão funcionando."""
    try:
        with Session(engine) as session:
            session.exec(text("SELECT 1"))  # type: ignore
        return {"status": "ok", "database": "ok"}
    except Exception as e:
        logger.error(f"Health check falhou: {e}")
        return {"status": "degraded", "database": "error"}


app.include_router(companies_router, prefix="/api")
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/", include_in_schema=False)
def root():
    return FileResponse("static/index.html")
