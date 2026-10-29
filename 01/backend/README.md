# Library API

> 🇧🇷 Leia em português: [README.pt-BR.md](README.pt-BR.md)

A REST API for a virtual library, built with **FastAPI**. Users can register books and search
them by title and/or author, with partial, case-insensitive matching and pagination.

## Stack

| Concern              | Tool                                                         |
| -------------------- | ------------------------------------------------------------ |
| Web framework        | [FastAPI](https://fastapi.tiangolo.com/) + Uvicorn           |
| Validation & schemas | Pydantic v2                                                  |
| Configuration        | pydantic-settings (`.env` / environment variables)           |
| Database             | SQLite via SQLAlchemy 2.0 (`Mapped` / `mapped_column`)       |
| Package management   | [uv](https://docs.astral.sh/uv/)                             |
| Tests                | pytest, pytest-cov, FastAPI `TestClient` (httpx2)            |
| Quality              | ruff (lint + format), mypy (strict)                          |

## Architecture

The code is organized in layers. Each layer only knows the layer directly below it:

```
 HTTP request
      │
      ▼
┌──────────────────────┐   app/api/routes/       Parse & validate input (Pydantic), call the
│  Routers (HTTP)      │                         service, shape the response. No business
└──────────┬───────────┘                         rules, no database access.
           │  Depends(get_book_service)
           ▼
┌──────────────────────┐   app/services/         Use cases (create_book, get_book, search_books).
│  Services (rules)    │                         Applies business rules and raises domain
└──────────┬───────────┘                         exceptions (BookNotFoundError). No HTTP.
           │  BookRepositoryProtocol
           ▼
┌──────────────────────┐   app/repositories/     The only place that builds SQLAlchemy queries
│  Repositories (data) │                         (add, get_by_id, search).
└──────────┬───────────┘
           │  Session (Depends(get_db))
           ▼
┌──────────────────────┐   app/models/, app/db/  ORM models, engine and sessions.
│  Database (SQLite)   │
└──────────────────────┘
```

Supporting pieces:

- **Dependency injection** — `get_db` → `get_book_repository` → `get_book_service`, wired in
  `app/api/dependencies.py`. Tests replace `get_db` through `app.dependency_overrides`.
- **Domain exceptions** — `app/core/exceptions.py`. A handler registered in `app/main.py` turns
  `BookNotFoundError` into `404 {"detail": "Book with id 42 not found"}`.
- **Configuration** — `Settings` in `app/core/config.py`.
- **Logging** — `app/core/logging.py`, standard `logging` module (book created / not found).
- **Application factory** — `create_app()` in `app/main.py` builds the app (settings, lifespan,
  security middleware, routers, handlers). Tables are created on startup through `lifespan`.
- **Security layer** — `app/api/middleware.py` (body size limit, rate limit, security headers)
  and `require_api_key` in `app/api/dependencies.py`, wired by `configure_security()` in
  `app/main.py`. See [Security](#security).
- **UTC datetimes** — SQLite does not store timezones. The `UTCDateTime` type
  (`app/db/types.py`) converts to UTC on write and returns timezone-aware values on read.

### Why layers?

- **Separation of concerns**: HTTP details, business rules and SQL each live in one place, so a
  change in one rarely ripples into the others.
- **Testability**: the service depends on `BookRepositoryProtocol` (a `typing.Protocol`), not on
  SQLAlchemy, so its rules are tested with an in-memory fake repository — no database needed.
- **Replaceability**: switching the database or adding another transport (CLI, queue consumer)
  only touches the repository or the router layer.

## Project structure

```
backend/
├── app/
│   ├── main.py                    # create_app(): settings, lifespan, security, routers, handlers
│   ├── core/
│   │   ├── config.py              # Settings (pydantic-settings)
│   │   ├── exceptions.py          # Domain exceptions (BookNotFoundError)
│   │   └── logging.py             # Logging configuration
│   ├── db/
│   │   ├── base.py                # DeclarativeBase
│   │   ├── session.py             # Engine, SessionLocal, get_db, init_db
│   │   └── types.py               # UTCDateTime column type
│   ├── models/book.py             # ORM model Book
│   ├── schemas/
│   │   ├── book.py                # BookCreate, BookRead
│   │   └── common.py              # ErrorResponse, HealthResponse
│   ├── repositories/
│   │   └── book_repository.py     # BookRepositoryProtocol + BookRepository
│   ├── services/
│   │   └── book_service.py        # BookService (business rules)
│   └── api/
│       ├── dependencies.py        # get_book_repository, get_book_service, require_api_key
│       ├── middleware.py          # Body size limit, rate limit, security headers
│       └── routes/
│           ├── books.py           # /books endpoints
│           └── health.py          # GET /health
├── tests/
│   ├── conftest.py                # Isolated in-memory DB per test, TestClient
│   ├── factories.py               # make_book_payload(...), make_book(...)
│   ├── unit/                      # BookService with a fake repository, infrastructure
│   ├── integration/               # BookRepository against in-memory SQLite
│   └── api/                       # Endpoints end to end, security layer
├── postman/                       # Postman collection + local environment (see below)
├── .env.example                   # Every setting with its default
├── .python-version                # Python 3.12
├── Dockerfile                     # Multi-stage image with uv, non-root user
├── pyproject.toml                 # Metadata, dependencies, ruff/mypy/pytest/coverage config
└── uv.lock
```

## Environment variables

All settings have defaults and can be overridden by environment variables or a `.env` file.
Copy [`.env.example`](.env.example) to `.env` to customize them.

| Variable                      | Default                                       | Description                                              |
| ----------------------------- | --------------------------------------------- | -------------------------------------------------------- |
| `APP_NAME`                    | `Library API`                                 | Name shown in the OpenAPI docs                           |
| `APP_VERSION`                 | `0.1.0`                                       | Version shown in the OpenAPI docs                        |
| `LOG_LEVEL`                   | `INFO`                                        | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`          |
| **Database**                  |                                               |                                                          |
| `DATABASE_URL`                | `sqlite:///./library.db`                      | SQLAlchemy database URL                                  |
| `DB_POOL_SIZE`                | `5`                                           | Connections kept open in the pool                        |
| `DB_MAX_OVERFLOW`             | `5`                                           | Extra connections allowed under load                     |
| `DB_POOL_TIMEOUT_SECONDS`     | `10`                                          | Wait for a free connection before failing                |
| `DB_POOL_RECYCLE_SECONDS`     | `1800`                                        | Replace connections older than this (`-1` = never)       |
| `SQLITE_BUSY_TIMEOUT_SECONDS` | `5`                                           | Wait for a SQLite lock before failing                    |
| **Pagination**                |                                               |                                                          |
| `DEFAULT_PAGE_SIZE`           | `20`                                          | `limit` used when it is not provided                     |
| `MAX_PAGE_SIZE`               | `100`                                         | Highest accepted `limit`                                 |
| **HTTP security**             |                                               |                                                          |
| `CORS_ORIGINS`                | `http://localhost:8050,http://127.0.0.1:8050` | Browser origins allowed to call the API (comma-separated) |
| `ALLOWED_HOSTS`               | `localhost,127.0.0.1,api`                     | Accepted `Host` headers (comma-separated; `*` = any)     |
| `API_KEY`                     | (empty = disabled)                            | When set, `/books` requires `X-API-Key: <value>`         |
| `ENABLE_DOCS`                 | `true`                                        | Serve `/docs`, `/redoc` and `/openapi.json`              |
| `MAX_REQUEST_BODY_BYTES`      | `65536`                                       | Largest request body accepted (413 above it)             |
| `RATE_LIMIT_REQUESTS`         | `300`                                         | Requests per client IP per window (`0` disables)         |
| `RATE_LIMIT_WINDOW_SECONDS`   | `60`                                          | Rate-limit window length                                 |

## Security

The API has no user accounts, but it is hardened against the usual risks of a public HTTP
service. Every item below is configurable through the variables above and covered by
`tests/api/test_security.py`.

### Access control

- **Optional API key.** When `API_KEY` is set, every `/books` request must send the header
  `X-API-Key: <value>`; otherwise the API answers `401 {"detail": "Invalid or missing API key"}`.
  The comparison is constant-time (`secrets.compare_digest`), so the key cannot be guessed
  from response times. `/health` stays public for health checks. When the key is not set, the
  API logs a warning at startup. Swagger UI shows an **Authorize** button to send the key.
  The frontend sends the same value from its own `API_KEY` variable.
- **Origins (CORS).** Only the origins in `CORS_ORIGINS` may call the API from a browser,
  restricted to `GET`/`POST` and the `Content-Type` and `X-API-Key` headers, without
  credentials. The Dash frontend calls the API from its server (not from the browser), so CORS
  only matters for other web clients.
- **Trusted hosts.** Requests whose `Host` header is not in `ALLOWED_HOSTS` get `400`, which
  blocks Host-header attacks and DNS rebinding.

### Limits

| Limit                      | Where                         | Behavior when exceeded                                   |
| -------------------------- | ----------------------------- | -------------------------------------------------------- |
| Requests per client IP     | `RATE_LIMIT_*`                | `429` with `Retry-After`; `X-RateLimit-*` headers on every response |
| Request body size          | `MAX_REQUEST_BODY_BYTES`      | `413`, also for chunked bodies without `Content-Length`  |
| Text sizes                 | Schemas                       | `title`/`author` ≤ 255 chars, `summary` ≤ 5000 chars → `422` |
| Page size                  | `MAX_PAGE_SIZE`               | `422`                                                     |
| Database connections       | `DB_POOL_SIZE` + `DB_MAX_OVERFLOW` | Requests wait up to `DB_POOL_TIMEOUT_SECONDS`         |
| Concurrent HTTP connections| `--limit-concurrency 100` (Dockerfile) | `503` above 100 simultaneous connections       |
| Idle keep-alive            | `--timeout-keep-alive 5` (Dockerfile)  | Idle connections closed after 5 s              |

The rate limiter keeps its counters in memory, per process: they reset on restart and are not
shared between workers. With several workers or servers, enforce the limit in a shared layer
(reverse proxy, API gateway or Redis). Behind a proxy, run uvicorn with `--proxy-headers` and
`--forwarded-allow-ips` so the real client IP is used. Note that all users of the Dash frontend
reach the API from the frontend server's IP, so they share one rate-limit bucket.

### Data protection

- **No mass assignment.** `BookCreate` rejects unknown fields (`422 extra_forbidden`), so a
  client cannot set server-controlled values such as `id`.
- **No SQL injection.** All queries go through SQLAlchemy with bound parameters; `%` and `_`
  typed by users are escaped in `LIKE` searches.
- **Integrity.** SQLite runs with `foreign_keys=ON`, WAL journaling (readers are not blocked by
  writes) and a busy timeout; `pool_pre_ping` drops dead connections.
- **No information leaks.** Unexpected errors return `500 {"detail": "Internal server error"}`;
  the traceback only goes to the server log. The Docker image does not send a `server` header.
- **Secrets.** `API_KEY` is stored as a `SecretStr` (masked in logs and reprs); keep real values
  in `.env` (git-ignored) or in the environment, never in the code.
- **Container.** The image runs as a non-root user, and the database lives in a dedicated volume.

### Response headers

Every response carries `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
`Referrer-Policy: no-referrer`, `Permissions-Policy` and `Cross-Origin-Resource-Policy`. JSON
endpoints also get `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'` (the
`/docs` page is exempt because it loads Swagger UI from a CDN).

### Production checklist

1. Set a strong `API_KEY` (`python -c "import secrets; print(secrets.token_urlsafe(32))"`) and
   the same value in the frontend.
2. Set `ALLOWED_HOSTS` and `CORS_ORIGINS` to your real domains only.
3. Set `ENABLE_DOCS=false` if the API surface should not be public.
4. Serve over HTTPS (TLS at a reverse proxy) and enable HSTS there.
5. Tune `RATE_LIMIT_*`, `MAX_REQUEST_BODY_BYTES` and the database pool to the expected load.
6. Back up the `library-data` volume (or move to a managed database via `DATABASE_URL`).

Not covered (out of scope for this project): user accounts and per-user permissions, TLS
termination, and audit logging.

## Getting started

### Prerequisite

Install **uv**: see the [official installation guide](https://docs.astral.sh/uv/getting-started/installation/).
uv downloads the Python version pinned in `.python-version` (3.12) automatically if needed.

### 1. Install dependencies

Inside the `backend/` folder:

```bash
uv sync
```

### 2. Run the API

```bash
uv run uvicorn app.main:app --reload
```

- Swagger UI: <http://127.0.0.1:8000/docs>
- ReDoc: <http://127.0.0.1:8000/redoc>
- Health check: <http://127.0.0.1:8000/health>

The `library.db` database is created automatically on the first run.

### 3. (Optional) Run it with the interface

The frontend lives in [`../frontend`](../frontend/README.md). With the API running, open another
terminal in `frontend/` and run `uv run python -m library_ui.app`, then open
<http://localhost:8050>.

### With Docker (optional)

The `Dockerfile` builds a multi-stage, non-root image with uv. To run the API together with the
frontend, use the `docker-compose.yml` one folder up:

```bash
cd ..
docker compose up --build
```

API docs at <http://localhost:8000/docs>, frontend at <http://localhost:8050>.

## Tests and quality

```bash
uv run pytest -v --cov=app   # tests with coverage (minimum: 90%)
uv run ruff check .          # lint
uv run ruff format .         # formatting
uv run mypy app              # type checking
```

Tests use a fresh in-memory SQLite database per test and never touch `library.db`.
The 90% coverage minimum is enforced in `pyproject.toml`.

## Adding dependencies

```bash
uv add <package>          # production dependency -> [project.dependencies]
uv add --dev <package>    # development dependency -> [dependency-groups].dev
```

Commit the updated `pyproject.toml` and `uv.lock`.

## Postman collection

[`postman/`](postman) has a ready-to-import collection with every request of the API (34
requests in 6 folders, each with automated tests):

| Folder                          | What it covers                                                        |
| ------------------------------- | --------------------------------------------------------------------- |
| 1. Health & docs                | `/health`, `/openapi.json`, `/docs`                                   |
| 2. Register books               | Successful `POST /books` (with/without `created_at`, timezones)       |
| 3. Validation errors (422)      | Missing/blank fields, bad dates, future dates, unknown fields, long summary |
| 4. Search books                 | Title, author, both, pagination, no results, invalid parameters       |
| 5. Get book by id               | Found, 404, invalid ids                                               |
| 6. Security                     | Missing/wrong API key (401), body too large (413), CORS, Host header, security headers |

1. In Postman, **Import** `postman/library-api.postman_collection.json` and
   `postman/library-api.local.postman_environment.json`.
2. Select the **Library API - local** environment. If `.env` sets `API_KEY`, paste the same value
   into the environment's `apiKey` (it is a secret variable and is empty in the file).
3. Run folder 2 before folders 4 and 5: they need data and the `bookId` saved by the first
   create request.

The whole collection can also run from the terminal with
[Newman](https://www.npmjs.com/package/newman), Postman's CLI runner:

```bash
npx newman run postman/library-api.postman_collection.json \
  -e postman/library-api.local.postman_environment.json --env-var "apiKey=<your API key>"
```

## Endpoints

| Method | Path               | Description                                   | Success | Errors   |
| ------ | ------------------ | --------------------------------------------- | ------- | -------- |
| POST   | `/books`           | Register a book                               | 201     | 413, 422 |
| GET    | `/books`           | Search by `title` / `author`, `skip`, `limit` | 200     | 422      |
| GET    | `/books/{book_id}` | Get a book by id                              | 200     | 404, 422 |
| GET    | `/health`          | Health check (public, never rate limited)     | 200     | —        |

Every `/books` endpoint may also return `401` (when `API_KEY` is set) and `429` (rate limit).
With an API key configured, add `-H "X-API-Key: <value>"` to the `curl` examples below.

### Book fields

| Field              | Type                | Rules                                                              |
| ------------------ | ------------------- | ------------------------------------------------------------------ |
| `id`               | integer             | Generated by the database                                          |
| `title`            | string              | Required, not blank, max 255 chars                                 |
| `author`           | string              | Required, not blank, max 255 chars                                 |
| `publication_date` | date (`YYYY-MM-DD`) | Required, not in the future                                        |
| `summary`          | string              | Optional free text, max 5000 chars (defaults to `""`)              |
| `created_at`       | datetime (ISO 8601) | Optional, not in the future; defaults to now. Always stored in UTC |

### Examples

**Register a book**

```bash
curl -X POST http://127.0.0.1:8000/books \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Harry Potter and the Philosopher'\''s Stone",
    "author": "J. K. Rowling",
    "publication_date": "1997-06-26",
    "summary": "A young wizard discovers his magical heritage."
  }'
```

```json
{
  "title": "Harry Potter and the Philosopher's Stone",
  "author": "J. K. Rowling",
  "publication_date": "1997-06-26",
  "summary": "A young wizard discovers his magical heritage.",
  "id": 1,
  "created_at": "2026-10-28T20:45:12.123456Z"
}
```

**Register a book with an explicit `created_at`** (converted to UTC)

```bash
curl -X POST http://127.0.0.1:8000/books \
  -H "Content-Type: application/json" \
  -d '{"title": "Dune", "author": "Frank Herbert", "publication_date": "1965-08-01",
       "created_at": "2024-05-10T11:30:00-03:00"}'
```

```json
{
  "title": "Dune",
  "author": "Frank Herbert",
  "publication_date": "1965-08-01",
  "summary": "",
  "id": 2,
  "created_at": "2024-05-10T14:30:00Z"
}
```

**Validation error** (`422`)

```bash
curl -X POST http://127.0.0.1:8000/books \
  -H "Content-Type: application/json" \
  -d '{"title": "", "author": "Someone", "publication_date": "2999-01-01"}'
```

```json
{
  "detail": [
    {"type": "string_too_short", "loc": ["body", "title"], "msg": "String should have at least 1 character", "...": "..."},
    {"type": "value_error", "loc": ["body", "publication_date"], "msg": "Value error, publication_date cannot be in the future", "...": "..."}
  ]
}
```

**Search by title** (partial, case-insensitive)

```bash
curl "http://127.0.0.1:8000/books?title=harry"
```

```json
[
  {
    "title": "Harry Potter and the Philosopher's Stone",
    "author": "J. K. Rowling",
    "publication_date": "1997-06-26",
    "summary": "A young wizard discovers his magical heritage.",
    "id": 1,
    "created_at": "2026-10-28T20:45:12.123456Z"
  }
]
```

**Search by title and author, with pagination**

```bash
curl "http://127.0.0.1:8000/books?title=potter&author=rowling&skip=0&limit=10"
```

**Get a book by id**

```bash
curl http://127.0.0.1:8000/books/1
```

**Book not found** (`404`)

```bash
curl http://127.0.0.1:8000/books/42
```

```json
{"detail": "Book with id 42 not found"}
```

**Health check**

```bash
curl http://127.0.0.1:8000/health
```

```json
{"status": "ok"}
```
