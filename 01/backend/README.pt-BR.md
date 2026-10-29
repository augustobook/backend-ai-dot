# Library API

> 🇺🇸 Read in English: [README.md](README.md)

API REST de uma biblioteca virtual, feita com **FastAPI**. Permite cadastrar livros e buscá-los
por título e/ou autor, com busca parcial, sem diferenciar maiúsculas de minúsculas, e com
paginação.

## Stack

| Responsabilidade        | Ferramenta                                                   |
| ----------------------- | ------------------------------------------------------------ |
| Framework web           | [FastAPI](https://fastapi.tiangolo.com/) + Uvicorn           |
| Validação e schemas     | Pydantic v2                                                  |
| Configuração            | pydantic-settings (`.env` / variáveis de ambiente)           |
| Banco de dados          | SQLite via SQLAlchemy 2.0 (`Mapped` / `mapped_column`)       |
| Migrations              | Alembic (aplicadas na inicialização)                         |
| Gerenciador de pacotes  | [uv](https://docs.astral.sh/uv/)                             |
| Testes                  | pytest, pytest-cov, `TestClient` do FastAPI (httpx2)         |
| Qualidade               | ruff (lint + format), mypy (modo strict)                     |

## Arquitetura

O código é organizado em camadas, e cada camada conhece apenas a camada logo abaixo:

```
 Requisição HTTP
      │
      ▼
┌──────────────────────┐   app/api/routes/       Valida a entrada (Pydantic), chama o service
│  Routers (HTTP)      │                         e monta a resposta. Sem regra de negócio e
└──────────┬───────────┘                         sem acesso ao banco.
           │  Depends(get_book_service)
           ▼
┌──────────────────────┐   app/services/         Casos de uso (create_book, get_book,
│  Services (regras)   │                         search_books). Aplica as regras e lança
└──────────┬───────────┘                         exceções de domínio. Não conhece HTTP.
           │  BookRepositoryProtocol
           ▼
┌──────────────────────┐   app/repositories/     Único lugar que monta queries SQLAlchemy
│  Repositories (dados)│                         (add, get_by_id, search).
└──────────┬───────────┘
           │  Session (Depends(get_db))
           ▼
┌──────────────────────┐   app/models/, app/db/  Modelos ORM, engine e sessões.
│  Banco (SQLite)      │
└──────────────────────┘
```

Peças de apoio:

- **Injeção de dependência:** a cadeia `get_db` → `get_book_repository` → `get_book_service`
  fica em `app/api/dependencies.py`. O `get_db` abre a sessão pela fábrica guardada em
  `app.state`, então os testes só passam outra engine para `create_app`.
- **Exceções de domínio:** ficam em `app/core/exceptions.py`. Um handler registrado em
  `app/main.py` converte `BookNotFoundError` em `404 {"detail": "Book with id 42 not found"}`.
- **Configuração:** a classe `Settings` em `app/core/config.py`.
- **Logging:** `app/core/logging.py`, com o módulo `logging` padrão. Registra livro criado e
  livro não encontrado.
- **Factory da aplicação:** `create_app(settings, db_engine)` em `app/main.py` monta a app
  (engine, lifespan, middleware de segurança, routers e handlers). Nada é criado na importação:
  a engine, a fábrica de sessões e o router de `/books` saem das settings recebidas. Assim, uma
  app criada com outras settings (como nos testes) segue os próprios limites de paginação e
  nunca abre o banco padrão.
- **Migrations:** o schema é definido pelas migrations do Alembic em `app/db/migrations/`, e o
  `lifespan` aplica as pendentes na inicialização. Veja [Migrations](#migrations).
- **Camada de segurança:** `app/api/middleware.py` (limite de tamanho do corpo, rate limit e
  headers de segurança) e `require_api_key` em `app/api/dependencies.py`, ligados por
  `configure_security()` em `app/main.py`. Veja [Segurança](#segurança).
- **Datas em UTC:** o SQLite não guarda fuso horário. O tipo `UTCDateTime` (`app/db/types.py`)
  converte para UTC ao gravar e devolve a data com timezone na leitura.

### Por que camadas?

- **Separação de responsabilidades:** detalhes de HTTP, regras de negócio e SQL ficam cada um
  em um lugar. Uma mudança em um deles raramente afeta os outros.
- **Testabilidade:** o service depende do `BookRepositoryProtocol` (um `typing.Protocol`), e não
  do SQLAlchemy. Por isso suas regras são testadas com um repositório falso em memória, sem banco.
- **Substituição:** trocar o banco ou adicionar outra forma de acesso (CLI, fila) mexe só no
  repository ou no router.

## Estrutura do projeto

```
backend/
├── app/
│   ├── main.py                    # create_app(): settings, lifespan, segurança, routers, handlers
│   ├── core/
│   │   ├── config.py              # Settings (pydantic-settings)
│   │   ├── exceptions.py          # Exceções de domínio (BookNotFoundError)
│   │   └── logging.py             # Configuração de logging
│   ├── db/
│   │   ├── base.py                # DeclarativeBase
│   │   ├── session.py             # create_db_engine, create_session_factory, get_db
│   │   ├── migrate.py             # migrate_db: aplica as migrations do Alembic
│   │   ├── migrations/            # env.py do Alembic + versions/ (0001_create_books)
│   │   └── types.py               # Tipo de coluna UTCDateTime
│   ├── models/book.py             # Modelo ORM Book
│   ├── schemas/
│   │   ├── book.py                # BookCreate, BookRead
│   │   └── common.py              # ErrorResponse, HealthResponse
│   ├── repositories/
│   │   └── book_repository.py     # BookRepositoryProtocol + BookRepository
│   ├── services/
│   │   └── book_service.py        # BookService (regras de negócio)
│   └── api/
│       ├── dependencies.py        # get_book_repository, get_book_service, require_api_key
│       ├── middleware.py          # Limite de corpo, rate limit, headers de segurança
│       └── routes/
│           ├── books.py           # Endpoints /books
│           └── health.py          # GET /health
├── tests/
│   ├── conftest.py                # Banco SQLite em memória isolado por teste, TestClient
│   ├── factories.py               # make_book_payload(...), make_book(...)
│   ├── unit/                      # BookService com repositório falso, infraestrutura
│   ├── integration/               # BookRepository contra SQLite em memória, migrations
│   └── api/                       # Endpoints de ponta a ponta e camada de segurança
├── postman/                       # Collection do Postman + environment local (veja abaixo)
├── .env.example                   # Todas as configurações com seus padrões
├── .python-version                # Python 3.12
├── Dockerfile                     # Imagem multi-stage com uv, usuário não-root
├── pyproject.toml                 # Metadados, dependências e config de ruff/mypy/pytest/coverage
└── uv.lock
```

## Variáveis de ambiente

Todas têm valor padrão e podem ser sobrescritas por variáveis de ambiente ou por um arquivo
`.env`. Para personalizar, copie o [`.env.example`](.env.example) para `.env`.

| Variável                      | Padrão                                        | Descrição                                                   |
| ----------------------------- | --------------------------------------------- | ----------------------------------------------------------- |
| `APP_NAME`                    | `Library API`                                 | Nome exibido na documentação OpenAPI                        |
| `APP_VERSION`                 | `0.1.0`                                       | Versão exibida na documentação OpenAPI                      |
| `LOG_LEVEL`                   | `INFO`                                        | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`             |
| **Banco de dados**            |                                               |                                                             |
| `DATABASE_URL`                | `sqlite:///./library.db`                      | URL do banco para o SQLAlchemy                              |
| `DB_POOL_SIZE`                | `5`                                           | Conexões mantidas abertas no pool                           |
| `DB_MAX_OVERFLOW`             | `5`                                           | Conexões extras permitidas em picos                         |
| `DB_POOL_TIMEOUT_SECONDS`     | `10`                                          | Espera por uma conexão livre antes de falhar                |
| `DB_POOL_RECYCLE_SECONDS`     | `1800`                                        | Substitui conexões mais velhas que isso (`-1` = nunca)      |
| `SQLITE_BUSY_TIMEOUT_SECONDS` | `5`                                           | Espera por um lock do SQLite antes de falhar                |
| **Paginação**                 |                                               |                                                             |
| `DEFAULT_PAGE_SIZE`           | `20`                                          | `limit` usado quando não é informado                        |
| `MAX_PAGE_SIZE`               | `100`                                         | Maior `limit` aceito                                        |
| **Segurança HTTP**            |                                               |                                                             |
| `CORS_ORIGINS`                | `http://localhost:8050,http://127.0.0.1:8050` | Origens de navegador que podem chamar a API (separadas por vírgula) |
| `ALLOWED_HOSTS`               | `localhost,127.0.0.1,api`                     | Valores aceitos no header `Host` (separados por vírgula; `*` = qualquer) |
| `API_KEY`                     | (vazio = desligado)                           | Se definido, `/books` exige `X-API-Key: <valor>`            |
| `ENABLE_DOCS`                 | `true`                                        | Serve `/docs`, `/redoc` e `/openapi.json`                   |
| `DOCS_SHOW_API_KEY`           | `false`                                       | Mostra a `API_KEY` no topo do `/docs` (só para demonstrações públicas) |
| `MAX_REQUEST_BODY_BYTES`      | `65536`                                       | Maior corpo de requisição aceito (acima disso, 413)         |
| `RATE_LIMIT_REQUESTS`         | `300`                                         | Requisições por IP por janela (`0` desliga)                 |
| `RATE_LIMIT_WINDOW_SECONDS`   | `60`                                          | Duração da janela do rate limit                             |

## Segurança

A API não tem contas de usuário, mas está protegida contra os riscos comuns de um serviço HTTP
público. Tudo abaixo é configurável pelas variáveis acima e coberto por
`tests/api/test_security.py`.

### Controle de acesso

- **Chave de API opcional.** Com `API_KEY` definida, toda requisição a `/books` precisa enviar o
  header `X-API-Key: <valor>`; caso contrário, a API responde
  `401 {"detail": "Invalid or missing API key"}`. A comparação é feita em tempo constante
  (`secrets.compare_digest`), então a chave não pode ser descoberta pelo tempo de resposta. O
  `/health` continua público para os health checks. Sem chave configurada, a API registra um
  aviso no log ao iniciar. O Swagger UI mostra um botão **Authorize** para enviar a chave. O
  frontend envia o mesmo valor, lido da sua própria variável `API_KEY`.
- **Origens (CORS).** Só as origens em `CORS_ORIGINS` podem chamar a API a partir de um
  navegador, e apenas com `GET`/`POST` e os headers `Content-Type` e `X-API-Key`, sem
  credenciais. O frontend em Dash chama a API pelo servidor (e não pelo navegador), então o CORS
  só importa para outros clientes web.
- **Hosts confiáveis.** Requisições com header `Host` fora de `ALLOWED_HOSTS` recebem `400`, o
  que bloqueia ataques de Host header e DNS rebinding.

### Limites

| Limite                        | Onde                                   | Comportamento ao ultrapassar                                   |
| ----------------------------- | -------------------------------------- | -------------------------------------------------------------- |
| Requisições por IP            | `RATE_LIMIT_*`                         | `429` com `Retry-After`; headers `X-RateLimit-*` em toda resposta |
| Tamanho do corpo              | `MAX_REQUEST_BODY_BYTES`               | `413`, inclusive para corpos chunked sem `Content-Length`      |
| Tamanho dos textos            | Schemas                                | `title`/`author` ≤ 255 caracteres, `summary` ≤ 5000 → `422`    |
| Tamanho da página             | `MAX_PAGE_SIZE`                        | `422`                                                          |
| Conexões com o banco          | `DB_POOL_SIZE` + `DB_MAX_OVERFLOW`     | A requisição espera até `DB_POOL_TIMEOUT_SECONDS`              |
| Conexões HTTP simultâneas     | `--limit-concurrency 100` (Dockerfile) | `503` acima de 100 conexões simultâneas                        |
| Keep-alive ocioso             | `--timeout-keep-alive 5` (Dockerfile)  | Conexões ociosas são fechadas após 5 s                         |

O rate limiter guarda os contadores em memória, por processo: eles zeram ao reiniciar e não são
compartilhados entre workers. Com vários workers ou servidores, aplique o limite numa camada
compartilhada (reverse proxy, API gateway ou Redis). Atrás de um proxy, rode o uvicorn com
`--proxy-headers` e `--forwarded-allow-ips` para usar o IP real do cliente. Atenção: todos os
usuários do frontend chegam à API pelo IP do servidor do frontend, então compartilham o mesmo
limite.

### Proteção dos dados

- **Sem mass assignment.** O `BookCreate` rejeita campos desconhecidos (`422 extra_forbidden`),
  então o cliente não consegue definir valores controlados pelo servidor, como o `id`.
- **Sem SQL injection.** Todas as queries passam pelo SQLAlchemy com parâmetros vinculados; `%`
  e `_` digitados pelo usuário são escapados nas buscas com `LIKE`.
- **Integridade.** O SQLite roda com `foreign_keys=ON`, journal WAL (leituras não são
  bloqueadas por escritas) e busy timeout; o `pool_pre_ping` descarta conexões mortas.
- **Sem vazamento de informação.** Erros inesperados retornam
  `500 {"detail": "Internal server error"}`; o stack trace vai só para o log do servidor. A
  imagem Docker não envia o header `server`.
- **Segredos.** A `API_KEY` é guardada como `SecretStr` (mascarada em logs e reprs). Mantenha os
  valores reais no `.env` (ignorado pelo git) ou no ambiente, nunca no código.
- **Container.** A imagem roda com usuário não-root, e o banco fica num volume dedicado.

### Headers de resposta

Toda resposta traz `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
`Referrer-Policy: no-referrer`, `Permissions-Policy` e `Cross-Origin-Resource-Policy`. Os
endpoints JSON também recebem `Content-Security-Policy: default-src 'none'; frame-ancestors
'none'` (a página `/docs` fica de fora porque carrega o Swagger UI de uma CDN).

### Checklist para produção

1. Defina uma `API_KEY` forte (`python -c "import secrets; print(secrets.token_urlsafe(32))"`)
   e o mesmo valor no frontend.
2. Restrinja `ALLOWED_HOSTS` e `CORS_ORIGINS` aos domínios reais.
3. Use `ENABLE_DOCS=false` se a superfície da API não deve ser pública.
4. Sirva por HTTPS (TLS num reverse proxy) e ative o HSTS lá.
5. Ajuste `RATE_LIMIT_*`, `MAX_REQUEST_BODY_BYTES` e o pool do banco à carga esperada.
6. Faça backup do volume `library-data` (ou migre para um banco gerenciado via `DATABASE_URL`).

Fora do escopo deste projeto: contas de usuário e permissões por usuário, terminação TLS e log
de auditoria.

## Como rodar

### Pré-requisito

Instale o **uv**: veja o [guia oficial de instalação](https://docs.astral.sh/uv/getting-started/installation/).
O uv baixa automaticamente o Python fixado em `.python-version` (3.12), se necessário.

### 1. Instalar as dependências

Dentro da pasta `backend/`:

```bash
uv sync
```

### 2. Subir a API

```bash
uv run uvicorn app.main:app --reload
```

- Swagger UI: <http://127.0.0.1:8000/docs>
- ReDoc: <http://127.0.0.1:8000/redoc>
- Health check: <http://127.0.0.1:8000/health>

O banco `library.db` é criado automaticamente na primeira execução.

### 3. (Opcional) Subir com a interface

O frontend fica em [`../frontend`](../frontend/README.pt-BR.md). Com a API rodando, abra outro
terminal na pasta `frontend/` e execute `uv run python -m library_ui.app`. Depois, acesse
<http://localhost:8050>.

### Com Docker (opcional)

O `Dockerfile` gera uma imagem multi-stage com uv, rodando com usuário não-root. Se tiver o
Docker ligado, o `docker-compose.yml` da pasta acima sobe a API e o frontend juntos:

```bash
cd ..
docker compose up --build
```

Documentação da API em <http://localhost:8000/docs> e frontend em <http://localhost:8050>.

## Testes e qualidade

```bash
uv run pytest -v --cov=app   # testes com cobertura (mínimo exigido: 90%)
uv run ruff check .          # lint
uv run ruff format .         # formatação
uv run mypy app              # checagem de tipos
```

Os testes usam um SQLite em memória novo a cada teste, criado pelas próprias migrations, e
nunca tocam no `library.db`. O mínimo de 90% de cobertura é exigido pelo `pyproject.toml`.

## Migrations

O schema do banco é versionado com [Alembic](https://alembic.sqlalchemy.org/). As migrations
ficam em `app/db/migrations/versions/` e a API aplica as pendentes sozinha ao iniciar
(`migrate_db`, chamado no `lifespan`), então subir uma versão nova já atualiza o banco.

**Por que não `create_all`:** o `Base.metadata.create_all` só cria tabelas que não existem e
nunca altera uma existente. Uma coluna ou índice novo nunca chegaria a um banco que já tem
livros. Com migrations, cada mudança de schema vira um passo versionado e reversível.

**Bancos antigos:** um `library.db` criado antes do Alembic já tem a tabela `books`, mas não a
tabela `alembic_version`. Nesse caso, o `migrate_db` marca o banco como estando na migration
inicial (`0001`) antes de aplicar as seguintes, então os livros cadastrados são mantidos.

Para mudar o schema:

```bash
# 1. altere o modelo em app/models/ e gere a migration comparando modelo x banco
uv run alembic revision --autogenerate -m "add isbn to books"
# 2. revise o arquivo gerado em app/db/migrations/versions/ e aplique
uv run alembic upgrade head
# conferir se modelos e migrations estão em sincronia
uv run alembic check
```

O teste `tests/integration/test_migrations.py` falha se um modelo mudar sem a migration
correspondente.

## Adicionando dependências

```bash
uv add <pacote>          # produção -> [project.dependencies]
uv add --dev <pacote>    # desenvolvimento -> [dependency-groups].dev
```

Versione o `pyproject.toml` e o `uv.lock` atualizados.

## Collection do Postman

A pasta [`postman/`](postman) tem uma collection pronta para importar, com todas as requisições
da API (45 requisições em 7 pastas, cada uma com testes automáticos):

| Pasta                           | O que cobre                                                             |
| ------------------------------- | ----------------------------------------------------------------------- |
| 1. Health & docs                | `/health`, `/openapi.json`, `/docs`                                     |
| 2. Register books               | `POST /books` com sucesso (com e sem `created_at`, fusos horários)      |
| 3. Validation errors (422)      | Campos ausentes ou vazios, datas inválidas ou futuras, campo extra, resumo longo |
| 4. Search books                 | Título, autor, os dois juntos, paginação, sem resultados, parâmetros inválidos |
| 5. Get book by id               | Encontrado, 404, ids inválidos                                          |
| 6. Edit & delete                | `PATCH` (parcial, UTC, 422, 404) e `DELETE` (204 e 404) — além do pedido na prova |
| 7. Security                     | Chave ausente ou errada (401), corpo grande demais (413), CORS, header Host, headers de segurança |

1. No Postman, use **Import** em `postman/library-api.postman_collection.json` e
   `postman/library-api.local.postman_environment.json`.
2. Selecione o environment **Library API - local**. Se o `.env` define `API_KEY`, cole o mesmo
   valor na variável `apiKey` do environment (ela é secreta e vem vazia no arquivo).
3. Rode a pasta 2 antes das pastas 4, 5 e 6: elas precisam de dados e do `bookId` salvo pela
   primeira requisição de cadastro.

Também dá para rodar a collection inteira pelo terminal com o
[Newman](https://www.npmjs.com/package/newman), o executor de linha de comando do Postman:

```bash
npx newman run postman/library-api.postman_collection.json \
  -e postman/library-api.local.postman_environment.json --env-var "apiKey=<sua API key>"
```

## Endpoints

| Método | Rota               | Descrição                                       | Sucesso | Erros    |
| ------ | ------------------ | ----------------------------------------------- | ------- | -------- |
| POST   | `/books`           | Cadastra um livro                               | 201     | 413, 422 |
| GET    | `/books`           | Busca por `title` / `author`, com `skip`/`limit` | 200     | 422      |
| GET    | `/books/{book_id}` | Busca um livro por ID                           | 200     | 404, 422 |
| PATCH  | `/books/{book_id}` | Edita um livro (só os campos enviados)          | 200     | 404, 413, 422 |
| DELETE | `/books/{book_id}` | Exclui um livro                                 | 204     | 404, 422 |
| GET    | `/health`          | Health check (público, sem rate limit)          | 200     | —        |

Todo endpoint de `/books` também pode retornar `401` (com `API_KEY` definida) e `429` (rate
limit). Com chave configurada, adicione `-H "X-API-Key: <valor>"` aos exemplos de `curl` abaixo.

### Paginação

`GET /books` devolve uma página (`skip` e `limit`, ordenada por `id`) e informa no header
**`X-Total-Count`** quantos livros atendem aos filtros no total, ignorando a paginação. Com isso
o cliente sabe quantas páginas existem sem precisar buscar todas.

O total vai num header, e não num envelope como `{"items": [...], "total": 42}`, para que o
corpo continue sendo uma lista de livros: os clientes existentes (o frontend e a collection do
Postman) seguem funcionando sem mudança. O header é exposto via CORS
(`Access-Control-Expose-Headers`), então scripts no navegador também conseguem lê-lo.

### Campos do livro

| Campo              | Tipo                | Regras                                                                  |
| ------------------ | ------------------- | ----------------------------------------------------------------------- |
| `id`               | inteiro             | Gerado pelo banco                                                       |
| `title`            | string              | Obrigatório, não vazio, máx. 255 caracteres                             |
| `author`           | string              | Obrigatório, não vazio, máx. 255 caracteres                             |
| `publication_date` | data (`YYYY-MM-DD`) | Obrigatório, não pode estar no futuro                                   |
| `summary`          | string              | Texto livre opcional, máx. 5000 caracteres (padrão `""`)                |
| `created_at`       | datetime (ISO 8601) | Opcional, não pode estar no futuro. Se omitido, usa a data/hora atual. Sempre em UTC |

### Exemplos com `curl`

**Cadastrar um livro**

```bash
curl -X POST http://127.0.0.1:8000/books \
  -H "Content-Type: application/json" \
  -d '{"title": "Dune", "author": "Frank Herbert", "publication_date": "1965-08-01",
       "summary": "Spice must flow.", "created_at": "2024-05-10T11:30:00-03:00"}'
```

```json
{
  "title": "Dune",
  "author": "Frank Herbert",
  "publication_date": "1965-08-01",
  "summary": "Spice must flow.",
  "id": 1,
  "created_at": "2024-05-10T14:30:00Z"
}
```

Repare que o `created_at` enviado em `-03:00` é devolvido convertido para UTC.

**Erro de validação** (`422`)

```bash
curl -X POST http://127.0.0.1:8000/books \
  -H "Content-Type: application/json" \
  -d '{"title": "", "author": "Someone", "publication_date": "2999-01-01"}'
```

A resposta traz um item em `detail` por campo inválido, por exemplo
`{"loc": ["body", "publication_date"], "msg": "Value error, publication_date cannot be in the future", ...}`.

**Buscar por título** (parcial, sem diferenciar maiúsculas/minúsculas)

```bash
curl "http://127.0.0.1:8000/books?title=dun"
```

**Buscar por título e autor, com paginação**

```bash
curl -i "http://127.0.0.1:8000/books?title=dune&author=herbert&skip=0&limit=10"
# x-total-count: 1   <- total de livros com esses filtros, em todas as páginas
```

**Buscar por ID**

```bash
curl http://127.0.0.1:8000/books/1
```

**Livro inexistente** (`404`)

```bash
curl http://127.0.0.1:8000/books/42
# {"detail": "Book with id 42 not found"}
```

**Health check**

```bash
curl http://127.0.0.1:8000/health
# {"status": "ok"}
```
