# Biblioteca Virtual

> 🇺🇸 Read in English: [README.md](README.md)

Uma biblioteca virtual em que o usuário cadastra livros, busca no catálogo por título e/ou
autor e vê estatísticas. São duas aplicações independentes, cada uma com seu próprio
`pyproject.toml`, `Dockerfile`, testes e README:

| Pasta | O que é | Stack | Porta | README |
|---|---|---|---|---|
| [`backend/`](backend) | API REST: cadastrar, buscar e consultar livros | FastAPI, Pydantic v2, SQLAlchemy 2.0, SQLite | 8000 | [Português](backend/README.pt-BR.md) · [English](backend/README.md) |
| [`frontend/`](frontend) | Interface web em português: cadastro, busca, painel | Plotly Dash, Dash Bootstrap Components, httpx | 8050 | [Português](frontend/README.pt-BR.md) · [English](frontend/README.md) |

## Como as partes se conectam

```
 Navegador ──▶ frontend (Dash, :8050) ──HTTP + X-API-Key──▶ backend (FastAPI, :8000) ──▶ SQLite
               os callbacks rodam no                        rotas → services →
               servidor Python                              repositories → banco
```

- O navegador só conversa com o frontend. Os callbacks do Dash rodam no servidor, que chama
  a API pelo `BooksApiClient`; assim, a chave da API nunca chega ao navegador e a API pode
  ficar numa rede interna.
- A API é a única dona dos dados: as regras de validação (campos obrigatórios, datas no
  futuro, limites de tamanho) ficam nela, e o frontend transforma os erros `422` em
  mensagens em português embaixo de cada campo.
- Os dois leem uma `API_KEY` opcional; quando definida, precisa ter o mesmo valor nos dois.

## Organização das pastas

```
01/
├── backend/
│   ├── app/              # api/ (rotas, middleware), services/, repositories/, models/, db/, core/
│   ├── tests/            # unit/, integration/, api/
│   ├── postman/          # Collection do Postman (45 requisições com testes) + environment local
│   ├── .env.example
│   └── Dockerfile
├── frontend/
│   ├── library_ui/       # app, layout, callbacks, api_client, services, assets/
│   ├── tests/
│   ├── .env.example
│   └── Dockerfile
└── docker-compose.yml    # Sobe a API e o frontend juntos
```

## Início rápido com Docker

```bash
docker compose up --build
```

- Documentação da API: <http://localhost:8000/docs>
- Frontend: <http://localhost:8050>

O `docker-compose.yml` gera as duas imagens (multi-stage, uv, usuário não-root), guarda o
banco SQLite no volume `library-data` e só sobe o frontend depois que o health check da API
passa. Para exigir uma chave de API, rode `export API_KEY=...` antes do `docker compose up`;
os dois containers a recebem. Para parar, `docker compose down` (com `-v` também apaga os
dados).

## Sem Docker

Requer o [uv](https://docs.astral.sh/uv/getting-started/installation/).

```bash
cd backend  && uv sync && uv run uvicorn app.main:app --reload   # terminal 1
cd frontend && uv sync && uv run python -m library_ui.app        # terminal 2
```

Os dois recarregam sozinhos quando o código muda; o frontend também atualiza a aba aberta
no navegador. As configurações ficam em `backend/.env` e `frontend/.env` (copie cada
`.env.example`).

## Testes e qualidade

Dentro de cada pasta:

```bash
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run mypy app          # backend
uv run mypy library_ui   # frontend
```

Os testes do backend usam um SQLite em memória novo a cada teste (cobertura mínima de 90%);
os do frontend simulam a API com o respx. Nenhum dos dois precisa do outro rodando.
