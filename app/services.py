import asyncio
import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

import httpx
from sqlmodel import Session, select

from app.models import Company

logger = logging.getLogger("contador.services")

BRASILAPI_URL = "https://brasilapi.com.br/api/cnpj/v1/{cnpj}"
HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT_SECONDS", "12"))
HTTP_RETRY_MAX = int(os.getenv("HTTP_RETRY_MAX", "2"))
UPDATE_TTL_HOURS = int(os.getenv("UPDATE_TTL_HOURS", "24"))
RETRY_STATUSES = {408, 500, 502, 503, 504}  # 429 NAO entra aqui
BACKOFF_DELAYS = [0.5, 1.5]

FALLBACK_FILE = Path(__file__).parent.parent / "fallback_companies.json"
_fallback_cache: dict | None = None


def _load_fallback() -> dict:
    global _fallback_cache
    if _fallback_cache is None:
        try:
            _fallback_cache = json.loads(FALLBACK_FILE.read_text(encoding="utf-8"))
            logger.info(f"Fallback local carregado: {len(_fallback_cache)} empresas.")
        except Exception as e:
            logger.warning(f"Nao foi possivel carregar fallback_companies.json: {e}")
            _fallback_cache = {}
    return _fallback_cache


def _is_stale(company: Company) -> bool:
    threshold = datetime.utcnow() - timedelta(hours=UPDATE_TTL_HOURS)
    return company.updated_at < threshold


async def _fetch_from_brasilapi(cnpj: str) -> dict:
    url = BRASILAPI_URL.format(cnpj=cnpj)
    last_exc: Exception | None = None

    for attempt in range(HTTP_RETRY_MAX + 1):
        if attempt > 0:
            delay = BACKOFF_DELAYS[min(attempt - 1, len(BACKOFF_DELAYS) - 1)]
            logger.info(f"Retry {attempt} para CNPJ {cnpj}, aguardando {delay}s...")
            await asyncio.sleep(delay)

        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                logger.info(f"BrasilAPI: consultando CNPJ {cnpj} (tentativa {attempt + 1})")
                resp = await client.get(url)
                logger.info(f"BrasilAPI: HTTP {resp.status_code} para CNPJ {cnpj}")

                if resp.status_code == 200:
                    return resp.json()

                if resp.status_code == 404:
                    raise CNPJNotFoundError(f"CNPJ {cnpj} nao encontrado na fonte publica.")

                # 429: SEM retry, lanca imediatamente
                if resp.status_code == 429:
                    raise RateLimitError("Fonte publica limitou requisicoes.")

                # Erros transitorios: retry
                if resp.status_code in RETRY_STATUSES and attempt < HTTP_RETRY_MAX:
                    last_exc = ExternalServiceError(f"HTTP {resp.status_code}")
                    continue

                raise ExternalServiceError(f"Erro externo: HTTP {resp.status_code}")

        except (httpx.TimeoutException, httpx.ConnectError) as e:
            last_exc = ExternalTimeoutError(f"Timeout: {e}")
            logger.warning(f"Timeout/conexao falhou para CNPJ {cnpj}: {e}")
            if attempt < HTTP_RETRY_MAX:
                continue
            raise last_exc

    raise last_exc or ExternalServiceError("Falha apos todas as tentativas.")


def _map_to_fields(data: dict, cnpj: str) -> dict:
    atividade = data.get("cnae_fiscal_descricao") or ""
    if not atividade and data.get("cnaes_secundarios"):
        atividade = data["cnaes_secundarios"][0].get("descricao", "")
    return {
        "cnpj": cnpj,
        "razao_social": data.get("razao_social"),
        "nome_fantasia": data.get("nome_fantasia") or None,
        "situacao": (
            data.get("descricao_situacao_cadastral") or data.get("situacao_cadastral") or ""
        ).upper() or None,
        "uf": data.get("uf"),
        "municipio": data.get("municipio"),
        "atividade_principal": atividade or None,
    }


