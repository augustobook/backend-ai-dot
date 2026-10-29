# 🐍 Python Tutor: um chatbot com LangChain + OpenAI

> 🇺🇸 Read in English: [README.md](README.md)

Um chatbot que responde **perguntas sobre programação em Python** com respostas didáticas
e detalhadas: conceito, exemplos de código comentados, armadilhas comuns e boas práticas.
Ele mantém o contexto da conversa (perguntas de acompanhamento funcionam), responde no
**mesmo idioma da pergunta** e recusa educadamente assuntos que não sejam Python.

A mesma lógica central atende três interfaces:

| Interface | Tecnologia | Comando |
|---|---|---|
| CLI interativa | [rich](https://rich.readthedocs.io/) (Markdown, destaque de sintaxe, streaming) | `uv run python -m app.cli` |
| Chat web | [Chainlit](https://docs.chainlit.io/) (streaming, perguntas sugeridas) | `uv run chainlit run app/ui/chainlit_app.py -w --port 8001` |
| API REST | [FastAPI](https://fastapi.tiangolo.com/) (documentação Swagger) | `uv run uvicorn app.api.main:app --reload` |

## Início rápido

```bash
uv sync
cp .env.example .env      # preencha OPENAI_API_KEY (Windows: Copy-Item .env.example .env)
uv run chainlit run app/ui/chainlit_app.py -w --port 8001   # http://localhost:8001
```

Troque o último comando por qualquer interface da tabela acima. Detalhes em
[Pré-requisitos](#pré-requisitos), [Configuração](#configuração) e [Como rodar](#como-rodar);
Docker em [Com Docker](#com-docker).

## Stack

- **Python 3.12** gerenciado com **[uv](https://docs.astral.sh/uv/)**
- **LangChain** (`langchain-core`, `langchain-openai`): chain LCEL, templates de prompt, histórico de mensagens
- **OpenAI**: modelo de chat da família GPT-4 (padrão `gpt-4o-mini`, configurável)
- **LangSmith** (opcional) para rastreamento e observabilidade
- **FastAPI** + **Uvicorn**, **Chainlit**, **rich**, **pydantic-settings**
- **pytest** + **pytest-cov**, **ruff**, **mypy** (modo estrito)

## Arquitetura

```
                 ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐
  entrada    ──▶ │  CLI (rich)  │  │ API (FastAPI)│  │  Web (Chainlit)  │   só interfaces
                 └──────┬───────┘  └──────┬───────┘  └────────┬─────────┘
                        └─────────────────┼───────────────────┘
                                          ▼
                              ┌───────────────────────┐
                              │      ChatService      │  1. pergunta ≤ 5000 caracteres?
                              │ (camada de services)  │  2. tokens(system + histórico
                              └───────────┬───────────┘     completo + pergunta) ≤ limite? (tiktoken)
                                          │              3. roteador de histórico (gpt-4.1-nano):
                                          │                 precisa do histórico?
                                          ▼              converte erros da OpenAI em erros de domínio
   ┌───────────────────────── RunnableWithMessageHistory ──────────────────────────┐
   │  carrega o histórico do session_id ──▶ InMemoryChatMessageHistory (por sessão)│
   │                                                                               │
   │      ChatPromptTemplate ─────────▶ ChatOpenAI ─────────▶ StrOutputParser      │
   │  (system + [histórico COMPLETO       (família GPT-4)      (texto/stream)       │
   │   se necessário] + pergunta)                                                  │
   │                                                                               │
   │  salva pergunta + resposta no histórico da sessão                             │
   └───────────────────────────────────────┬───────────────────────────────────────┘
                                           │ cada execução é rastreada (se ativado) com
                                           ▼ metadados {session_id, interface} + tags
                                      LangSmith
```

```
python_chatbot/
├── app/
│   ├── cli.py                   # CLI interativa (rich)
│   ├── core/                    # Settings, exceções de domínio, logging, configuração do LangSmith
│   ├── llm/                     # Prompt de sistema, chain LCEL, roteador de histórico, histórico por sessão
│   ├── services/                # ChatService: os casos de uso compartilhados por todas as interfaces
│   ├── api/                     # App FastAPI, schemas, dependências, rotas
│   └── ui/                      # Handlers do Chainlit (finos), helpers puros, persistência em SQLite
├── .chainlit/                   # Config do Chainlit (nome, pt-BR, tema) e tradução pt-BR
├── public/                      # Logos, avatar, ícones das sugestões, cores do tema, CSS próprio
├── chainlit.md                  # Página de boas-vindas da interface web
├── data/                        # Histórico de conversas da web (SQLite, criado sob demanda; fora do git)
├── docs/EXAMPLES.md             # Perguntas e respostas reais (geradas pelo script abaixo)
├── scripts/generate_examples.py # Gera o docs/EXAMPLES.md
├── tests/                       # Testes unitários e de API (LLM falsa, sem chamadas à OpenAI)
├── .env.example                 # Todas as configurações com seus padrões
├── Dockerfile                   # Imagem multi-stage com uv, usuário não-root, roda a interface web
└── pyproject.toml               # Dependências e config de ruff/mypy/pytest/cobertura
```

## Decisões de projeto

- **Modelo e temperatura.** O padrão é o `gpt-4o-mini`: um modelo da família GPT-4 com boa
  qualidade para respostas didáticas, a baixo custo e latência. Qualquer modelo da família
  GPT-4 pode ser usado via `OPENAI_MODEL` (por exemplo `gpt-4o`, `gpt-4.1`). A temperatura é
  `0.3`: um tutor precisa ser preciso e consistente, com variação suficiente apenas para
  manter as explicações naturais. `max_tokens`, `timeout` e `max_retries` limitam custo e
  latência.
- **Memória.** `RunnableWithMessageHistory` + `InMemoryChatMessageHistory`, um histórico por
  `session_id` (uma execução da CLI, um cliente da API ou uma aba do navegador), então as
  conversas nunca se misturam. O armazenamento fica em memória por simplicidade; trocá-lo por
  Redis/SQL muda só o `app/llm/history.py`.
- **Histórico: nunca cortado, enviado só quando necessário.** Um modelo pequeno e barato
  decide, a cada pergunta, se a conversa é necessária; quando é, o histórico **completo** é
  enviado (nenhuma mensagem é cortada). Veja
  [Como o histórico da conversa é tratado](#como-o-histórico-da-conversa-é-tratado).
- **Limites medidos em tokens.** As perguntas são limitadas a 5000 caracteres e cada
  conversa à janela de contexto do modelo, contada exatamente com `tiktoken`; o usuário é
  avisado aos 80%. Veja [Limites](#limites).
- **Engenharia de prompt** (`app/llm/prompts.py`, cada decisão está comentada lá):
  um *papel* concreto (tutor sênior de Python, paciente); um *formato de resposta* fixo
  (conceito → código comentado em Markdown → armadilhas → boas práticas, proporcional à
  pergunta); uma *regra de idioma* (responder no idioma da última mensagem, identificadores de
  código em inglês); uma *regra de escopo*; uso do *contexto da conversa*; e *honestidade*
  (nunca inventar APIs).
- **Restrição de escopo.** O prompt de sistema só permite assuntos de programação em Python;
  qualquer outro recebe uma recusa curta e educada que sugere um tema relacionado de Python.
- **Testabilidade.** `build_chat_chain(model, ...)` recebe o modelo como parâmetro
  (`BaseChatModel`), então os testes injetam um modelo falso do LangChain e nunca chamam a
  OpenAI.
- **Tratamento de erros.** As exceções da OpenAI são traduzidas em exceções de domínio
  (`LLMAuthenticationError`, `LLMRateLimitError`, `LLMTimeoutError`,
  `LLMUnavailableError`), registradas no log com os detalhes técnicos e mostradas ao usuário
  como mensagens amigáveis (CLI/web) ou erros HTTP (API: 409, 422, 429, 503, 504).
- **Interfaces finas.** A CLI, a API e o app Chainlit só traduzem entrada e saída e delegam
  ao `ChatService`; nenhuma lógica de LLM é duplicada.

### Limitações conhecidas

- Desde o `langchain-core` 1.6, `RunnableWithMessageHistory` e
  `InMemoryChatMessageHistory` emitem um `LangChainDeprecationWarning` recomendando a
  persistência do LangGraph. Elas ainda fazem parte do `langchain-core` e são usadas aqui
  porque os requisitos do projeto pedem uma chain LCEL pura com essas classes. Só esses dois
  avisos conhecidos são silenciados (`app/llm/__init__.py`), e o `langchain-core` está
  fixado abaixo da 2.0, versão em que elas serão removidas. A memória está isolada atrás do
  `SessionHistoryStore` e do `build_chat_chain`, então uma migração para o checkpointer do
  LangGraph não afetaria o service nem as interfaces.
- A memória da conversa vive no processo: é perdida ao reiniciar e não é compartilhada entre
  vários workers da API. Um armazenamento persistente (por exemplo Redis) resolveria as duas
  coisas. (A interface web a recarrega do SQLite quando uma conversa é reaberta.)

## Como o histórico da conversa é tratado

Cada conversa (`session_id`) mantém o seu **histórico completo**: toda pergunta e resposta é
salva e **nenhuma mensagem é cortada**. O que muda de uma pergunta para a outra é apenas **se
esse histórico é enviado ao modelo**. Enviá-lo junto com uma pergunta independente custaria
mais e acrescentaria ruído; deixá-lo de fora de uma pergunta de acompanhamento produziria uma
resposta errada. Um pequeno **roteador de histórico** decide, pergunta a pergunta.

### Fluxo de uma pergunta

```
Pergunta do usuário
      │
      ▼
0. Limites (ChatService._check_limits)
      ├─ pergunta > 5000 caracteres?                                → recusada (QuestionTooLongError)
      └─ prompt de sistema + histórico COMPLETO + pergunta > limite? → recusada (ConversationLimitError)
      │
      ▼
1. É a primeira pergunta da conversa?
      ├─ sim → não há histórico: nenhuma chamada extra
      └─ não ↓
2. Chamada ao ROTEADOR (app/llm/router.py) ─ separada, pequena e barata
      modelo : HISTORY_ROUTER_MODEL (padrão gpt-4.1-nano), temperatura 0, ≤ 150 tokens
      entrada: instruções do roteador + ÚLTIMAS 6 mensagens (cada uma cortada em 600 caracteres)
               + a nova pergunta
      saída  : estruturada  { "needs_history": true | false, "reason": "..." }
      │
      ▼
3. Chamada da RESPOSTA (o tutor: OPENAI_MODEL, padrão gpt-4o-mini, com streaming)
      ├─ needs_history = true  → prompt de sistema + histórico COMPLETO + pergunta
      └─ needs_history = false → prompt de sistema + pergunta (sem histórico)
      │
      ▼
4. A pergunta e a resposta são SALVAS no histórico (nos dois casos)
```

### Exemplo (uma conversa)

| # | Pergunta | Decisão do roteador | Enviado ao modelo tutor |
|---|---|---|---|
| 1 | "Como criar uma lista em Python?" | nenhuma (primeira pergunta) | só a pergunta |
| 2 | "E como adiciono itens nela?" | `true`: "nela" se refere à lista | histórico completo (turno 1) + pergunta |
| 3 | "O que são decorators?" | `false`: independente | só a pergunta |
| 4 | "Me dá outro exemplo disso?" | `true`: "disso" se refere a decorators | histórico completo (turnos 1-3) + pergunta |

A pergunta 4 funciona porque o turno 3 foi salvo, mesmo que a pergunta 3 tenha sido enviada
sem histórico.

### Regras

- **O roteador só decide; a resposta recebe tudo.** O roteador vê um trecho curto e cortado
  (suficiente para detectar referências como "it", "nela", "disso", "o código acima"). Quando
  o histórico é necessário, o modelo tutor recebe a conversa **inteira**, nunca um resumo ou
  um corte.
- **Na dúvida, envia o histórico.** As instruções do roteador terminam com
  "When in doubt, answer true", e qualquer falha do roteador (timeout, saída inválida) também
  cai no envio do histórico: contexto a mais não atrapalha, contexto a menos sim.
- **Barato e rápido de propósito.** O roteador usa um modelo nano separado, sem raciocínio,
  com um limite de saída mínimo. Modelos de raciocínio (por exemplo a família nano do
  `gpt-5`) podem ser mais baratos por token, mas gastam tokens de "raciocínio" e tempo numa
  decisão de sim ou não.
- **Por que um roteador e não um agente.** Um agente com ferramentas ("chame `get_history`
  quando precisar") exigiria duas chamadas sempre que o histórico fosse necessário e
  complicaria o streaming. Uma única chamada de decisão estruturada responde à mesma pergunta
  de sim ou não.
- **Custo.** A partir da segunda pergunta, cada pergunta acrescenta uma pequena chamada ao
  roteador (algumas centenas de tokens no modelo mais barato). Em troca, perguntas
  independentes deixam de levar a conversa inteira ao modelo tutor.
- **Os limites não dependem da decisão.** O limite da conversa sempre conta o histórico
  completo, porque ele limita o tamanho da própria conversa.
- **Observabilidade.** No LangSmith, cada pergunta mostra uma execução `history_router` (com o
  `reason`), e a execução da resposta leva o metadado `history_used` e a tag
  `history:used` ou `history:skipped`.
- **Configuração.** `HISTORY_ROUTER_MODEL` troca o modelo do roteador;
  `HISTORY_ROUTER_ENABLED=false` desliga o roteador (o histórico completo passa a ser sempre
  enviado).

Onde fica: o prompt e a lógica da decisão em [`app/llm/router.py`](app/llm/router.py)
(`ROUTER_SYSTEM_PROMPT`, `HistoryRouter`); a decisão é aplicada em
`ChatService._prepare` / `_aprepare` ([`app/services/chat_service.py`](app/services/chat_service.py));
a chain descarta o histórico quando `use_history` é falso
([`app/llm/chain.py`](app/llm/chain.py)).

### Limites

- **Pergunta:** no máximo **5000 caracteres** (`MAX_QUESTION_LENGTH`), em todas as
  interfaces. Acima disso, `QuestionTooLongError` (API: `422`).
- **Conversa:** os tokens de *prompt de sistema + histórico completo + nova pergunta* precisam
  caber em `OPENAI_CONTEXT_WINDOW - OPENAI_MAX_TOKENS` (128000 - 4096 = 123904 tokens por
  padrão), para o modelo sempre ter espaço para uma resposta completa. Acima disso,
  `ConversationLimitError` (API: `409`) e o usuário é convidado a começar uma nova conversa; o
  histórico fica intacto.
- **Resposta:** no máximo `OPENAI_MAX_TOKENS` (padrão 4096 tokens).
- **A contagem de tokens** é **exata**, com o tokenizador do próprio modelo
  (`ChatOpenAI.get_num_tokens_from_messages`, que usa o `tiktoken`). Como referência:
  prompt de sistema + uma pergunta curta ≈ 430 tokens; uma pergunta de 5000 caracteres ≈ 630
  tokens. O contador é injetado no `ChatService`, então os testes usam um contador
  aproximado e continuam offline.
- **Aviso aos 80%:** um toast na interface web (não salvo no histórico), uma linha amarela na
  CLI e os campos `conversation_usage_percent` / `near_conversation_limit` na resposta da API.
- **Perguntas por cliente:** cada IP pode fazer **10 perguntas por minuto e 100 por dia**
  (`RATE_LIMIT_PER_MINUTE`, `RATE_LIMIT_PER_DAY`; `0` desliga) na interface web e na API,
  porque cada pergunta custa tokens da OpenAI. Acima disso, a interface web mostra quanto
  tempo esperar e a API responde `429` com o cabeçalho `Retry-After`; perguntas recusadas
  nunca chegam à OpenAI e não são contadas. A CLI é local e nunca é limitada. Atrás dos
  proxies reversos (Caddy), o cliente é o endereço público mais à direita do
  `X-Forwarded-For`, então um valor forjado pelo cliente é ignorado. Os contadores ficam em
  memória (um processo; zeram ao reiniciar).

## Pré-requisitos

1. **uv**: veja o [guia de instalação](https://docs.astral.sh/uv/getting-started/installation/).
   - macOS/Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`
   - Windows: `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
2. **Uma chave da API da OpenAI**: crie em <https://platform.openai.com/api-keys>.

O uv baixa o Python 3.12 automaticamente, se necessário (fixado em `.python-version`).

## Configuração

Copie o arquivo de exemplo e preencha a sua chave:

```bash
cp .env.example .env      # Windows (PowerShell): Copy-Item .env.example .env
```

| Variável | Padrão | Descrição |
|---|---|---|
| `OPENAI_API_KEY` | *(obrigatória)* | Chave da API da OpenAI |
| `OPENAI_MODEL` | `gpt-4o-mini` | Modelo de chat da família GPT-4 |
| `OPENAI_TEMPERATURE` | `0.3` | Temperatura de amostragem |
| `OPENAI_MAX_TOKENS` | `4096` | Máximo de tokens por resposta |
| `OPENAI_CONTEXT_WINDOW` | `128000` | Tokens que o modelo aceita por requisição (define o limite da conversa) |
| `HISTORY_ROUTER_ENABLED` | `true` | Decide, a cada pergunta, se o histórico é enviado |
| `HISTORY_ROUTER_MODEL` | `gpt-4.1-nano` | Modelo barato e rápido usado pelo roteador de histórico |
| `RATE_LIMIT_PER_MINUTE` | `10` | Perguntas por IP de cliente por minuto (web e API; `0` desliga) |
| `RATE_LIMIT_PER_DAY` | `100` | Perguntas por IP de cliente por dia (web e API; `0` desliga) |
| `OPENAI_TIMEOUT` | `60` | Timeout da requisição (segundos) |
| `OPENAI_MAX_RETRIES` | `2` | Novas tentativas em erros transitórios |
| `LOG_LEVEL` | `INFO` | Nível de log |
| `CHAINLIT_SHOW_CHAIN_STEPS` | `false` | Mostra as etapas do LangChain na interface web |
| `CHAINLIT_DATABASE_PATH` | `data/chat_history.db` | Arquivo SQLite com a lista de conversas da interface web |
| `CHAINLIT_AUTH_SECRET` | *(gerado)* | Assina o cookie da sessão web; se vazio, é gerado e salvo em `data/.chainlit_auth_secret` |
| `LANGSMITH_TRACING` | `false` | Liga o rastreamento no LangSmith |
| `LANGSMITH_API_KEY` | | Chave da API do LangSmith |
| `LANGSMITH_PROJECT` | `python-chatbot` | Nome do projeto no LangSmith |
| `LANGSMITH_ENDPOINT` | `https://api.smith.langchain.com` | Endpoint do LangSmith |

O `.env` está no `.gitignore`: nunca versione chaves reais. Se a `OPENAI_API_KEY` estiver
faltando, todas as interfaces param com uma mensagem explicando como configurá-la (a API
responde `503`).

## Instalação

```bash
uv sync
```

## Como rodar

### CLI

```bash
uv run python -m app.cli
```

Comandos: `/help` (lista os comandos), `/clear` (limpa o histórico da conversa),
`/exit` ou `Ctrl+C` (sai). As respostas chegam em streaming e são renderizadas em Markdown,
com destaque de sintaxe no código.

### Interface web

```bash
uv run chainlit run app/ui/chainlit_app.py -w --port 8001
```

Abra <http://localhost:8001>. O Chainlit usa a porta 8000 por padrão, a mesma da API;
`--port 8001` permite rodar os dois ao mesmo tempo. O `-w` recarrega ao mudar o código.

### API

```bash
uv run uvicorn app.api.main:app --reload
```

Documentação interativa (Swagger): <http://localhost:8000/docs>.

```bash
# Começa uma conversa (um session_id é gerado e devolvido)
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Como criar uma lista em Python?"}'

# Pergunta de acompanhamento na mesma conversa
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"session_id": "<session_id da resposta anterior>", "message": "E como adiciono um item nela?"}'

# Limpa a conversa
curl -X DELETE http://localhost:8000/chat/<session_id>

# Health check
curl http://localhost:8000/health
```

| Método | Rota | Descrição | Respostas |
|---|---|---|---|
| `POST` | `/chat` | Faz uma pergunta (`{"session_id"?, "message"}`, mensagem ≤ 5000 caracteres) | `200`, `409` (conversa cheia), `422` (corpo inválido), `429`, `503`, `504` |
| `DELETE` | `/chat/{session_id}` | Limpa uma conversa | `204` |
| `GET` | `/health` | Health check | `200` |

### Com Docker

O [Dockerfile](Dockerfile) gera uma imagem multi-stage com uv que roda a **interface web**
(Chainlit) com usuário não-root na porta 8000, com health check. O histórico de conversas e o
segredo de autenticação gerado ficam em `/app/data`; monte um volume ali para mantê-los entre
reinícios:

```bash
docker build -t python-chatbot .
docker run --rm -p 8000:8000 --env-file .env -v chatbot-data:/app/data python-chatbot
```

Abra <http://localhost:8000>. O `docker-compose.yml` da raiz do repositório roda esta mesma
imagem junto com os outros projetos, atrás de um proxy reverso com HTTPS (veja o
[README da raiz](../../README.md)).

## Interface web

O app Chainlit (`app/ui/chainlit_app.py`) oferece:

- **Perguntas sugeridas** na tela inicial (criar uma lista, lista × tupla, decorators,
  tratamento de exceções), cada uma com um ícone.
- **Streaming**: a resposta aparece token a token, com Markdown e destaque de código.
- **Novo chat**: o botão "Novo chat" começa uma conversa nova; o histórico anterior é
  liberado da memória.
- **Erros amigáveis**: chave inválida, rate limit ou timeout aparecem como mensagem no chat,
  em português.
- **Temas claro e escuro** (alternáveis na interface; cores em `public/theme.json`).
- Exibição opcional das etapas do LangChain (`CHAINLIT_SHOW_CHAIN_STEPS=true`).

A interface tem a marca **"Chatbot de Python DOT Group"** e é exibida em **português do
Brasil** (o bot continua respondendo no idioma de cada pergunta):

- `.chainlit/config.toml`: nome do assistente, `language = "pt-BR"`, tema padrão.
- `.chainlit/translations/pt-BR.json`: os textos do próprio Chainlit (placeholder do campo,
  menus, botões), adaptados da tradução `pt-PT` que vem com ele.
- `chainlit.md`: página de boas-vindas ("Leia-me"), em português.
- `app/ui/helpers.py`: rótulos das sugestões e mensagens de erro em português.
- `public/logo_dark.svg`, `public/logo_light.svg`: logo exibido no lugar do logo do Chainlit.
- `public/avatars/chatbot_de_python_dot_group.svg`: avatar do assistente.
- `public/custom.css`: esconde a caixa de "lista vazia" da lista de conversas.

### Lista de conversas (histórico)

A barra lateral lista as conversas anteriores, que ficam salvas em **SQLite**
(`data/chat_history.db`, criado automaticamente; caminho definido por `CHAINLIT_DATABASE_PATH`).

- O chat é **aberto a todos, sem tela de login**. O Chainlit só mostra a lista para um
  usuário logado, então um `header_auth_callback` loga todo visitante como o mesmo usuário
  compartilhado ("Visitante"). Por isso, **todos os visitantes veem a mesma lista**.
- `app/ui/persistence.py` adapta o `SQLAlchemyDataLayer` do Chainlit ao SQLite (cria as
  tabelas e serializa listas/dicts, que o SQLite não guarda diretamente).
- Ao reabrir uma conversa (`on_chat_resume`), a memória do modelo é reconstruída a partir das
  mensagens salvas, então as perguntas de acompanhamento continuam funcionando.
- O Chainlit assina o cookie de sessão com o `CHAINLIT_AUTH_SECRET`. Se ele não estiver
  definido, um segredo é gerado uma vez e salvo em `data/.chainlit_auth_secret`.

Só a interface web persiste as conversas; a CLI e a API mantêm a memória no processo.

![Interface web do Chainlit](docs/images/chainlit.png)

> Print a ser adicionado em `docs/images/chainlit.png`.

## Rastreamento no LangSmith

O rastreamento é opcional e controlado só por variáveis de ambiente:

```dotenv
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=<sua chave do LangSmith>
LANGSMITH_PROJECT=python-chatbot
```

Rode qualquer interface e abra <https://smith.langchain.com> → *Projects* →
`python-chatbot`. Cada execução se chama `python_tutor_chat` e leva:

- os metadados `session_id` e `interface` (`cli`, `api`, `web` ou `script`);
- as tags `python-tutor` e `interface:<nome>`.

Filtre por eles para acompanhar uma conversa inteira ou comparar interfaces. Cada trace
mostra o histórico completo, o prompt renderizado, a chamada ao modelo (tokens, latência) e a
resposta processada. Sem essas variáveis a aplicação funciona normalmente, sem rastreamento.

## Exemplos

Perguntas e respostas reais são geradas pelo próprio chatbot:

```bash
uv run python scripts/generate_examples.py
```

O script faz uma lista de perguntas (incluindo uma de acompanhamento, que depende da memória, e
uma fora do assunto, que precisa ser recusada) e as grava em
[docs/EXAMPLES.md](docs/EXAMPLES.md). Requer uma `OPENAI_API_KEY` válida.

## Testes e qualidade

Nenhum teste chama a API da OpenAI: um modelo de chat falso do LangChain
(`FakeListChatModel`) é injetado na chain.

```bash
uv run pytest -v --cov=app        # testes + cobertura (falha abaixo de 90%)
uv run ruff check .               # lint
uv run ruff format --check .      # formatação
uv run mypy                       # checagem estática de tipos (modo estrito)
```

## Exemplo de sessão

> Apenas ilustrativo: mostra o formato de uma interação na CLI, não uma saída gravada.
> Veja o [docs/EXAMPLES.md](docs/EXAMPLES.md) para respostas reais.

```text
╭──────────────────────────── 🐍 Python Tutor ─────────────────────────────╮
│ Hi! I'm your Python Tutor. Ask me anything about Python programming, in  │
│ any language.                                                            │
│                                                                          │
│ Try asking:                                                              │
│   • How do I create a list in Python?                                    │
│   • Como criar uma lista em Python?                                      │
│   • What is the difference between a list and a tuple?                   │
│   • What are decorators?                                                 │
│                                                                          │
│ Type /help to see the commands.                                          │
╰──────────────────────────────────────────────────────────────────────────╯
You > Como criar uma lista em Python?
Python Tutor
Uma lista é uma coleção ordenada e mutável. Você pode criá-la com colchetes:

    # Lista com valores iniciais
    frutas = ["maçã", "banana", "laranja"]
    # Lista vazia
    vazia = []
...

You > E como adiciono um item nela?
Python Tutor
Para adicionar um item à lista `frutas`, use o método append():

    frutas.append("uva")  # adiciona ao final
...

You > Qual a capital da França?
Python Tutor
Desculpe, eu só posso ajudar com perguntas sobre programação em Python. Que tal
perguntar, por exemplo, como trabalhar com dicionários em Python?

You > /exit
Goodbye! Keep coding. 👋
```
