# Exemplos de consultas e resultados

Resultados reais gerados por `uv run python scripts/generate_examples.py`, sobre o
índice versionado em `storage/`. Cada consulta foi buscada de duas formas:

- **Busca semântica pura:** só embeddings e FAISS, com a pergunta como foi digitada.
  A nota é a similaridade de cosseno entre a pergunta e o melhor trecho do artigo.
- **Pipeline padrão:** busca híbrida (embeddings + BM25), reordenada pelo
  cross-encoder. A nota é a relevância do cross-encoder, entre 0 e 1.

Nas duas, a reescrita da pergunta pela LLM fica desligada, como na avaliação: ela
varia de uma execução para outra, e os exemplos precisam ser reproduzíveis. O
enriquecimento dos trechos feito pela LLM na ingestão já está no índice.

A coluna **Esperado** marca os artigos que respondem à pergunta, segundo o conjunto
de avaliação ([data/eval/queries.json](../data/eval/queries.json)).

- Modelo de embeddings: `intfloat/multilingual-e5-small`
- Cross-encoder: `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`

## 1. Palavras populares vs. termo técnico

> O usuário diz "prisão de ventre"; o artigo fala em "obstipação".

**Consulta:** `o que comer para acabar com a prisão de ventre`

**Busca semântica pura**

| # | Artigo | Categoria | Cosseno | Esperado |
|---|---|---|---|---|
| 1 | Obstipação (`nut-11`) | nutrition | 0.889 | ✅ |
| 2 | Doença de Parkinson (`chr-14`) | chronic-diseases | 0.884 |  |
| 3 | Diarreia (`nut-12`) | nutrition | 0.878 |  |

**Pipeline padrão**

| # | Artigo | Categoria | Relevância | Esperado |
|---|---|---|---|---|
| 1 | Osteoporose (`chr-08`) | chronic-diseases | 0.850 |  |
| 2 | Obstipação (`nut-11`) | nutrition | 0.674 | ✅ |
| 3 | Diarreia (`nut-12`) | nutrition | 0.339 |  |

Trecho do 1º resultado (Osteoporose):

> Prevenção Fazer exercícios físicos regularmente: os exercícios resistidos são os mais recomendados; Dieta com alimentos ricos em cálcio: 100g de gergelim: 975 mg de cálcio 100g de semente de chia: 1476 mg de cálcio 100g de tofu: 128 mg de cálcio 100g de salsa: 203 mg de cálcio 10…

---

## 2. Pergunta direta

> Pergunta curta, do jeito que se digita num buscador.

**Consulta:** `como controlar a pressão alta`

**Busca semântica pura**

| # | Artigo | Categoria | Cosseno | Esperado |
|---|---|---|---|---|
| 1 | Hipertensão arterial (`chr-01`) | chronic-diseases | 0.882 | ✅ |
| 2 | Desidratação (`nut-03`) | nutrition | 0.876 |  |
| 3 | Meditação (`men-06`) | mental-health | 0.874 |  |

**Pipeline padrão**

| # | Artigo | Categoria | Relevância | Esperado |
|---|---|---|---|---|
| 1 | Hipertensão arterial (`chr-01`) | chronic-diseases | 0.324 | ✅ |
| 2 | Diabetes mellitus (`chr-02`) | chronic-diseases | 0.183 |  |
| 3 | Desidratação (`nut-03`) | nutrition | 0.119 |  |

Trecho do 1º resultado (Hipertensão arterial):

> As alterações no estilo de vida e a medicação permitem diminuir a pressão arterial e o risco de complicações. Entre as alterações no estilo de vida estão perder peso, diminuir o consumo de sal, praticar exercício físico e manter uma dieta saudável. Quando as alterações no estilo…

---

## 3. Sintoma descrito sem o nome da doença

> Nenhuma palavra da pergunta aparece no nome do artigo.

**Consulta:** `tristeza profunda que não passa`

**Busca semântica pura**

| # | Artigo | Categoria | Cosseno | Esperado |
|---|---|---|---|---|
| 1 | Transtorno depressivo maior (`men-02`) | mental-health | 0.883 | ✅ |
| 2 | Síndrome de burnout (`men-04`) | mental-health | 0.874 |  |
| 3 | Diabetes mellitus (`chr-02`) | chronic-diseases | 0.873 |  |

**Pipeline padrão**

| # | Artigo | Categoria | Relevância | Esperado |
|---|---|---|---|---|
| 1 | Apneia do sono (`act-03`) *(baixa relevância)* | sleep-exercise | 0.016 |  |
| 2 | Transtorno depressivo maior (`men-02`) *(baixa relevância)* | mental-health | 0.011 | ✅ |
| 3 | Transtorno de pânico (`men-08`) *(baixa relevância)* | mental-health | 0.010 |  |

Nenhum resultado passou do limite de relevância: a interface mostra o aviso
"nenhum resultado confiável" em vez de apresentar esses artigos como resposta.

---

## 4. Sintomas que apontam um diagnóstico

> A busca precisa ligar a descrição dos sintomas à doença.

**Consulta:** `dor no peito que vai para o braço esquerdo`

**Busca semântica pura**

| # | Artigo | Categoria | Cosseno | Esperado |
|---|---|---|---|---|
| 1 | Insuficiência cardíaca (`chr-17`) | chronic-diseases | 0.899 |  |
| 2 | Doença de refluxo gastroesofágico (`nut-19`) | nutrition | 0.891 |  |
| 3 | Enfarte agudo do miocárdio (`chr-05`) | chronic-diseases | 0.890 | ✅ |

