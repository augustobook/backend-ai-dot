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

## Decisões técnicas

As principais escolhas e o motivo de cada uma. A lista completa está na seção "Decisões
de projeto" do README de cada projeto.

**01 — Biblioteca virtual**

- **Camadas com repositório atrás de um `Protocol`** (rotas → services → repositories).
  As regras de negócio são testadas com um repositório falso em memória, sem banco, e
  trocar o SQLite por outro banco mexe só no repositório.
- **SQLite em vez de Postgres.** Para um catálogo deste tamanho, um arquivo basta e não
  exige outro serviço. Ele roda com WAL, `foreign_keys=ON` e busy timeout, e a URL do
  banco é configurável.
- **A API é a única dona das regras.** As validações ficam nos schemas Pydantic. O
  frontend só traduz os erros `422` em mensagens em português e chama a API pelo servidor
  Python (callbacks do Dash), então a chave da API nunca chega ao navegador.
- **Segurança de serviço público mesmo sem contas de usuário:** chave de API comparada em
  tempo constante, rate limit por IP, limite de tamanho do corpo, hosts confiáveis,
  campos desconhecidos rejeitados e `%`/`_` escapados nas buscas com `LIKE`.

**02 — Python Tutor**

- **`gpt-4o-mini` com temperatura `0.3`.** Tem boa qualidade didática a baixo custo e
  latência. A temperatura baixa deixa as respostas consistentes, que é o que se espera
  de um tutor.
- **Roteador de histórico.** A cada pergunta, um modelo pequeno (`gpt-4.1-nano`) decide
  se a conversa anterior é necessária. Quando é, o histórico vai **completo**, sem
  cortes; quando não é, economiza tokens.
- **Limites medidos em tokens com `tiktoken`, não em mensagens.** O usuário é avisado
  aos 80% da janela de contexto.
- **Um `ChatService` para três interfaces** (CLI, web e API). As interfaces só traduzem
  entrada e saída. Os erros da OpenAI viram exceções de domínio, e cada interface os
  mostra do seu jeito (mensagem amigável ou código HTTP).
- **Modelo injetado na chain.** Os testes usam um modelo falso do LangChain e nunca
  chamam a OpenAI.

**03 — Busca semântica**

- **O problema é de vocabulário, não de tamanho do modelo.** A pessoa escreve "prisão de
  ventre" e o artigo diz "obstipação". O `multilingual-e5-base` foi testado: ficou ~10×
  mais lento e não resolveu isso. Por isso o projeto usa o `e5-small` (rápido em CPU) e
  uma LLM barata (`gpt-5-nano`) que enriquece os trechos e reescreve as perguntas.
- **Índice separado de perguntas geradas.** Comparar a pergunta do usuário com perguntas
  é mais confiável do que compará-la com um parágrafo enciclopédico.
- **Busca híbrida com Reciprocal Rank Fusion.** A busca densa acha paráfrases e o BM25
  acha termos exatos. O RRF combina as duas listas pela posição, sem precisar calibrar
  notas de escalas diferentes.
- **Metadados como reforço, não como filtro.** Um palpite errado da LLM sobre a categoria
  não pode esconder a resposta certa.
- **Cross-encoder com limite de relevância.** É a única nota calibrada do pipeline, então
  é ela que decide quando nada responde de fato. O cross-encoder lê o trecho original, sem
  o enriquecimento: com o bloco da LLM, ele acertou 3 respostas a menos em 1º lugar na
  avaliação.
- **FAISS exato (`IndexFlatIP`).** Com alguns milhares de vetores, a busca exata é
  instantânea; um índice aproximado não traria ganho.
- **A LLM é opcional.** Sem `OPENAI_API_KEY`, a busca funciona com os trechos e as
  perguntas como estão.

## Como rodar localmente

Cada projeto roda sozinho. Com [uv](https://docs.astral.sh/uv/) instalado:

```bash
# 01 — API em http://localhost:8000/docs e interface em http://localhost:8050
cd 01 && docker compose up --build
# ou, sem Docker:
cd 01/backend  && uv sync && uv run uvicorn app.main:app --reload   # terminal 1
cd 01/frontend && uv sync && uv run python -m library_ui.app        # terminal 2

# 02 — chat web em http://localhost:8001 (exige OPENAI_API_KEY no .env)
cd 02/python_chatbot && uv sync && cp .env.example .env
uv run chainlit run app/ui/chainlit_app.py -w --port 8001

# 03 — interface em http://127.0.0.1:8065 (o índice já vem pronto em storage/)
cd 03/semantic_search && uv sync && cp .env.example .env   # OPENAI_API_KEY é opcional
uv run python -m app.ui.dash_app
```

No Windows (PowerShell), troque `cp` por `Copy-Item`. Na primeira vez, o 03 baixa os
modelos do Hugging Face (~1 GB), então demora alguns minutos para abrir. Os testes rodam
sem chave e sem rede: `uv run pytest` dentro da pasta de cada projeto. O README de cada projeto traz as
outras interfaces (CLI e API do 02, CLI do 03), o Docker e todas as configurações.
