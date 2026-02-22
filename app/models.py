from datetime import datetime
from typing import Optional
from sqlmodel import Field, SQLModel


class Company(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    cnpj: str = Field(unique=True, index=True)
    razao_social: Optional[str] = None
    nome_fantasia: Optional[str] = None
    situacao: Optional[str] = None
    uf: Optional[str] = None
    municipio: Optional[str] = None
    atividade_principal: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class CompanyRead(SQLModel):
    id: int
    cnpj: str
    razao_social: Optional[str]
    nome_fantasia: Optional[str]
    situacao: Optional[str]
    uf: Optional[str]
    municipio: Optional[str]
    atividade_principal: Optional[str]
    created_at: datetime
    updated_at: datetime


class SemaforoResponse(SQLModel):
    cor: str
    mensagem: str
    situacao: str


class CompanyWithSemaforo(CompanyRead):
    semaforo: SemaforoResponse


class ListResponse(SQLModel):
    total: int
    page: int
    page_size: int
    items: list[CompanyWithSemaforo]
