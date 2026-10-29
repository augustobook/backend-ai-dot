# Virtual Library

> 🇧🇷 Leia em português: [README.pt-BR.md](README.pt-BR.md)

A virtual library where users register books, search the catalog by title and/or author
and explore statistics. It has two independent applications, each with its own
`pyproject.toml`, `Dockerfile`, tests and README:

| Folder | What it is | Stack | Port | README |
|---|---|---|---|---|
| [`backend/`](backend) | REST API: register, search and get books | FastAPI, Pydantic v2, SQLAlchemy 2.0, SQLite | 8000 | [English](backend/README.md) · [Português](backend/README.pt-BR.md) |
| [`frontend/`](frontend) | Web interface in Portuguese: register, search, dashboard | Plotly Dash, Dash Bootstrap Components, httpx | 8050 | [English](frontend/README.md) · [Português](frontend/README.pt-BR.md) |

## How the parts fit together

```
 Browser ──▶ frontend (Dash, :8050) ──HTTP + X-API-Key──▶ backend (FastAPI, :8000) ──▶ SQLite
             callbacks run on the                         routes → services →
             Python server                                repositories → database
```

- The browser only talks to the frontend. Dash callbacks run on the server, which calls
  the API through `BooksApiClient`, so the API key never reaches the browser and the API
  can stay on an internal network.
- The API is the only owner of the data: validation rules (required fields, no future
  dates, size limits) live there, and the frontend turns its `422` errors into messages
  under each field, in Portuguese.
- Both read an optional `API_KEY`; when set, it must be the same value on both sides.

## Folder structure

```
01/
├── backend/
│   ├── app/              # api/ (routes, middleware), services/, repositories/, models/, db/, core/
│   ├── tests/            # unit/, integration/, api/
│   ├── postman/          # Postman collection (34 requests with tests) + local environment
│   ├── .env.example
│   └── Dockerfile
├── frontend/
│   ├── library_ui/       # app, layout, callbacks, api_client, services, assets/
│   ├── tests/
│   ├── .env.example
│   └── Dockerfile
└── docker-compose.yml    # Runs the API and the frontend together
```

## Quick start with Docker

```bash
docker compose up --build
```

- API docs: <http://localhost:8000/docs>
- Frontend: <http://localhost:8050>

`docker-compose.yml` builds both images (multi-stage, uv, non-root), stores the SQLite
database in the `library-data` volume and starts the frontend only after the API health
check passes. To require an API key, `export API_KEY=...` before `docker compose up`; both
containers receive it. Stop with `docker compose down` (add `-v` to also delete the data).

## Without Docker

Requires [uv](https://docs.astral.sh/uv/getting-started/installation/).

```bash
cd backend  && uv sync && uv run uvicorn app.main:app --reload   # terminal 1
cd frontend && uv sync && uv run python -m library_ui.app        # terminal 2
```

Both reload automatically on code changes; the frontend also refreshes the open browser
tab by itself. Settings go in `backend/.env` and `frontend/.env` (copy each
`.env.example`).

## Tests and quality

Run inside each folder:

```bash
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run mypy app          # backend
uv run mypy library_ui   # frontend
```

The backend tests use a fresh in-memory SQLite database per test (minimum coverage: 90%);
the frontend tests simulate the API with respx. Neither needs the other running.