**Pipeline padrão**

| # | Artigo | Categoria | Relevância | Esperado |
|---|---|---|---|---|
| 1 | Enfarte agudo do miocárdio (`chr-05`) | chronic-diseases | 0.133 | ✅ |
| 2 | Artrose (`chr-12`) *(baixa relevância)* | chronic-diseases | 0.030 |  |
| 3 | Insuficiência cardíaca (`chr-17`) *(baixa relevância)* | chronic-diseases | 0.013 |  |

Trecho do 1º resultado (Enfarte agudo do miocárdio):

> Um enfarte agudo do miocárdio (português europeu) ou infarto agudo do miocárdio (português brasileiro), vulgarmente denominado ataque cardíaco, ocorre quando a circulação de sangue para uma parte do coração é interrompida, causando lesões no músculo cardíaco. O sintoma mais comum…

---

## 5. Pergunta em inglês

> O modelo de embeddings é multilíngue: a pergunta em inglês acha artigos em português.

**Consulta:** `tips to improve sleep quality`

**Busca semântica pura**

| # | Artigo | Categoria | Cosseno | Esperado |
|---|---|---|---|---|
| 1 | Higiene do sono (`act-11`) | sleep-exercise | 0.859 | ✅ |
| 2 | Privação de sono (`act-12`) | sleep-exercise | 0.859 |  |
| 3 | Insônia (`act-02`) | sleep-exercise | 0.856 | ✅ |

**Pipeline padrão**

| # | Artigo | Categoria | Relevância | Esperado |
|---|---|---|---|---|
| 1 | Insônia (`act-02`) | sleep-exercise | 0.911 | ✅ |
| 2 | Higiene do sono (`act-11`) | sleep-exercise | 0.840 | ✅ |
| 3 | Privação de sono (`act-12`) | sleep-exercise | 0.470 |  |

Trecho do 1º resultado (Insônia):

> Prevenção > Hábitos Diurnos e Estilo de Vida As atividades realizadas durante o dia influenciam diretamente a capacidade de dormir à noite. As principais práticas preventivas são: Evitar estimulantes: Cafeína, nicotina e outras substâncias estimulantes devem ser evitadas, especia…

---

## 6. Termo exato

> Um nome científico, caso em que a busca por palavras-chave ajuda a semântica.

**Consulta:** `Aedes aegypti`

**Busca semântica pura**

| # | Artigo | Categoria | Cosseno | Esperado |
|---|---|---|---|---|
| 1 | Chicungunha (`inf-15`) | infectious-diseases | 0.903 | ✅ |
| 2 | Dengue (`inf-01`) | infectious-diseases | 0.901 | ✅ |
| 3 | Febre amarela (`inf-09`) | infectious-diseases | 0.884 | ✅ |

**Pipeline padrão**

| # | Artigo | Categoria | Relevância | Esperado |
|---|---|---|---|---|
| 1 | Febre amarela (`inf-09`) | infectious-diseases | 0.753 | ✅ |
| 2 | Dengue (`inf-01`) | infectious-diseases | 0.491 | ✅ |
| 3 | Chicungunha (`inf-15`) | infectious-diseases | 0.359 | ✅ |

Trecho do 1º resultado (Febre amarela):

> Causas > Contaminação Nas áreas urbanas, o Aedes aegypti é o principal vetor, transmitindo o vírus da febre amarela de 9 a 12 dias após ter picado uma pessoa infectada. Esse intervalo, chamado de período de incubação extrínseca, varia de acordo com a temperatura, sendo menor quan…

---

## 7. Assunto fora do acervo

> Nenhum artigo responde. A busca semântica sempre devolve os vizinhos mais próximos; o cross-encoder é que diz que nenhum resultado é confiável.

**Consulta:** `como trocar o óleo do carro`

**Busca semântica pura**

| # | Artigo | Categoria | Cosseno | Esperado |
|---|---|---|---|---|
| 1 | Enxaqueca (`chr-15`) | chronic-diseases | 0.829 |  |
| 2 | Varicela (`inf-20`) | infectious-diseases | 0.827 |  |
| 3 | Melatonina (`act-17`) | sleep-exercise | 0.825 |  |

**Pipeline padrão**

| # | Artigo | Categoria | Relevância | Esperado |
|---|---|---|---|---|
| 1 | Diarreia (`nut-12`) *(baixa relevância)* | nutrition | 0.004 |  |
| 2 | Sódio (`nut-10`) *(baixa relevância)* | nutrition | 0.004 |  |
| 3 | Jet lag (`act-05`) *(baixa relevância)* | sleep-exercise | 0.003 |  |

Nenhum resultado passou do limite de relevância: a interface mostra o aviso
"nenhum resultado confiável" em vez de apresentar esses artigos como resposta.

---

## O que os exemplos mostram

- **O cosseno não separa acerto de erro.** Na busca semântica pura, todas as notas
  ficam entre 0.82 e 0.90, inclusive em "como trocar o óleo do carro" (caso 7).
  Nenhum corte de cosseno consegue dizer "nenhum artigo responde".
- **O cross-encoder separa.** Fora do acervo, as notas caem para perto de zero e a
  interface avisa que não há resultado confiável. Ele também corrige a ordem: no
  caso 4, o infarto sobe do 3º para o 1º lugar.
- **Ele também erra.** No caso 1, Osteoporose fica à frente de Obstipação por falar
  de dieta. No caso 3, o artigo certo aparece, mas abaixo do limite, e a pergunta
  fica sem resposta. Nos dois, a busca semântica pura acertou o 1º lugar.
