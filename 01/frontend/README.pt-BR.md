# Virtual Library — Frontend

> 🇺🇸 Read in English: [README.md](README.md)

Interface web em [Plotly Dash](https://dash.plotly.com/) para a Library API, desenvolvida para
a **DOT Digital Group**. Com ela, o usuário cadastra livros, busca no catálogo e vê
estatísticas da biblioteca. Tudo passa pela API REST em
[`../backend`](../backend/README.pt-BR.md).

**Idioma:** tudo o que aparece na tela está em **português** (rótulos, mensagens, erros de
validação, gráficos; datas no formato `DD/MM/AAAA`). O código, os nomes, as docstrings e os
comentários continuam em inglês.

## Visão geral

| Módulo                     | Responsabilidade                                                                      |
| -------------------------- | ------------------------------------------------------------------------------------- |
| `library_ui/app.py`        | Cria a app Dash (tema FLATLY + Bootstrap Icons) e expõe `server` para o gunicorn      |
| `library_ui/config.py`     | Configurações lidas de variáveis de ambiente                                          |
| `library_ui/api_client.py` | `BooksApiClient` (httpx): **toda** chamada HTTP, convertida em exceções próprias      |
| `library_ui/layout.py`     | Componentes, layout das páginas e IDs centralizados (`Ids`)                           |
| `library_ui/callbacks.py`  | Callbacks finos, que ligam os componentes ao client e aos services                    |
| `library_ui/services.py`   | Funções puras: formatação, validação, parsing de erros 422, paginação, dados dos gráficos |
| `library_ui/assets/`       | CSS com ajustes visuais sobre o tema                                                  |

Decisões de design:

- **Os callbacks nunca fazem HTTP diretamente.** Eles usam o `BooksApiClient`, que lança
  `ApiValidationError` (com os erros por campo), `ApiNotFoundError`, `ApiUnavailableError` ou
  `ApiResponseError`. Cada tela transforma essas exceções em um alerta amigável ou em erros
  embaixo de cada campo.
- **Fuso horário.** Os callbacks do Dash rodam no servidor, que não sabe o fuso do usuário. Um
  pequeno callback no navegador (clientside) guarda o fuso IANA do browser. Com isso, a
  "Data de cadastro" é convertida do horário local para UTC antes do envio, e as datas da API são
  exibidas de volta no horário local.
- **Paginação sem endpoint de contagem.** A busca pede `tamanho da página + 1` registros. Se o
  registro extra vier, o botão "Próxima" é habilitado. O `fetch_all_books()` percorre as páginas da
  API (que limita o `limit`) para o dashboard enxergar o catálogo inteiro.
- **Ordenação correta.** A tabela ordena pelos valores ISO originais, e não pelo texto
  formatado (em que `01/12/2019` viria depois de `01/04/2020`).
- **Mensagens em português para uma API em inglês.** A API responde em inglês; os erros 422
  são reescritos em português a partir do `type` de cada erro, e não traduzindo o texto bruto.
- **Nenhum endereço interno na tela.** A URL da API nunca aparece na interface (nem no alerta
  de "API fora do ar"); ela só vai para os logs do servidor.

## Estrutura do projeto

```
frontend/
├── library_ui/
│   ├── app.py                 # create_app(), expõe `server` (gunicorn) e roda o servidor de dev
│   ├── config.py              # Settings lidas do ambiente / .env
│   ├── api_client.py          # BooksApiClient (httpx) + exceções da API
│   ├── layout.py              # Navbar, abas, formulários, tabela, painel, IDs (Ids)
│   ├── callbacks.py           # Callbacks do Dash (finos)
│   ├── services.py            # Funções puras (formatação, validação, paginação, gráficos)
│   └── assets/styles.css      # Ajustes visuais sobre o tema FLATLY
├── tests/
│   ├── test_api_client.py     # Client com HTTP simulado (respx)
│   ├── test_services.py       # Funções puras
│   └── test_app.py            # Testes de fumaça do layout e dos callbacks
├── .env.example               # Todas as configurações com seus padrões
├── .python-version            # Python 3.12
├── Dockerfile                 # Imagem multi-stage com uv, gunicorn, usuário não-root
├── pyproject.toml             # Dependências e config de ruff/mypy/pytest
└── uv.lock
```

## Comunicação com a API

Os callbacks do Dash rodam **no servidor Python**, não no navegador. Por isso, quem chama a API
é sempre o servidor do frontend (pelo `BooksApiClient`); o navegador só conversa com o Dash.
Isso tem algumas consequências:

- **A chave da API não chega ao navegador.** O `API_KEY` é lido do ambiente do servidor e enviado
  no header `X-API-Key` de cada requisição; ele não aparece no HTML nem no JavaScript.
- **A API pode ficar numa rede interna.** O `API_BASE_URL` só precisa ser alcançável pelo
  servidor do frontend; no Docker, é `http://api:8000`, o nome do serviço no Compose.
- **CORS não se aplica aqui.** Como não há chamada do navegador para a API, o `CORS_ORIGINS` do
  backend só importa para outros clientes web.
- **Todos os usuários dividem o mesmo rate limit.** Para a API, toda requisição vem do IP do
  servidor do frontend; o limite de `RATE_LIMIT_REQUESTS` vale para a soma dos usuários.
- **Falhas viram mensagens.** Timeout (`API_TIMEOUT_SECONDS`), conexão recusada e erros HTTP
  são convertidos em exceções próprias pelo client, e cada tela mostra um alerta em português.

## Telas

- **Cadastrar livro:** formulário com Título, Autor, Data de publicação (datas futuras
  bloqueadas), Resumo e uma Data de cadastro opcional (data + hora, com a dica "Deixe em branco
  para usar a data e hora atuais"). Os erros aparecem embaixo de cada campo. O botão mostra um
  spinner enquanto salva. No sucesso, um alerta verde mostra o título cadastrado e o formulário
  é limpo.
- **Buscar livros:** filtros por Título e Autor (que podem ser usados juntos; Enter também
  busca), botões Buscar e Limpar, contador ("Exibindo livros 1–10") e tabela ordenável com
  título, autor, publicação (`15/01/2020`), cadastro (`28/10/2026 14:30`) e o resumo truncado.
  Tem paginação Anterior/Próxima e o estado vazio "Nenhum livro encontrado". Ao clicar em uma
  linha, abre um modal com os detalhes completos, buscados em `GET /books/{id}`.
- **Painel:** quatro cards (total de livros, autores distintos, livro mais antigo e mais
  recente), gráfico de barras de livros por ano de publicação, gráfico de barras horizontais
  com o top 10 autores, botão Atualizar e estado vazio quando não há livros. Também atualiza
  sozinho depois que um livro é cadastrado.

A navbar mostra "Biblioteca Virtual | para DOT Digital Group", e o rodapé e o título da aba do
navegador também citam a DOT Digital Group. Se a API estiver fora do ar, cada tela mostra "Não
foi possível conectar à API…" em vez de quebrar. O layout é responsivo: no celular, os campos
ficam empilhados.

As datas usam o campo de data nativo do navegador em vez do `dcc.DatePickerSingle`: o usuário
pode digitar a data diretamente (`DD/MM/AAAA` num navegador em português) ou escolher no
calendário, que aparece no idioma do navegador, e datas futuras ficam bloqueadas no calendário
(`max`). O seletor do Dash 4 só confirmava a data digitada com Enter/Tab, o que fazia parecer
que digitar não funcionava. Os erros de validação aparecem em vermelho embaixo de cada campo,
com a borda do campo também em vermelho.

## Como rodar

### Pré-requisito

Instale o **uv**: veja o [guia oficial de instalação](https://docs.astral.sh/uv/getting-started/installation/).

### 1. Subir a API

O frontend depende da API. Em um terminal, dentro da pasta `backend/`:

```bash
uv sync
uv run uvicorn app.main:app --reload
```

A API fica em <http://localhost:8000> (documentação em <http://localhost:8000/docs>).

### 2. Subir o frontend

Em outro terminal, dentro da pasta `frontend/`:

```bash
uv sync
uv run python -m library_ui.app
```

Abra <http://localhost:8050>. O servidor de desenvolvimento roda com **recarga automática**: ao
salvar um arquivo `.py`, ele reinicia e a aba aberta no navegador se atualiza sozinha; mudanças
no CSS (`library_ui/assets/`) são aplicadas sem recarregar a página. Para desligar, defina
`DASH_DEBUG=false`.

Se a API estiver em outro endereço, defina `API_BASE_URL` antes de subir o frontend:

```powershell
# PowerShell
$env:API_BASE_URL = "http://localhost:9000"; uv run python -m library_ui.app
```

```bash
# bash
API_BASE_URL=http://localhost:9000 uv run python -m library_ui.app
```

### Com Docker (opcional)

Se tiver o Docker ligado, na pasta que contém `backend/`, `frontend/` e `docker-compose.yml`:

```bash
docker compose up --build
```

Isso sobe a API (<http://localhost:8000/docs>) e o frontend (<http://localhost:8050>). No
container, o frontend usa o servidor **gunicorn** e acessa a API por `http://api:8000` (o nome
do serviço na rede do Compose). Ele só sobe depois que o health check da API passa.

## Variáveis de ambiente

Defina no ambiente ou num arquivo `frontend/.env` (copie o [`.env.example`](.env.example)); as
variáveis de ambiente têm prioridade sobre o arquivo. O `.env` é ignorado pelo git, então a
chave da API fica só na sua máquina.

| Variável              | Padrão                  | Descrição                                            |
| --------------------- | ----------------------- | ---------------------------------------------------- |
| `API_BASE_URL`        | `http://localhost:8000` | URL base da Library API                              |
| `API_KEY`             | (vazio)                 | Enviada como `X-API-Key`; deve ser igual à `API_KEY` da API, quando ela estiver definida |
| `API_TIMEOUT_SECONDS` | `5`                     | Timeout de cada requisição à API                     |
| `API_MAX_PAGE_SIZE`   | `100`                   | Maior `limit` aceito pela API (seu `MAX_PAGE_SIZE`)  |
| `SEARCH_PAGE_SIZE`    | `10`                    | Linhas por página na tela de busca                   |
| `DASH_HOST`           | `127.0.0.1`             | Host do servidor de desenvolvimento                  |
| `DASH_PORT`           | `8050`                  | Porta do servidor de desenvolvimento                 |
| `DASH_DEBUG`          | `true`                  | Só no servidor de desenvolvimento: reinicia ao mudar o código e atualiza o navegador (use `false` para desligar) |

## Testes e qualidade

Dentro da pasta `frontend/`:

```bash
uv run pytest                      # todos os testes
uv run pytest --cov=library_ui     # com cobertura
uv run ruff check . && uv run ruff format --check .
uv run mypy library_ui
```

- `tests/test_api_client.py` testa o `BooksApiClient` com o HTTP simulado pelo respx: sucesso,
  422 → `ApiValidationError`, query params enviados, 404, API fora do ar e a paginação do
  `fetch_all_books()`.
- `tests/test_services.py` testa as funções puras: formatação de datas, payload com e sem
  `created_at`, conversão de horário local para UTC, truncamento, parsing de erros 422,
  paginação e dados do dashboard, incluindo listas vazias.
- `tests/test_app.py` tem testes de fumaça que renderizam o layout e chamam os callbacks pelo
  endpoint HTTP do Dash.

Para adicionar dependências, use `uv add <pacote>` (ou `uv add --dev <pacote>`) e versione o
`uv.lock`.
