# Virtual Library — Frontend

> 🇧🇷 Leia em português: [README.pt-BR.md](README.pt-BR.md)

A [Plotly Dash](https://dash.plotly.com/) web interface for the Library API, built for
**DOT Digital Group**. Users register books, search the catalog and explore library
statistics, all through the REST API in [`../backend`](../backend).

**Language:** everything the user sees on screen is in **Brazilian Portuguese** (labels,
messages, validation errors, charts; dates as `DD/MM/YYYY`). The code, identifiers, docstrings
and comments stay in English.

## Overview

| Module                     | Responsibility                                                                 |
| -------------------------- | ------------------------------------------------------------------------------ |
| `library_ui/app.py`        | Creates the Dash app (FLATLY theme + Bootstrap Icons), exposes `server` for gunicorn |
| `library_ui/config.py`     | Settings read from environment variables                                       |
| `library_ui/api_client.py` | `BooksApiClient` (httpx): **all** HTTP calls, translated into typed exceptions |
| `library_ui/layout.py`     | Components, page layout and the centralized component ids (`Ids`)              |
| `library_ui/callbacks.py`  | Thin Dash callbacks that wire components to the client and services            |
| `library_ui/services.py`   | Pure functions: formatting, validation, 422 parsing, search paging, chart data |
| `library_ui/assets/`       | CSS tweaks on top of the theme                                                 |

Design decisions:

- **Callbacks never call HTTP directly.** They use `BooksApiClient`, which raises
  `ApiValidationError` (with errors per field), `ApiNotFoundError`, `ApiUnavailableError` or
  `ApiResponseError`. Each screen turns these into a friendly alert or inline field errors.
- **Timezones.** Dash callbacks run on the server, which does not know the user's timezone. A
  small client-side callback stores the browser's IANA timezone; "Created At" is converted from
  local time to UTC before it is sent, and API datetimes are displayed back in local time.
- **Paging without a count endpoint.** The Search screen requests `page_size + 1` rows: if the
  extra row comes back, "Próxima" (next) is enabled. `fetch_all_books()` walks the API pages (the API caps
  `limit`) so the dashboard sees the whole catalog.
- **Correct sorting.** Table sorting runs on the raw ISO values, not on the formatted text
  (where `01/12/2019` would come after `01/04/2020`).
- **Portuguese messages for an English API.** The API answers in English; 422 errors are
  rebuilt in Portuguese from each error's `type`, not by translating the raw text.
- **No internal addresses on screen.** The API URL never appears in the UI (not even in the
  "API offline" alert); it is only written to the server logs.

## Project structure

```
frontend/
├── library_ui/
│   ├── app.py                 # create_app(), exposes `server` (gunicorn), runs the dev server
│   ├── config.py              # Settings read from the environment / .env
│   ├── api_client.py          # BooksApiClient (httpx) + API exceptions
│   ├── layout.py              # Navbar, tabs, forms, table, dashboard, component ids (Ids)
│   ├── callbacks.py           # Dash callbacks (thin)
│   ├── services.py            # Pure functions (formatting, validation, paging, charts)
│   └── assets/styles.css      # Visual tweaks on top of the FLATLY theme
├── tests/
│   ├── test_api_client.py     # Client with simulated HTTP (respx)
│   ├── test_services.py       # Pure functions
│   └── test_app.py            # Smoke tests of the layout and callbacks
├── .env.example               # Every setting with its default
├── .python-version            # Python 3.12
├── Dockerfile                 # Multi-stage image with uv, gunicorn, non-root user
├── pyproject.toml             # Dependencies and ruff/mypy/pytest config
└── uv.lock
```

## Talking to the API

Dash callbacks run **on the Python server**, not in the browser. So the API is always called by
the frontend server (through `BooksApiClient`); the browser only talks to Dash. This has a few
consequences:

- **The API key never reaches the browser.** `API_KEY` is read from the server's environment and
  sent in the `X-API-Key` header of each request; it is not in the HTML or the JavaScript.
- **The API can stay on an internal network.** `API_BASE_URL` only has to be reachable from the
  frontend server; in Docker it is `http://api:8000`, the Compose service name.
- **CORS does not apply here.** Since the browser never calls the API, the backend's
  `CORS_ORIGINS` only matters for other web clients.
- **All users share one rate limit.** To the API, every request comes from the frontend
  server's IP, so `RATE_LIMIT_REQUESTS` applies to all users combined.
- **Failures become messages.** Timeouts (`API_TIMEOUT_SECONDS`), refused connections and HTTP
  errors are turned into typed exceptions by the client, and each screen shows a Portuguese alert.

## Screens

The tab names below are the ones shown on screen.

- **Cadastrar livro** (register) — a card with Título, Autor, Data de publicação (future dates
  blocked), Resumo, and an optional Data de cadastro date + time ("Deixe em branco para usar a
  data e hora atuais"). Errors appear under each field; the button shows a spinner while
  saving; a green alert confirms the registered title and the form is cleared.
- **Buscar livros** (search) — Título and Autor filters (usable together, Enter also searches),
  Buscar and Limpar buttons, a result counter ("Exibindo livros 1–10"), a sortable table with
  title, author, publication date (`15/01/2020`), registration date (`28/10/2026 14:30`) and a
  truncated summary, Anterior/Próxima pagination and a "Nenhum livro encontrado" empty state.
  Clicking a row opens a modal with the full details loaded from `GET /books/{id}`, plus
  **Edit** (pre-filled form, same validation as registering; only changed fields are sent in
  `PATCH /books/{id}`) and **Delete** (asks for confirmation before `DELETE /books/{id}`).
  Editing and deleting were not required by the assignment; they complete the CRUD.
  The navbar also has a **Coleção Postman** button that downloads the API test collection,
  pointed at `PUBLIC_API_URL`.
- **Painel** (dashboard) — four summary cards (total books, distinct authors, oldest and newest
  book), a bar chart of books per publication year, a horizontal bar chart of the top 10
  authors, an Atualizar (refresh) button and an empty state when the library has no books. It
  also refreshes after a new book is registered.

The navbar reads "Biblioteca Virtual | para DOT Digital Group", and the footer and browser tab
title name DOT Digital Group too. If the API is offline, every screen shows "Não foi possível
conectar à API…" instead of breaking. The layout is responsive (stacked fields on phones).

Dates use the browser's native date input instead of `dcc.DatePickerSingle`: the user can
type the date directly (`DD/MM/AAAA` in a Portuguese browser) or pick it from a calendar shown
in the browser's language, and future dates are blocked in the calendar (`max`). Dash 4's
picker only committed typed dates on Enter/Tab, which made typing look broken. Validation
errors are shown in red under each field, with a red border on the field itself.

## Getting started

### Prerequisite

Install **uv**: see the [official installation guide](https://docs.astral.sh/uv/getting-started/installation/).

### 1. Run the API

The frontend needs the API. In one terminal, inside `backend/`:

```bash
uv sync
uv run uvicorn app.main:app --reload
```

The API runs at <http://localhost:8000> (docs at <http://localhost:8000/docs>).

### 2. Run the frontend

In another terminal, inside `frontend/`:

```bash
uv sync
uv run python -m library_ui.app
```

Open <http://localhost:8050>. The development server **auto-reloads**: saving a `.py` file
restarts it and the open browser tab refreshes by itself; CSS changes in `library_ui/assets/`
are applied without a page reload. Set `DASH_DEBUG=false` to turn this off.

If the API runs at another address, set `API_BASE_URL` before starting the frontend:

```powershell
# PowerShell
$env:API_BASE_URL = "http://localhost:9000"; uv run python -m library_ui.app
```

```bash
# bash
API_BASE_URL=http://localhost:9000 uv run python -m library_ui.app
```

### With Docker (optional)

From the folder that contains `backend/`, `frontend/` and `docker-compose.yml`:

```bash
docker compose up --build
```

This starts the API (<http://localhost:8000/docs>) and the frontend (<http://localhost:8050>).
In the container the frontend is served by **gunicorn** and reaches the API at
`http://api:8000` (the Compose service name). It only starts once the API health check passes.

## Environment variables

Set them in the environment or in a `frontend/.env` file (copy [`.env.example`](.env.example));
environment variables win over the file. `.env` is git-ignored, so the API key stays local.

| Variable              | Default                 | Description                                         |
| --------------------- | ----------------------- | --------------------------------------------------- |
| `API_BASE_URL`        | `http://localhost:8000` | Base URL of the Library API                         |
| `API_KEY`             | (empty)                 | Sent as `X-API-Key`; must match the API's `API_KEY` when it is set |
| `API_TIMEOUT_SECONDS` | `5`                     | Timeout of each API request                         |
| `API_MAX_PAGE_SIZE`   | `100`                   | Highest `limit` the API accepts (its `MAX_PAGE_SIZE`) |
| `SEARCH_PAGE_SIZE`    | `10`                    | Rows per page in Search Books                       |
| `DASH_HOST`           | `127.0.0.1`             | Host of the development server                      |
| `DASH_PORT`           | `8050`                  | Port of the development server                      |
| `DASH_DEBUG`          | `true`                  | Dev server only: auto-reload on code changes and refresh the browser (set `false` to disable) |
| `PUBLIC_API_URL`      | (`API_BASE_URL`)        | API URL written into the downloaded Postman collection (as the browser sees it, not the Docker name) |
| `POSTMAN_INCLUDE_API_KEY` | `false`             | Embed `API_KEY` in the downloaded collection. Public demos only |

## Tests and quality

```bash
uv run pytest                      # all tests
uv run pytest --cov=library_ui     # with coverage
uv run ruff check . && uv run ruff format --check .
uv run mypy library_ui
```

- `tests/test_api_client.py` — `BooksApiClient` with HTTP simulated by respx (success, 422 →
  `ApiValidationError`, query params, 404, API offline, `fetch_all_books()` pagination).
- `tests/test_services.py` — pure functions (formatting, payload with/without `created_at`,
  local → UTC conversion, truncation, 422 parsing, search paging, dashboard data, empty lists).
- `tests/test_app.py` — smoke tests that render the layout and invoke callbacks through Dash's
  HTTP endpoint.

Add dependencies with `uv add <pkg>` (or `uv add --dev <pkg>`) and commit `uv.lock`.