def _upsert(cnpj: str, fields: dict, existing: Company | None, session: Session) -> Company:
    if existing:
        for k, v in fields.items():
            if k != "cnpj":
                setattr(existing, k, v)
        existing.updated_at = datetime.utcnow()
        session.add(existing)
        session.commit()
        session.refresh(existing)
        return existing
    company = Company(**fields)
    session.add(company)
    session.commit()
    session.refresh(company)
    return company


class ImportResult:
    __slots__ = ("company", "source")

    def __init__(self, company: Company, source: str):
        self.company = company
        self.source = source  # brasilapi | cache_local | fallback_local


async def import_company(cnpj: str, force: bool, session: Session) -> ImportResult:
    existing = session.exec(select(Company).where(Company.cnpj == cnpj)).first()

    # Cache local-first
    if existing and not force:
        logger.info(f"CNPJ {cnpj}: cache local (force=false).")
        return ImportResult(existing, "cache_local")

    try:
        data = await _fetch_from_brasilapi(cnpj)
        fields = _map_to_fields(data, cnpj)
        company = _upsert(cnpj, fields, existing, session)
        logger.info(f"CNPJ {cnpj}: salvo via BrasilAPI.")
        return ImportResult(company, "brasilapi")

    except RateLimitError:
        logger.warning(f"CNPJ {cnpj}: 429 da BrasilAPI.")
        return _handle_failure(cnpj, existing, session, exc_type=RateLimitError)

    except CNPJNotFoundError:
        raise

    except (ExternalServiceError, ExternalTimeoutError) as exc:
        logger.warning(f"CNPJ {cnpj}: falha externa ({exc}).")
        return _handle_failure(cnpj, existing, session, exc_type=type(exc), original=exc)


def _handle_failure(cnpj, existing, session, exc_type, original=None) -> ImportResult:
    if existing:
        logger.info(f"CNPJ {cnpj}: retornando cache local apos falha.")
        return ImportResult(existing, "cache_local")

    fallback_data = _load_fallback().get(cnpj)
    if fallback_data:
        logger.info(f"CNPJ {cnpj}: encontrado no fallback_companies.json.")
        fields = _map_to_fields(fallback_data, cnpj)
        company = _upsert(cnpj, fields, None, session)
        return ImportResult(company, "fallback_local")

    if original:
        raise original
    raise exc_type("Falha externa sem cache disponivel.")


# ─── Excecoes de dominio ─────────────────────────────────────────────────────

class CNPJNotFoundError(Exception):
    pass

class RateLimitError(Exception):
    pass

class ExternalServiceError(Exception):
    pass

class ExternalTimeoutError(Exception):
    pass


# ─── Dev Seed ────────────────────────────────────────────────────────────────

DEV_SEED = [
    {
        "cnpj": "33000167000101",
        "razao_social": "PETROLEO BRASILEIRO S.A. PETROBRAS",
        "nome_fantasia": "PETROBRAS",
        "situacao": "ATIVA",
        "uf": "RJ",
        "municipio": "RIO DE JANEIRO",
        "atividade_principal": "Extracao de petroleo e gas natural",
    },
    {
        "cnpj": "60746948000112",
        "razao_social": "BANCO BRADESCO S.A.",
        "nome_fantasia": "BRADESCO",
        "situacao": "ATIVA",
        "uf": "SP",
        "municipio": "OSASCO",
        "atividade_principal": "Banco multiplo, com carteira comercial",
    },
    {
        "cnpj": "47960950000121",
        "razao_social": "MAGAZINE LUIZA S.A.",
        "nome_fantasia": "MAGALU",
        "situacao": "ATIVA",
        "uf": "SP",
        "municipio": "FRANCA",
        "atividade_principal": "Comercio varejista de eletrodomesticos",
    },
]


def seed_dev_data(session: Session) -> list[Company]:
    results = []
    for fields in DEV_SEED:
        existing = session.exec(select(Company).where(Company.cnpj == fields["cnpj"])).first()
        if not existing:
            company = Company(**fields)
            session.add(company)
            session.commit()
            session.refresh(company)
            results.append(company)
            logger.info(f"Seed: inseriu {fields['cnpj']}")
        else:
            results.append(existing)
    return results
