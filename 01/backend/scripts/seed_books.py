"""Cadastra 25 livros de exemplo, todos em língua portuguesa, pela Library API.

São 10 clássicos e 15 livros publicados depois de 2000. Usa só a biblioteca
padrão, então roda com `python` puro ou com `uv run`:

    uv run python scripts/seed_books.py
    uv run python scripts/seed_books.py --grupo recentes
    uv run python scripts/seed_books.py --base-url https://api.exemplo --api-key <chave>

A URL e a chave vêm, por padrão, das variáveis de ambiente `API_BASE_URL` e
`API_KEY` (senão, `http://localhost:8000` e sem chave). Os livros passam por
`POST /books`, então a API os valida como faria com qualquer cliente. Rodar o
script duas vezes cadastra os livros duas vezes: a API não remove duplicados.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

DEFAULT_BASE_URL = "http://localhost:8000"

# Clássicos escritos originalmente em português (Brasil e Portugal).
CLASSIC_BOOKS: list[dict[str, str]] = [
    {
        "title": "Dom Casmurro",
        "author": "Machado de Assis",
        "publication_date": "1899-12-01",
        "summary": "Bentinho, já velho, narra o amor por Capitu e o ciúme que o faz duvidar "
        "da fidelidade dela e da paternidade do filho.",
    },
    {
        "title": "Memórias Póstumas de Brás Cubas",
        "author": "Machado de Assis",
        "publication_date": "1881-01-01",
        "summary": "Um defunto autor conta a própria vida com ironia, expondo a vaidade "
        "e a hipocrisia da elite do Rio de Janeiro do século XIX.",
    },
    {
        "title": "Grande Sertão: Veredas",
        "author": "João Guimarães Rosa",
        "publication_date": "1956-01-01",
        "summary": "O ex-jagunço Riobaldo relembra as travessias pelo sertão, a guerra entre "
        "bandos e o amor por Diadorim.",
    },
    {
        "title": "Vidas Secas",
        "author": "Graciliano Ramos",
        "publication_date": "1938-01-01",
        "summary": "Uma família de retirantes atravessa o sertão nordestino fugindo da seca, "
        "em busca de trabalho e dignidade.",
    },
    {
        "title": "A Hora da Estrela",
        "author": "Clarice Lispector",
        "publication_date": "1977-10-01",
        "summary": "O narrador Rodrigo S.M. conta a vida de Macabéa, nordestina pobre e "
        "solitária no Rio de Janeiro.",
    },
    {
        "title": "Capitães da Areia",
        "author": "Jorge Amado",
        "publication_date": "1937-01-01",
        "summary": "Meninos abandonados vivem de pequenos furtos nas ruas de Salvador, "
        "liderados por Pedro Bala.",
    },
    {
        "title": "O Cortiço",
        "author": "Aluísio Azevedo",
        "publication_date": "1890-01-01",
        "summary": "A vida coletiva de um cortiço no Rio de Janeiro e a ambição de João "
        "Romão, seu dono, retratadas pelo olhar naturalista.",
    },
    {
        "title": "Iracema",
        "author": "José de Alencar",
        "publication_date": "1865-01-01",
        "summary": "A índia tabajara Iracema se apaixona pelo português Martim, numa lenda "
        "sobre a origem do Ceará.",
    },
    {
        "title": "Macunaíma",
        "author": "Mário de Andrade",
        "publication_date": "1928-07-26",
        "summary": "O herói sem nenhum caráter sai da floresta para São Paulo em busca da "
        "muiraquitã, num retrato bem-humorado do Brasil.",
    },
    {
        "title": "Ensaio sobre a Cegueira",
        "author": "José Saramago",
        "publication_date": "1995-01-01",
        "summary": "Uma epidemia de cegueira branca se espalha por uma cidade e expõe o que "
        "resta de humano quando a ordem desaba.",
    },
]

# Livros em língua portuguesa publicados depois de 2000.
RECENT_BOOKS: list[dict[str, str]] = [
    {
        "title": "Budapeste",
        "author": "Chico Buarque",
        "publication_date": "2003-01-01",
        "summary": "José Costa, escritor-fantasma carioca, divide a vida entre o Rio de "
        "Janeiro e Budapeste, onde aprende o húngaro.",
    },
    {
        "title": "O Vendedor de Passados",
        "author": "José Eduardo Agualusa",
        "publication_date": "2004-01-01",
        "summary": "Em Luanda, Félix Ventura vende genealogias inventadas a novos-ricos, "
        "numa história narrada por uma osga.",
    },
    {
        "title": "As Intermitências da Morte",
        "author": "José Saramago",
        "publication_date": "2005-01-01",
        "summary": "Num país sem nome, as pessoas deixam de morrer, e o fim da morte vira um "
        "problema político, religioso e econômico.",
    },
    {
        "title": "Um Defeito de Cor",
        "author": "Ana Maria Gonçalves",
        "publication_date": "2006-01-01",
        "summary": "Kehinde, capturada na África e escravizada no Brasil, conta a própria "
        "vida enquanto procura o filho perdido.",
    },
    {
        "title": "Leite Derramado",
        "author": "Chico Buarque",
        "publication_date": "2009-01-01",
        "summary": "Um homem centenário, num leito de hospital, relembra a decadência da "
        "família entre memórias e delírios.",
    },
    {
        "title": "Caim",
        "author": "José Saramago",
        "publication_date": "2009-01-01",
        "summary": "Releitura irônica do Antigo Testamento em que Caim vaga pelo tempo e "
        "testemunha episódios bíblicos.",
    },
    {
        "title": "O Filho de Mil Homens",
        "author": "Valter Hugo Mãe",
        "publication_date": "2011-01-01",
        "summary": "Crisóstomo, um pescador de quarenta anos que deseja ter um filho, reúne "
        "à sua volta uma família improvável.",
    },
    {
        "title": "Diário da Queda",
        "author": "Michel Laub",
        "publication_date": "2011-01-01",
        "summary": "Um homem revisita um episódio de violência na escola e a relação com o "
        "pai e o avô, sobrevivente de Auschwitz.",
    },
    {
        "title": "Tudo é Rio",
        "author": "Carla Madeira",
        "publication_date": "2014-01-01",
        "summary": "Dalva, Venâncio e Lucy vivem um triângulo marcado por uma tragédia, "
        "pela culpa e pela possibilidade do perdão.",
    },
    {
        "title": "Ainda Estou Aqui",
        "author": "Marcelo Rubens Paiva",
        "publication_date": "2015-01-01",
        "summary": "O autor narra o desaparecimento do pai durante a ditadura militar e a "
        "luta da mãe, Eunice Paiva, por respostas.",
    },
    {
        "title": "A Vida Invisível de Eurídice Gusmão",
        "author": "Martha Batalha",
        "publication_date": "2016-01-01",
        "summary": "Duas irmãs no Rio de Janeiro dos anos 1940 veem os próprios sonhos "
        "sufocados pelo machismo da época.",
    },
    {
        "title": "Torto Arado",
        "author": "Itamar Vieira Junior",
        "publication_date": "2019-01-01",
        "summary": "As irmãs Bibiana e Belonísia crescem numa fazenda do sertão baiano onde "
        "descendentes de escravizados trabalham sem direitos.",
    },
    {
        "title": "O Avesso da Pele",
        "author": "Jeferson Tenório",
        "publication_date": "2020-01-01",
        "summary": "Pedro reconstrói a história do pai, um professor negro morto numa "
        "abordagem policial em Porto Alegre.",
    },
    {
        "title": "O Som do Rugido da Onça",
        "author": "Micheliny Verunschk",
        "publication_date": "2021-01-01",
        "summary": "Duas crianças indígenas levadas à Europa por naturalistas no século XIX "
        "têm sua história reencontrada no presente.",
    },
    {
        "title": "Salvar o Fogo",
        "author": "Itamar Vieira Junior",
        "publication_date": "2023-01-01",
        "summary": "No povoado de Tapera do Paraguaçu, na Bahia, a lavadeira Luzia e o irmão "
        "Moisés enfrentam a herança de violência de um mosteiro.",
    },
]

BOOK_GROUPS: dict[str, list[dict[str, str]]] = {
    "classicos": CLASSIC_BOOKS,
    "recentes": RECENT_BOOKS,
    "todos": CLASSIC_BOOKS + RECENT_BOOKS,
}


def post_book(base_url: str, api_key: str | None, book: dict[str, str]) -> dict[str, Any]:
    """Cadastra um livro com `POST /books`.

    Args:
        base_url: URL da API, sem barra no final.
        api_key: Valor do cabeçalho `X-API-Key`, ou `None` quando a API não exige chave.
        book: Os dados do livro.

    Returns:
        O livro devolvido pela API (com o `id`).

    Raises:
        urllib.error.HTTPError: Quando a API responde com status de erro.
        urllib.error.URLError: Quando não é possível conectar à API.
    """
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key
    request = urllib.request.Request(
        f"{base_url}/books",
        data=json.dumps(book).encode(),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        created: dict[str, Any] = json.loads(response.read())
        return created


def main(argv: list[str] | None = None) -> int:
    """Cadastra os livros do grupo escolhido e mostra o resultado de cada requisição.

    Args:
        argv: Argumentos de linha de comando (padrão: `sys.argv[1:]`).

    Returns:
        O código de saída: 0 se todos os livros foram cadastrados, 1 caso contrário.
    """
    parser = argparse.ArgumentParser(description="Cadastra livros de exemplo pela API.")
    parser.add_argument(
        "--grupo",
        choices=sorted(BOOK_GROUPS),
        default="todos",
        help="quais livros cadastrar: os 10 clássicos, os 15 recentes ou todos "
        "(padrão: %(default)s)",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("API_BASE_URL", DEFAULT_BASE_URL),
        help="URL da API (padrão: $API_BASE_URL ou %(default)s)",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("API_KEY") or None,
        help="valor do cabeçalho X-API-Key (padrão: $API_KEY)",
    )
    args = parser.parse_args(argv)
    base_url = args.base_url.rstrip("/")
    books = BOOK_GROUPS[args.grupo]

    failures = 0
    for book in books:
        try:
            created = post_book(base_url, args.api_key, book)
        except urllib.error.HTTPError as exc:
            failures += 1
            print(f"ERRO {exc.code}  {book['title']}: {exc.read().decode(errors='replace')}")
        except urllib.error.URLError as exc:
            print(f"Não foi possível conectar a {base_url}: {exc.reason}")
            return 1
        else:
            print(f"OK  #{created['id']:<4} {created['title']} ({created['author']})")

    print(f"\n{len(books) - failures} de {len(books)} livros cadastrados em {base_url}.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
