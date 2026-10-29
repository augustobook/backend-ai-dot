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

## Resultados sem LLM (29/10/2026, manhã)

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

## Resultados com o índice enriquecido (29/10/2026, tarde)

Índice com 1.477 trechos (caminho de títulos, seções pequenas unidas), **enriquecido
pelo `gpt-5-nano`** (contexto, termos semelhantes e 7.162 perguntas geradas). Reescrita
da pergunta **desligada** em todas as medições abaixo, para isolar cada etapa.

### Cada etapa

| Configuração | hit@1 | hit@5 | MRR@10 |
|---|---|---|---|
| BM25 | 0,70 | 0,88 | 0,786 |
| Semântica | 0,57 | 0,85 | 0,676 |
| Híbrida (RRF 1:1) | 0,63 | 0,90 | 0,750 |
| Híbrida, BM25 com peso 2 | 0,70 | 0,88 | 0,786 |
| Híbrida, BM25 com peso 3 | 0,68 | 0,88 | 0,781 |

O enriquecimento fortaleceu muito o BM25 (hit@1 0,63 → 0,70), porque os termos
semelhantes e as perguntas geradas trazem as palavras dos usuários. Com isso, a fusão
1:1 passou a puxar o 1º lugar para baixo (0,70 → 0,63), e só ganha uma pergunta no top 5.
Peso 2 para o BM25 recupera o topo **antes** do cross-encoder; ainda falta medir se o
ganho continua **depois** dele, que é o que aparece na tela.

### Texto juntado × independente

O bloco escrito pela LLM ("Contexto: … Termos semelhantes: … Perguntas: …") era
anexado ao trecho e usado em três lugares: vetor do trecho, BM25 e cross-encoder. O
BM25 continua usando o texto juntado; o vetor e o cross-encoder foram testados com e
sem o bloco (híbrida 1:1 + cross-encoder com 20 candidatos):

| Vetor do trecho | Cross-encoder lê | hit@1 | hit@5 | MRR@10 |
|---|---|---|---|---|
| trecho + bloco | trecho + bloco | 0,73 | 0,92 | 0,806 |
| trecho + bloco | trecho original | **0,78** | 0,92 | **0,849** |
| trecho original | trecho + bloco | 0,72 | 0,92 | 0,799 |
| **trecho original** | **trecho original** | 0,77 | **0,93** | 0,847 |

- **Cross-encoder:** lendo só o trecho original, acerta 3 perguntas a mais em 1º lugar,
  com qualquer versão do vetor (e o resultado se repetiu em duas medições). Um texto
  "Contexto: … Termos: … Perguntas: …" não se parece com os pares pergunta → trecho
  com que o modelo foi treinado.
- **Vetor do trecho:** empate (diferenças de uma pergunta). As perguntas geradas já têm
  vetores próprios no `questions.faiss`, então colá-las no vetor do trecho não acrescenta.

### Calibração do limite de relevância

Nota do cross-encoder (lendo o trecho original) para o 1º resultado: nas 47 perguntas
em que ele está certo, e em 10 perguntas **fora do acervo** ("como trocar o pneu do
carro", "receita de bolo de chocolate", "como declarar o imposto de renda",
"how to fix a flat tire"...):

| | mínima | mediana | máxima |
|---|---|---|---|
| 1º resultado certo | 0,026 | 0,486 | 1,000 |
| Pergunta fora do acervo | 0,000 | 0,014 | 0,036 |

| Limite | Respostas certas exibidas | Perguntas fora do acervo bloqueadas |
|---|---|---|
| 0,30 (antigo) | 64% | 100% |
| 0,10 | 83% | 100% |
| **0,05 (novo padrão)** | **96%** | **100%** |
| 0,03 | 98% | 90% |

Com 0,3, um terço das respostas certas aparecia como "baixa relevância". Era o caso de
"tristeza profunda que não passa": Transtorno depressivo maior em 1º lugar, com nota
0,026, e a tela dizendo "Nenhum resultado confiável".

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
| Cross-encoder lendo o bloco da LLM | hit@1 0,78 → 0,73 e MRR 0,849 → 0,806 | **Passou a ler só o trecho original** |
| Vetor do trecho com o bloco da LLM | empate com o trecho original | **Só o trecho original** (separação mais limpa; as perguntas já têm vetor próprio) |
| Limite de relevância 0,3 | exibia só 64% das respostas certas | **Passou para 0,05** (96% exibidas, 100% fora do acervo bloqueadas) |
| Caminho de títulos, sem trechos só de título | 35 trechos eram uma palavra ("Causas") | **Corrigido** (correção de bug; não depende de métrica) |

Por que o stemming piorou: num acervo pequeno, reduzir as palavras ao radical junta
palavras demais ("comer" e "coma" viram `com`), e as palavras comuns da pergunta
passam a casar com muito mais trechos.
