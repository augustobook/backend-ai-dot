# Backend & IA

Três projetos independentes em Python, cada um numa pasta numerada. Eles não dependem
uns dos outros: cada um tem seu próprio `pyproject.toml` (gerenciado com
[uv](https://docs.astral.sh/uv/)), seu `Dockerfile`, seus testes e **seu próprio
README**, com a explicação completa de arquitetura, decisões, configuração e como rodar.
Este arquivo é só o mapa do repositório.

| Pasta | Projeto | Stack principal | README |
|---|---|---|---|
| [`01/`](01) | Biblioteca virtual: API REST + interface web | FastAPI, SQLAlchemy, SQLite, Plotly Dash | [01/README.pt-BR.md](01/README.pt-BR.md) |
| [`02/python_chatbot/`](02/python_chatbot) | Python Tutor: chatbot que ensina Python | LangChain, OpenAI, Chainlit, FastAPI | [02/python_chatbot/README.pt-BR.md](02/python_chatbot/README.pt-BR.md) |
| [`03/semantic_search/`](03/semantic_search) | Busca semântica em artigos de saúde | Embeddings E5, FAISS, BM25, cross-encoder, OpenAI, Dash | [03/semantic_search/README.pt-BR.md](03/semantic_search/README.pt-BR.md) |

## Acesse online

> **Observação:** os projetos rodam numa máquina na AWS que, por causa do custo, pode
> estar desligada em alguns momentos. Se algum link não abrir, é só entrar em contato
> comigo que eu ligo o servidor.

| Projeto | Link |
|---|---|
| Página inicial | <https://backend-ai-dot.oladata.com.br> |
| 01 — Biblioteca virtual (interface) | <https://01.backend-ai-dot.oladata.com.br> |
| 01 — API da biblioteca (Swagger) | <https://api-01.backend-ai-dot.oladata.com.br/docs> |
| 02 — Python Tutor (chatbot) | <https://02.backend-ai-dot.oladata.com.br> |
| 03 — Busca semântica | <https://03.backend-ai-dot.oladata.com.br> |

### Testando a API do 01 no Swagger

A documentação abre sem chave, mas os endpoints `/books` exigem o cabeçalho
`X-API-Key`. Chave da demonstração:

```
TiqGqSQ8HETtY92eH3AXwY_UAILquYHQoTC1sMGbjcg
```

Em <https://api-01.backend-ai-dot.oladata.com.br/docs>, clique em **Authorize**, cole a
chave e confirme; depois use **Try it out** em qualquer endpoint. Sem a chave, as
chamadas a `/books` retornam `401`. A chave é pública de propósito (é só um ambiente de
demonstração) e a API tem limite de requisições por IP.

## Organização das pastas

```
.
├── 01/                       # Biblioteca virtual
│   ├── backend/              #   API REST (FastAPI + SQLite)
│   ├── frontend/             #   Interface web (Plotly Dash) que consome a API
│   ├── docker-compose.yml    #   Sobe só o projeto 01 (API + interface)
│   └── README.md             #   Visão geral do 01 (também README.pt-BR.md)
├── 02/
│   └── python_chatbot/       # Chatbot Python Tutor (CLI, web e API)
├── 03/
│   └── semantic_search/      # Busca semântica híbrida (CLI e web)
├── deploy/
│   ├── Caddyfile             # Proxy reverso: um subdomínio por projeto, HTTPS automático
│   └── landing/index.html    # Página inicial com links para os projetos
├── docker-compose.yml        # Sobe todos os projetos juntos atrás do Caddy
└── .env.example              # Variáveis do docker-compose da raiz
```

Dentro de cada projeto a estrutura segue o mesmo padrão: `app/` (ou `library_ui/` no
frontend do 01) com o código separado em camadas (`core/` para configuração, logs e
exceções; `services/` para os casos de uso; e as interfaces por cima, finas), `tests/`
com testes que rodam offline, e `pyproject.toml` com ruff, mypy (modo estrito) e pytest
configurados.

## 01 — Biblioteca virtual

Cadastro, busca, edição e exclusão de livros.

> **Sobre a edição e a exclusão:** a Questão 1 da prova (`Prova - Backend IA.pdf`) pede
> apenas o **cadastro** de livros (título, autor, data de publicação e resumo) e a
> **consulta** por título ou autor. A atualização e a exclusão de registros **não foram
> pedidas**, mas optei por implementá-las para entregar um CRUD completo: na API
> (`PATCH /books/{id}` e `DELETE /books/{id}`, com as mesmas validações do cadastro e
> testes) e na interface (botões **Editar** e **Excluir** nos detalhes do livro).

- **[`01/backend/`](01/backend)**: API REST em FastAPI com SQLite via SQLAlchemy 2.0.
  Cadastra livros, busca por título e/ou autor (busca parcial, sem diferenciar
  maiúsculas, com paginação), edita e exclui. Organizada em camadas (rotas → services → repositories →
  banco), com middleware de segurança (chave de API opcional, limite de requisições,
  hosts permitidos) e uma coleção do Postman em `postman/`.
  README: [inglês](01/backend/README.md) · [português](01/backend/README.pt-BR.md).
- **[`01/frontend/`](01/frontend)**: interface em Plotly Dash, toda em português, que
  consome a API: cadastro de livros, busca no catálogo (com edição e exclusão a partir
  dos detalhes do livro) e um painel com estatísticas.
  README: [inglês](01/frontend/README.md) · [português](01/frontend/README.pt-BR.md).

O README da pasta 01 ([português](01/README.pt-BR.md) · [inglês](01/README.md)) mostra
como as duas partes se conectam e como subi-las juntas (Docker ou `uv`).

## 02 — Python Tutor (chatbot)

Chatbot que responde **dúvidas sobre programação em Python** de forma didática
(conceito, código comentado, armadilhas comuns e boas práticas), no idioma da pergunta,
e recusa educadamente assuntos fora de Python.

- Cadeia LCEL do LangChain com modelo da família GPT-4 da OpenAI (padrão `gpt-4o-mini`).
- Memória por conversa; um modelo pequeno ("roteador") decide, a cada pergunta, se o
  histórico precisa ser enviado. Limites medidos em tokens, com aviso aos 80%.
- Três interfaces sobre o mesmo serviço: **CLI** (rich), **web** (Chainlit, com lista de
  conversas salva em SQLite) e **API REST** (FastAPI).
- Rastreamento opcional no LangSmith.
- Exige `OPENAI_API_KEY`.

README: [português](02/python_chatbot/README.pt-BR.md) ·
[inglês](02/python_chatbot/README.md) (exemplos de respostas em
[docs/EXAMPLES.md](02/python_chatbot/docs/EXAMPLES.md)).

## 03 — Busca semântica

Busca híbrida sobre **100 artigos de saúde da Wikipédia em português**: a pessoa
pergunta com as próprias palavras ("o que comer para acabar com a prisão de ventre") e
a busca encontra os trechos que respondem, mesmo quando o artigo usa outros termos.

- **Busca densa** (embeddings `multilingual-e5-small` + FAISS) combinada com **BM25**
  por Reciprocal Rank Fusion.
- **LLM opcional** (`gpt-5-nano`) que enriquece cada trecho na ingestão e reescreve cada
  pergunta na busca; sem a chave, tudo continua funcionando.
- **Cross-encoder** que reordena os melhores candidatos e separa resultados de baixa
  relevância.
- Interface web em Dash, CLI (`ingest`, `search`, `stats`) e um conjunto de avaliação
  com 60 perguntas (hit@k, MRR).

README: [português](03/semantic_search/README.pt-BR.md) ·
[inglês](03/semantic_search/README.md). Detalhes técnicos em
[docs/EMBEDDINGS_PIPELINE.md](03/semantic_search/docs/EMBEDDINGS_PIPELINE.md) e
[docs/EVALUATION.md](03/semantic_search/docs/EVALUATION.md).

## Rodando

Todos os projetos sobem juntos com Docker. Na raiz:

```bash
cp .env.example .env          # Windows (PowerShell): Copy-Item .env.example .env
# preencha OPENAI_API_KEY; use DOMAIN=localhost para rodar localmente

# cada serviço também lê o .env do próprio projeto (env_file no docker-compose.yml)
for dir in 01/backend 01/frontend 02/python_chatbot 03/semantic_search; do
  [ -f "$dir/.env" ] || cp "$dir/.env.example" "$dir/.env"
done

docker compose up -d --build
```

Os cinco arquivos `.env` ficam fora do git, então precisam ser criados em cada máquina
nova (inclusive no servidor); sem algum deles o `docker compose up` falha com
"env file not found". O `.env` da raiz tem prioridade: `DOMAIN` e as chaves definidas
nele sobrescrevem os valores dos `.env` dos projetos.

O servidor já tem um [Caddy](https://caddyserver.com/) de outro projeto nas portas
80/443, responsável pelo HTTPS. Esta stack não publica portas: o Caddy dela é um
roteador interno, ligado à rede Docker daquele Caddy (`PROXY_NETWORK` no `.env`), que
encaminha cada subdomínio para o seu serviço. No Caddyfile do Caddy principal entra
um bloco só:

```
backend-ai-dot.oladata.com.br, 01.backend-ai-dot.oladata.com.br, api-01.backend-ai-dot.oladata.com.br, 02.backend-ai-dot.oladata.com.br, 03.backend-ai-dot.oladata.com.br {
	reverse_proxy backend-ai-dot-router:80
}
```

Endereços:

| Endereço | Serviço |
|---|---|
| `https://DOMAIN` | Página inicial com links para os projetos |
| `https://01.DOMAIN` | 01 — interface da biblioteca |
| `https://api-01.DOMAIN` | 01 — API da biblioteca (documentação em `/docs`) |
| `https://02.DOMAIN` | 02 — chatbot (Chainlit) |
| `https://03.DOMAIN` | 03 — busca semântica |

Para rodar localmente, sem o Caddy principal, use `DOMAIN=localhost`, crie a rede
com `docker network create proxy` (e `PROXY_NETWORK=proxy`) e publique a porta do
roteador num `docker-compose.override.yml` (`services: caddy: ports: ["8080:80"]`); os
endereços ficam `http://01.localhost:8080`, `http://02.localhost:8080` e assim por
diante.
