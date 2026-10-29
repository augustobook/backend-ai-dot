# Avaliação da busca

Este documento registra como a qualidade da busca é medida, os resultados obtidos e as
decisões tomadas a partir deles. Toda técnica nova só fica no projeto se melhorar (ou
pelo menos não piorar) estes números.

## Como medir

```bash
uv run python scripts/evaluate.py                    # configurações rápidas (sem cross-encoder)
uv run python scripts/evaluate.py --list             # todas as configurações
uv run python scripts/evaluate.py --misses \
    --configs hybrid,hybrid+rerank@20                # quais perguntas cada uma erra
```

- **Conjunto de avaliação:** [data/eval/queries.json](../data/eval/queries.json), 60
  perguntas escritas como um usuário escreveria (50 em linguagem popular, 4 em inglês,
  3 com termo exato), cada uma com o(s) artigo(s) que a respondem.
- **Métricas**, no nível do artigo (o que a busca devolve):
  - **hit@1:** o 1º resultado é um artigo esperado;
  - **hit@5:** um artigo esperado está entre os 5 primeiros;
  - **MRR@10:** média de 1 / posição do primeiro artigo esperado (1º = 1; 2º = 0,5;
    fora do top 10 = 0). Premia achar a resposta **mais acima**, não só achá-la.
- O código ([app/evaluation.py](../app/evaluation.py)) não depende do assunto: para outro
  acervo, basta escrever outro arquivo de perguntas.

## Resultados (29/10/2026)

Índice com 100 artigos e 1.525 trechos, **sem enriquecimento pela LLM** e sem reescrita
da pergunta (não havia chave da OpenAI). CPU Intel de 2012 sem AVX2, PyTorch com 2
threads; numa CPU atual as latências do cross-encoder são bem menores.

| Configuração | hit@1 | hit@5 | MRR@10 | Latência média |
|---|---|---|---|---|
| BM25 | 0,63 | 0,85 | 0,720 | 0,02 s |
| Semântica | 0,53 | 0,80 | 0,655 | 0,13 s |
| **Híbrida (RRF 1:1)** | 0,63 | 0,90 | 0,741 | 0,08 s |
| Híbrida, semântica com peso 2 | 0,62 | 0,88 | 0,735 | 0,09 s |
| Híbrida, BM25 com peso 2 | 0,60 | 0,88 | 0,726 | 0,08 s |
| Híbrida + cross-encoder, 10 candidatos | 0,72 | 0,90 | 0,793 | 5,9 s |
| **Híbrida + cross-encoder, 20 candidatos** | **0,77** | 0,92 | **0,840** | 10,3 s |
| Híbrida + cross-encoder, 30 candidatos | 0,75 | **0,93** | 0,834 | 17,4 s |

Experimento descartado (mesmo conjunto, mesmo índice):

| Configuração | hit@1 | hit@5 | MRR@10 |
|---|---|---|---|
| BM25 com stemming (Snowball) | 0,60 | 0,77 | 0,684 |
| Híbrida com stemming | 0,57 | 0,83 | 0,691 |

## Decisões

| Técnica | Resultado | Decisão |
|---|---|---|
| Busca híbrida (BM25 + semântica) | hit@5 0,90, contra 0,85 (BM25) e 0,80 (semântica) | **Mantida** |
| Pesos do RRF diferentes de 1:1 | 0,88 nos dois casos; não melhora | **Mantido 1:1** |
| Cross-encoder | hit@1 0,63 → 0,77 e MRR 0,741 → 0,840 | **Mantido** |
| Candidatos do cross-encoder | 20 empata com 30 (MRR 0,840 × 0,834) com 40% menos tempo; 10 perde (0,793) | **Padrão passou de 30 para 20** |
| Stemming no BM25 | hit@5 cai 0,85 → 0,77 (BM25) e 0,90 → 0,83 (híbrida) | **Removido** |
| Cross-encoder quantizado (int8) | sem ganho de velocidade nem de memória nesta CPU, e as notas mudaram até 0,09 | **Não implementado** |
| `multilingual-e5-base` no lugar do e5-small | ~10× mais lento por pergunta, 1,9 GB, e não resolveu o vocabulário popular | **Descartado** |

Por que o stemming piorou: num acervo pequeno, reduzir as palavras ao radical junta
palavras demais ("comer" e "coma" viram `com`), e as palavras comuns da pergunta
passam a casar com muito mais trechos.

## O que ainda erra

A melhor configuração (híbrida + cross-encoder com 20 candidatos) erra 5 perguntas no
top 5. Todas são de vocabulário popular que nenhum artigo usa:

| Pergunta | Esperado | Veio em 1º |
|---|---|---|
| rosto torto e fala enrolada de repente | AVC (`chr-04`) | Fibromialgia |
| ardência ao fazer xixi | Infecção urinária (`inf-18`) | Higiene do sono |
| beber demais todo dia e não conseguir parar | Alcoolismo (`men-15`) | Privação de sono |
| dor no corpo todo e cansaço sem causa aparente | Fibromialgia (`chr-19`), 6º lugar | AVC |
| pegar no sono de dia sem conseguir evitar | Narcolepsia (`act-13`) | Privação de sono |

São exatamente os casos que o enriquecimento (termos semelhantes e perguntas geradas) e
a reescrita da pergunta pela LLM foram feitos para resolver.

## Ainda não medido

Sem `OPENAI_API_KEY`, nada que depende da LLM foi avaliado:

- enriquecimento dos trechos (contexto, termos semelhantes, perguntas geradas);
- índice de perguntas;
- reescrita da pergunta e multi-query;
- reforço por metadados.

Para medir: ponha a chave no `.env`, rode `uv run python -m app.cli ingest` (com
enriquecimento) e depois

```bash
uv run python scripts/evaluate.py --configs hybrid,hybrid+rerank@20,hybrid+rewrite,hybrid+rewrite+rerank@20
```

Pela regra deste documento, cada uma dessas peças que não melhorar os números deve ser
desligada ou removida.

A expansão para trechos vizinhos (`context_text`) e o limite de relevância não mudam a
ordem dos resultados, então não aparecem nestas métricas: a primeira afeta só o texto
entregue a um RAG, e o segundo só a forma de exibir os resultados fracos.

## Ressalvas

- **60 perguntas é pouco.** Cada pergunta vale 1,7 ponto de hit@5. Diferenças de 0,02
  (uma pergunta) são ruído: provam que algo não melhorou, não que piorou. As decisões
  acima se apoiam em diferenças de pelo menos 3 perguntas, exceto o 1:1 do RRF, que foi
  mantido por falta de ganho.
- **As perguntas foram escritas por quem conhece o acervo.** O ideal é acrescentar
  perguntas reais de usuários, principalmente as que dão errado na interface.
- **Os números valem para este acervo e estes modelos.** Em outro acervo, as conclusões
  (o stemming, por exemplo) podem se inverter; o processo de medir é que se repete.
