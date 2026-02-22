import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, func, select

from app.database import get_session
from app.models import Company, CompanyRead, CompanyWithSemaforo, ListResponse, SemaforoResponse
from app.rules import get_semaforo, normalize_cnpj, validate_cnpj
from app.services import (
    CNPJNotFoundError,
    ExternalServiceError,
    ExternalTimeoutError,
    RateLimitError,
    import_company,
    seed_dev_data,
)

router = APIRouter()
logger = logging.getLogger("contador.routes")

ENABLE_DEV_SEED = os.getenv("ENABLE_DEV_SEED", "false").lower() == "true"
APP_ENV = os.getenv("APP_ENV", "prod")


def _with_semaforo(company: Company, source: str | None = None) -> CompanyWithSemaforo:
    data = CompanyRead.model_validate(company).model_dump()
    result = CompanyWithSemaforo(**data, semaforo=get_semaforo(company.situacao))
    if source:
        result.__dict__["_source"] = source
    return result


def _import_response(company: Company, source: str) -> dict:
    base = _with_semaforo(company)
    return {**base.model_dump(), "source": source}


@router.post(
    "/companies/import",
    tags=["Empresas"],
    summary="Importa empresa pelo CNPJ (BrasilAPI → cache → fallback)",
)
async def import_cnpj(
    cnpj: str = Query(..., description="CNPJ com ou sem formatacao"),
    force: bool = Query(False, description="Forcar atualizacao mesmo se ja existe"),
    session: Session = Depends(get_session),
):
    """
    Importa empresa. Fluxo de prioridade:
    1. Cache local (se force=false)
    2. BrasilAPI
    3. Cache local (se BrasilAPI falhar)
    4. fallback_companies.json (se nem cache existir)

    O campo `source` indica a origem: `brasilapi` | `cache_local` | `fallback_local`.
    """
    clean = normalize_cnpj(cnpj)
    if not validate_cnpj(clean):
        raise HTTPException(status_code=400, detail="CNPJ invalido.")

    try:
        result = await import_company(clean, force, session)
        return _import_response(result.company, result.source)

    except CNPJNotFoundError:
        raise HTTPException(status_code=404, detail="CNPJ nao encontrado na fonte publica.")

    except RateLimitError:
        raise HTTPException(
            status_code=429,
            detail="Fonte publica limitou requisicoes. Tente novamente em alguns instantes.",
        )

    except ExternalTimeoutError:
        raise HTTPException(status_code=504, detail="Timeout ao consultar fonte publica.")

    except ExternalServiceError:
        raise HTTPException(status_code=502, detail="Falha ao consultar fonte publica.")

    except Exception:
        logger.exception(f"Erro inesperado ao importar CNPJ {cnpj}")
        raise HTTPException(status_code=500, detail="Erro interno do servidor.")


@router.get("/companies", response_model=ListResponse, tags=["Empresas"])
def list_companies(
    q: Optional[str] = Query(None),
    uf: Optional[str] = Query(None),
    situacao: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: Session = Depends(get_session),
):
    """Lista empresas com filtros e paginacao."""
    query = select(Company)

    if q:
        term = f"%{q.upper()}%"
        query = query.where(
            (func.upper(Company.razao_social).like(term))
            | (func.upper(Company.nome_fantasia).like(term))
        )
    if uf:
        query = query.where(func.upper(Company.uf) == uf.upper())
    if situacao:
        query = query.where(func.upper(Company.situacao) == situacao.upper())

    total = session.exec(select(func.count()).select_from(query.subquery())).one()
    query = query.order_by(Company.updated_at.desc())  # type: ignore
    query = query.offset((page - 1) * page_size).limit(page_size)

    companies = session.exec(query).all()
    return ListResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=[_with_semaforo(c) for c in companies],
    )


@router.get("/companies/by-cnpj/{cnpj}", response_model=CompanyWithSemaforo, tags=["Empresas"])
def get_by_cnpj(cnpj: str, session: Session = Depends(get_session)):
    clean = normalize_cnpj(cnpj)
    if not validate_cnpj(clean):
        raise HTTPException(status_code=400, detail="CNPJ invalido.")
    company = session.exec(select(Company).where(Company.cnpj == clean)).first()
    if not company:
        raise HTTPException(status_code=404, detail="Empresa nao encontrada no banco local.")
    return _with_semaforo(company)


@router.get("/companies/{company_id}", response_model=CompanyWithSemaforo, tags=["Empresas"])
def get_by_id(company_id: int, session: Session = Depends(get_session)):
    company = session.get(Company, company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Empresa nao encontrada.")
    return _with_semaforo(company)


@router.get("/companies/{company_id}/semaforo", response_model=SemaforoResponse, tags=["Semaforo"])
def semaforo(company_id: int, session: Session = Depends(get_session)):
    company = session.get(Company, company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Empresa nao encontrada.")
    return get_semaforo(company.situacao)


@router.post("/dev/seed", tags=["Dev"], include_in_schema=True)
def dev_seed(session: Session = Depends(get_session)):
    """
    Insere 3 empresas de exemplo no banco (apenas em APP_ENV=dev ou ENABLE_DEV_SEED=true).
    Util para testar sem internet ou sem BrasilAPI.
    """
    if APP_ENV != "dev" and not ENABLE_DEV_SEED:
        raise HTTPException(
            status_code=403,
            detail="Endpoint disponivel apenas em ambiente de desenvolvimento. "
                   "Defina APP_ENV=dev ou ENABLE_DEV_SEED=true.",
        )
    companies = seed_dev_data(session)
    return {
        "seeded": len(companies),
        "companies": [c.cnpj for c in companies],
    }
