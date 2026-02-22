# Contador MVP — Consulta CNPJ

API + interface web para importar e consultar dados de empresas via CNPJ, com persistência em SQLite e semáforo de situação cadastral.

---

## Estrutura do projeto

```
contador-mvp/
├── main.py                   # App FastAPI (entry point)
├── requirements.txt
├── static/
│   └── index.html            # Interface web
└── app/
    ├── database.py           # Sessão e init do SQLite
    ├── models.py             # Tabela Company + schemas
    ├── rules.py              # Validação CNPJ + semáforo
    ├── services.py           # BrasilAPI + retry/backoff/fallback
    └── routers/
        └── companies.py      # Todos os endpoints
```

---

## Rodando localmente

### 1. Criar e ativar ambiente virtual

```bash
python -m venv venv

# Linux/Mac:
source venv/bin/activate

# Windows:
venv\Scripts\activate
```

### 2. Instalar dependências

```bash
pip install -r requirements.txt
```

### 3. Subir o servidor

```bash
uvicorn main:app --reload --port 8000
```

### 4. Acessar

| URL | O quê |
|-----|-------|
| http://localhost:8000 | Interface web |
| http://localhost:8000/docs | Swagger / testes interativos |
| http://localhost:8000/health | Health check |

---

## Variáveis de ambiente (opcionais)

| Variável | Padrão | Descrição |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./database.db` | URL do banco |
| `HTTP_TIMEOUT_SECONDS` | `12` | Timeout para BrasilAPI |
| `HTTP_RETRY_MAX` | `2` | Máximo de retries |

---

## Endpoints principais

| Método | Rota | Descrição |
|--------|------|-----------|
| `POST` | `/api/companies/import?cnpj=X&force=false` | Importa empresa |
| `GET` | `/api/companies` | Lista com filtros e paginação |
| `GET` | `/api/companies/{id}` | Busca por ID |
| `GET` | `/api/companies/by-cnpj/{cnpj}` | Busca por CNPJ |
| `GET` | `/api/companies/{id}/semaforo` | Semáforo de uma empresa |
| `GET` | `/health` | Health check |

### Filtros da listagem

```
GET /api/companies?q=nome&uf=SP&situacao=ATIVA&page=1&page_size=20
```

---

## Semáforo

| Cor | Situações |
|-----|-----------|
| 🟢 Verde | ATIVA |
| 🔴 Vermelho | INAPTA, SUSPENSA, BAIXADA, NULA |
| 🟡 Amarelo | Qualquer outra / desconhecida |

---

## Comportamento de fallback

| Cenário | Comportamento |
|---------|---------------|
| Empresa existe + `force=false` | Retorna do banco local (sem chamar API externa) |
| API externa retorna 5xx/timeout + empresa no banco | Retorna dado local |
| API externa retorna 429 + empresa no banco | Retorna dado local |
| API externa retorna 429 + sem banco | HTTP 429 |
| API externa retorna 5xx/timeout + sem banco | HTTP 502/504 |

---

## Deploy (Render/Railway/Fly.io)

Comando de start para produção (sem `--reload`):

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

Configurar variável `DATABASE_URL` para PostgreSQL em produção real.

---

## CNPJs para teste

| CNPJ | Empresa |
|------|---------|
| `11.222.333/0001-81` | — (inválido, para testar erro 400) |
| `33.000.167/0001-01` | Petrobras |
| `60.746.948/0001-12` | Bradesco |
| `00.000.000/0000-00` | — (inválido, todos iguais) |
