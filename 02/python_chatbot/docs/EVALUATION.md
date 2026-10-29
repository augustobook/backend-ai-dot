# Avaliação do Python Tutor

Este documento registra como o chatbot é avaliado com o modelo real, os resultados e as
decisões tomadas a partir deles: o **roteador de histórico** (vale o custo?), o **limite de
64 mil tokens por conversa** e o **comportamento do tutor** (idioma, escopo, segurança).

## Como medir

```bash
uv run python scripts/evaluate.py                   # roteador + comportamento
uv run python scripts/evaluate.py --skip-behavior   # só o roteador
uv run python scripts/evaluate.py --skip-router     # só o comportamento
```

Exige `OPENAI_API_KEY`; uma rodada completa faz cerca de 50 perguntas e custa poucos
centavos de dólar com o `gpt-4o-mini`. A lógica que não chama a OpenAI (conjuntos, métricas,
custos, tabelas) fica em [app/evaluation.py](../app/evaluation.py) e tem testes offline.

- **Conversas do roteador:** [evals/conversations.json](../evals/conversations.json), 6
  conversas de 5 perguntas (3 em português, 3 em inglês). As 24 perguntas a partir da segunda
  têm um rótulo escrito à mão: precisa do histórico (13, por exemplo "E como adiciono e
  removo itens dela?") ou é independente (11, por exemplo "O que são type hints em Python?").
- **Casos de comportamento:** [evals/behavior.json](../evals/behavior.json), 18 perguntas:
  7 de Python (devem ser respondidas), 5 fora de Python, 3 de prompt injection e 1 de código
  malicioso (devem ser recusadas), e 2 com um segredo colado (devem ser respondidas sem
  repetir o segredo).
- **Juiz:** o `gpt-4o-mini` com temperatura 0 e saída estruturada classifica cada resposta
  (recusou ou respondeu; idioma do texto). O vazamento de segredo e do prompt de sistema é
  checado por comparação de texto, sem juiz.

Preços usados (tabela da OpenAI, US$ por milhão de tokens): `gpt-4o-mini` 0,15 na entrada,
0,075 na entrada servida do cache e 0,60 na saída.

## Roteador de histórico

**Como foi medido.** O tutor responde às 6 conversas **sempre com o histórico completo** (a
linha de base). Antes de cada pergunta a partir da segunda, o roteador decide se ela precisa
do histórico, na mesma conversa. Assim, o acerto é comparado com o rótulo, e a economia é
exatamente o histórico que ele teria deixado de enviar.

### Resultado (`gpt-4o-mini` como roteador, 29/10/2026)

| Métrica | Valor |
|---|---|
| Acerto | 92% (22 de 24) |
| Follow-up respondido sem histórico (o erro que estraga a resposta) | **0** |
| Histórico enviado à toa (só perde a economia) | 2 |
| Latência do roteador | média 1,04 s, p95 1,52 s |
| Tokens economizados no tutor, por pergunta | 532 |
| Tokens gastos pelo roteador, por pergunta | 631 |
| Custo do roteador, por 1.000 perguntas | US$ 0,105 |
| Economia no tutor, por 1.000 perguntas | US$ 0,080 sem cache; **US$ 0,046** com o cache medido |
| **Saldo, por 1.000 perguntas** | **US$ −0,060** (custa mais do que economiza) |

As duas perguntas com histórico à toa foram "Qual a diferença entre lista e tupla?" e "Why is
a bare except considered bad practice in Python?": independentes, mas no mesmo assunto da
conversa, e o roteador foi conservador ("na dúvida, envie").

**Por que economiza tão pouco.** A OpenAI guarda em cache o começo repetido dos prompts, e numa
conversa o começo (prompt de sistema + histórico) é sempre o mesmo da pergunta anterior: **86%
dos tokens de entrada do tutor vieram do cache**, pela metade do preço. Reenviar o histórico
já é barato, e o roteador gasta ~630 tokens por pergunta para economizar uma parte disso.

**Quando passa a compensar.** O custo do roteador é fixo por pergunta; a economia cresce com o
histórico. Com a taxa de perguntas independentes medida (9 de 24) e o cache de 86%, o
roteador empata no custo quando o histórico passa de **~3.300 tokens** (umas 6 perguntas).
Perto do limite de 64 mil tokens, ele economizaria cerca de US$ 2 por 1.000 perguntas.

### Decisão

**O roteador passou a vir desligado** (`HISTORY_ROUTER_ENABLED=false`): o histórico completo é
sempre enviado.

- **Latência:** ele acrescenta ~1 s antes de **toda** resposta. Com streaming, o primeiro
  pedaço da resposta chega bem antes dos 4,75 s da resposta completa, então esse segundo é
  sentido em toda pergunta.
- **Custo:** nas conversas medidas, ele custa mais do que economiza. A economia só aparece em
  conversas longas, e mesmo assim é de centavos por mil perguntas.
- **Risco:** desligado, não existe o erro de responder um follow-up sem contexto.

O código continua no projeto (com testes), para ligar em cenários de conversas longas ou com
um modelo tutor caro, em que o histórico pesa mais. O `gpt-4.1-nano`, o roteador mais barato
sem raciocínio, foi descontinuado pela OpenAI; os nanos da família `gpt-5` são modelos de
raciocínio (não aceitam temperatura 0 e "pensam" antes de responder), o que aumentaria a
latência, que já é o problema.

## Limite da conversa: 64 mil tokens

Medido nas mesmas 30 respostas: o prompt de sistema tem **680 tokens** e cada pergunta com a
resposta acrescenta, em média, **516 tokens** ao histórico.

| Limite | Perguntas que cabem numa conversa |
|---|---|
| 123.904 (janela de 128k menos a resposta máxima, o limite antigo) | ~238 |
| **64.000 (novo padrão)** | **~122** |

Por que 64 mil:

- **Custo das últimas perguntas.** Todo o histórico vai em cada pergunta, então quanto mais
  longa a conversa, mais cara cada pergunta. No limite antigo, uma pergunta podia levar ~124
  mil tokens de entrada (~US$ 0,019 sem cache); com 64 mil, no máximo a metade. Com o limite
  de 100 perguntas por dia por IP, isso também corta pela metade o pior caso de gasto de um
  cliente.
- **Qualidade.** Modelos perdem precisão em contextos muito longos: informações no meio de um
  prompt enorme são mais ignoradas ("lost in the middle"). Com 64 mil, o prompt fica na
  metade da janela.
- **Latência.** O tempo até o primeiro pedaço da resposta cresce com o tamanho do prompt.
- **Não atrapalha o uso real.** ~122 perguntas numa só conversa é muito mais do que uma sessão
  de estudo. Quem chega lá é avisado aos 80% e começa uma conversa nova; o histórico antigo
  continua salvo.

O limite é configurável (`MAX_CONVERSATION_TOKENS`), e a configuração recusa um valor que,
somado à resposta máxima (`OPENAI_MAX_TOKENS`), não caiba na janela do modelo.

## Comportamento do tutor

| Tipo de caso | 1ª rodada | Depois das correções |
|---|---|---|
| Pergunta de Python (deve responder) | 4/7 | **7/7** |
| Fora de Python (deve recusar) | 3/5 | **5/5** |
| Prompt injection (deve recusar) | 2/3 | **3/3** |
| Código malicioso (deve recusar) | 1/1 | **1/1** |
| Segredo colado na pergunta (responde sem repetir) | 0/2 | **2/2** |
| **Total** | **10/18** | **18/18** |

A primeira rodada achou dois problemas reais, que os testes offline não pegam (eles usam um
modelo falso):

1. **Perguntas em inglês respondidas em português.** Todas as falhas de Python, fora de
   Python e injection da 1ª rodada eram isso: a decisão (responder ou recusar) estava certa,
   o idioma não. O prompt citava o português como exemplo ("a question in Portuguese gets an
   answer in Portuguese") e trazia o nome em português do tutor, e isso puxava o
   `gpt-4o-mini` para o português. Variantes testadas (perguntas em inglês respondidas em
   inglês):

   | Regra de idioma | Acertos |
   |---|---|
   | Original (só o português como exemplo) | 0 de 7 |
   | Citando os dois sentidos (inglês → inglês, português → português) | 4 de 7; 6 de 8 num segundo teste |
   | Dois sentidos, sem o nome do tutor em português | 4 de 8 |
   | Dois sentidos + um lembrete no fim do prompt | 2 de 8 |
   | **Regra curta, sem citar idioma nenhum** | **6 de 6** (e 4 de 4 em português) |

   Sem regra nenhuma, o modelo também acertou 10 de 10: ele já responde no idioma da
   pergunta, e o que atrapalhava era o exemplo. **Correção:** a regra virou uma frase só,
   "Reply in the same language the user wrote their latest message in", sem citar idiomas
   (ela continua no prompt, porque deixa explícito o que se espera). Um teste garante que o
   prompt não volte a citar o português. Na rodada final, as 7 perguntas em inglês foram
   respondidas em inglês.
2. **O tutor repetia o segredo colado.** Ele avisava para revogar a chave e, logo depois,
   colava a própria chave num exemplo `export OPENAI_API_KEY="sk-proj-..."`. Reforçar a regra
   no prompt não resolveu (0/2 nas duas versões). **Correção no código, não no prompt:**
   [app/core/redaction.py](../app/core/redaction.py) troca segredos conhecidos (chaves da
   OpenAI, GitHub, AWS e Google, senhas em URLs, `password=...`, chaves privadas) por
   `[REDACTED]` antes de a pergunta ir para o modelo. Assim, o segredo também não vai para a
   OpenAI, para o histórico nem para o LangSmith. O prompt explica o `[REDACTED]` ao modelo,
   que continua avisando o usuário para revogar a chave.

**Cuidado com a leitura.** As correções foram feitas olhando estes mesmos 18 casos, então o
18/18 mostra que os problemas encontrados foram resolvidos, não que o tutor acerta 100% em
qualquer pergunta. São poucos casos (cada um vale 5,6 pontos percentuais), e o juiz é um
modelo da mesma família do tutor.
