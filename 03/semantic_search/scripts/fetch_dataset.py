"""Download the real documents of the dataset into `data/documents/`.

The dataset is made of 100 health articles from the Portuguese Wikipedia, licensed
under CC BY-SA 4.0 (redistribution and adaptation allowed with attribution and the
same license). They are fetched as plain text through the official MediaWiki API.

Each article becomes a Markdown file with a YAML front matter recording where it came
from (URL, revision id, license, retrieval date). Reference-only sections
(references, external links...) are dropped and long articles are cut at a section
boundary, so every document has a comparable size; the front matter says so.

The files are committed to the repository, so the project works offline; this script
only exists to make the dataset reproducible:

    uv run python scripts/fetch_dataset.py            # every document
    uv run python scripts/fetch_dataset.py nut-01     # only some ids
"""

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import yaml

DOCUMENTS_DIR = Path("data/documents")
USER_AGENT = "semantic-search-demo/0.1 (educational project)"
WIKIPEDIA_API = "https://pt.wikipedia.org/w/api.php"
LICENSE = "CC BY-SA 4.0"
LICENSE_URL = "https://creativecommons.org/licenses/by-sa/4.0/deed.pt-br"
AUTHOR = "Colaboradores da Wikipédia"
PAUSE_SECONDS = 2.0
MAX_WORDS = 2000
MIN_WORDS = 300

# Sections that only list references or links: there is nothing to search in them.
SKIPPED_SECTIONS = {
    "referências",
    "referencias",
    "ligações externas",
    "ver também",
    "bibliografia",
    "notas",
    "notas e referências",
    "leitura adicional",
    "leituras adicionais",
    "galeria",
    "fontes",
    "obras citadas",
}


@dataclass(frozen=True)
class Entry:
    """One document of the catalog.

    Attributes:
        id: Document id (`<prefix>-<nn>`).
        slug: File name slug (Portuguese, no accents).
        category: English category slug (an identifier used by the code).
        title: Wikipedia article title.
        tags: Portuguese tags (3 to 5).
    """

    id: str
    slug: str
    category: str
    title: str
    tags: tuple[str, ...]


def entry(doc_id: str, slug: str, category: str, title: str, *tags: str) -> Entry:
    """Build a catalog entry."""
    return Entry(doc_id, slug, category, title, tags)


CATALOG: list[Entry] = [
    # --- Nutrition -------------------------------------------------------------------
    entry("nut-01", "nutricao", "nutrition", "Nutrição", "nutrição", "alimentação", "nutrientes"),
    entry("nut-02", "obesidade", "nutrition", "Obesidade", "obesidade", "peso corporal", "imc"),
    entry(
        "nut-03", "desidratacao", "nutrition", "Desidratação", "hidratação", "água", "eletrólitos"
    ),
    entry(
        "nut-04",
        "fibra-alimentar",
        "nutrition",
        "Fibra alimentar",
        "fibras",
        "digestão",
        "alimentação",
    ),
    entry("nut-05", "vitamina-d", "nutrition", "Vitamina D", "vitaminas", "sol", "ossos"),
    entry(
        "nut-06",
        "dieta-mediterranica",
        "nutrition",
        "Dieta mediterrânica",
        "padrão alimentar",
        "azeite",
        "prevenção",
    ),
    entry(
        "nut-07",
        "vegetarianismo",
        "nutrition",
        "Vegetarianismo",
        "vegetarianismo",
        "proteína vegetal",
        "alimentação",
    ),
    entry(
        "nut-08", "anemia-ferropriva", "nutrition", "Anemia ferropriva", "anemia", "ferro", "sangue"
    ),
    entry(
        "nut-09",
        "desnutricao",
        "nutrition",
        "Desnutrição",
        "desnutrição",
        "carências nutricionais",
        "fome",
    ),
    entry("nut-10", "sodio", "nutrition", "Sódio", "sódio", "sal", "minerais"),
    entry(
        "nut-11",
        "constipacao-intestinal",
        "nutrition",
        "Constipação intestinal",
        "intestino",
        "digestão",
        "fibras",
    ),
    entry("nut-12", "diarreia", "nutrition", "Diarreia", "diarreia", "intestino", "hidratação"),
    entry(
        "nut-13",
        "intolerancia-a-lactose",
        "nutrition",
        "Intolerância à lactose",
        "lactose",
        "leite",
        "digestão",
    ),
    entry(
        "nut-14", "doenca-celiaca", "nutrition", "Doença celíaca", "glúten", "intestino", "dieta"
    ),
    entry(
        "nut-15", "probiotico", "nutrition", "Probiótico", "probióticos", "microbiota", "intestino"
    ),
    entry("nut-16", "vitamina-c", "nutrition", "Vitamina C", "vitaminas", "frutas", "imunidade"),
    entry("nut-17", "vitamina-b12", "nutrition", "Vitamina B12", "vitaminas", "anemia", "carne"),
    entry("nut-18", "omega-3", "nutrition", "Ômega 3", "gorduras", "peixe", "coração"),
    entry(
        "nut-19",
        "refluxo-gastroesofagico",
        "nutrition",
        "Doença do refluxo gastroesofágico",
        "refluxo",
        "azia",
        "estômago",
    ),
    entry("nut-20", "gastrite", "nutrition", "Gastrite", "gastrite", "estômago", "digestão"),
    # --- Mental health -----------------------------------------------------------------
    entry(
        "men-01", "ansiedade", "mental-health", "Ansiedade", "ansiedade", "emoções", "saúde mental"
    ),
    entry(
        "men-02",
        "depressao",
        "mental-health",
        "Transtorno depressivo maior",
        "depressão",
        "humor",
        "saúde mental",
    ),
    entry(
        "men-03",
        "transtorno-de-ansiedade-generalizada",
        "mental-health",
        "Transtorno de ansiedade generalizada",
        "ansiedade",
        "preocupação",
        "transtornos mentais",
    ),
    entry(
        "men-04",
        "sindrome-de-burnout",
        "mental-health",
        "Síndrome de burnout",
        "burnout",
        "trabalho",
        "esgotamento",
    ),
    entry("men-05", "estresse", "mental-health", "Estresse", "estresse", "tensão", "saúde mental"),
    entry(
        "men-06", "meditacao", "mental-health", "Meditação", "meditação", "atenção", "relaxamento"
    ),
    entry(
        "men-07",
        "atencao-plena",
        "mental-health",
        "Atenção plena",
        "mindfulness",
        "atenção plena",
        "bem-estar",
    ),
    entry(
        "men-08",
        "transtorno-do-panico",
        "mental-health",
        "Transtorno do pânico",
        "pânico",
        "crises",
        "ansiedade",
    ),
    entry(
        "men-09",
        "tdah",
        "mental-health",
        "Transtorno do déficit de atenção com hiperatividade",
        "tdah",
        "atenção",
        "neurodesenvolvimento",
    ),
    entry(
        "men-10",
        "transtorno-bipolar",
        "mental-health",
        "Transtorno bipolar",
        "transtorno bipolar",
        "humor",
        "psiquiatria",
    ),
    entry(
        "men-11",
        "transtorno-obsessivo-compulsivo",
        "mental-health",
        "Transtorno obsessivo-compulsivo",
        "toc",
        "obsessões",
        "ansiedade",
    ),
    entry(
        "men-12",
        "transtorno-de-estresse-pos-traumatico",
        "mental-health",
        "Transtorno de estresse pós-traumático",
        "trauma",
        "tept",
        "ansiedade",
    ),
    entry(
        "men-13",
        "esquizofrenia",
        "mental-health",
        "Esquizofrenia",
        "esquizofrenia",
        "psicose",
        "psiquiatria",
    ),
    entry(
        "men-14",
        "transtorno-do-espectro-autista",
        "mental-health",
        "Transtorno do espectro autista",
        "autismo",
        "neurodesenvolvimento",
        "comunicação",
    ),
    entry("men-15", "alcoolismo", "mental-health", "Alcoolismo", "álcool", "dependência", "vício"),
    entry(
        "men-16",
        "anorexia-nervosa",
        "mental-health",
        "Anorexia nervosa",
        "anorexia",
        "transtornos alimentares",
        "peso corporal",
    ),
    entry(
        "men-17",
        "bulimia-nervosa",
        "mental-health",
        "Bulimia nervosa",
        "bulimia",
        "transtornos alimentares",
        "compulsão",
    ),
    entry(
        "men-18",
        "transtorno-de-ansiedade-social",
        "mental-health",
        "Transtorno de ansiedade social",
        "fobia social",
        "timidez",
        "ansiedade",
    ),
    entry(
        "men-19",
        "psicoterapia",
        "mental-health",
        "Psicoterapia",
        "terapia",
        "psicologia",
        "tratamento",
    ),
    entry(
        "men-20",
        "terapia-cognitivo-comportamental",
        "mental-health",
        "Terapia cognitivo-comportamental",
        "tcc",
        "terapia",
        "pensamentos",
    ),
    # --- Sleep and physical activity ----------------------------------------------------
    entry("act-01", "sono", "sleep-exercise", "Sono", "sono", "descanso", "cérebro"),
    entry(
        "act-02", "insonia", "sleep-exercise", "Insônia", "insônia", "distúrbios do sono", "noite"
    ),
    entry(
        "act-03",
        "apneia-do-sono",
        "sleep-exercise",
        "Apneia do sono",
        "apneia",
        "ronco",
        "respiração",
    ),
    entry(
        "act-04",
        "ritmo-circadiano",
        "sleep-exercise",
        "Ritmo circadiano",
        "ritmo circadiano",
        "relógio biológico",
        "luz",
    ),
    entry("act-05", "jet-lag", "sleep-exercise", "Jet lag", "jet lag", "fusos horários", "viagens"),
    entry(
        "act-06",
        "exercicio-fisico",
        "sleep-exercise",
        "Exercício físico",
        "exercício",
        "atividade física",
        "condicionamento",
    ),
    entry(
        "act-07", "musculacao", "sleep-exercise", "Musculação", "musculação", "força", "hipertrofia"
    ),
    entry("act-08", "corrida", "sleep-exercise", "Corrida", "corrida", "resistência", "esporte"),
    entry(
        "act-09",
        "alongamento",
        "sleep-exercise",
        "Alongamento",
        "alongamento",
        "flexibilidade",
        "músculos",
    ),
    entry(
        "act-10",
        "sedentarismo",
        "sleep-exercise",
        "Sedentarismo",
        "sedentarismo",
        "inatividade física",
        "riscos",
    ),
    entry(
        "act-11",
        "higiene-do-sono",
        "sleep-exercise",
        "Higiene do sono",
        "hábitos",
        "sono",
        "rotina",
    ),
    entry(
        "act-12",
        "privacao-de-sono",
        "sleep-exercise",
        "Privação de sono",
        "falta de sono",
        "cansaço",
        "sono",
    ),
    entry(
        "act-13",
        "narcolepsia",
        "sleep-exercise",
        "Narcolepsia",
        "narcolepsia",
        "sonolência",
        "distúrbios do sono",
    ),
    entry(
        "act-14",
        "sonambulismo",
        "sleep-exercise",
        "Sonambulismo",
        "sonambulismo",
        "parassonias",
        "distúrbios do sono",
    ),
    entry(
        "act-15",
        "sindrome-das-pernas-inquietas",
        "sleep-exercise",
        "Síndrome das pernas inquietas",
        "pernas",
        "distúrbios do sono",
        "noite",
    ),
    entry("act-16", "bruxismo", "sleep-exercise", "Bruxismo", "bruxismo", "dentes", "sono"),
    entry(
        "act-17", "melatonina", "sleep-exercise", "Melatonina", "melatonina", "hormônios", "sono"
    ),
    entry("act-18", "ioga", "sleep-exercise", "Ioga", "ioga", "respiração", "flexibilidade"),
    entry("act-19", "pilates", "sleep-exercise", "Pilates", "pilates", "postura", "força"),
    entry("act-20", "natacao", "sleep-exercise", "Natação", "natação", "esporte", "resistência"),
    # --- Chronic diseases ----------------------------------------------------------------
    entry(
        "chr-01",
        "hipertensao-arterial",
        "chronic-diseases",
        "Hipertensão arterial",
        "hipertensão",
        "pressão arterial",
        "coração",
    ),
    entry(
        "chr-02",
        "diabetes-mellitus",
        "chronic-diseases",
        "Diabetes mellitus",
        "diabetes",
        "glicose",
        "insulina",
    ),
    entry(
        "chr-03",
        "colesterol",
        "chronic-diseases",
        "Colesterol",
        "colesterol",
        "gorduras",
        "artérias",
    ),
    entry(
        "chr-04",
        "acidente-vascular-cerebral",
        "chronic-diseases",
        "Acidente vascular cerebral",
        "avc",
        "cérebro",
        "emergência",
    ),
    entry(
        "chr-05",
        "infarto-agudo-do-miocardio",
        "chronic-diseases",
        "Infarto agudo do miocárdio",
        "infarto",
        "coração",
        "emergência",
    ),
    entry("chr-06", "asma", "chronic-diseases", "Asma", "asma", "pulmões", "respiração"),
    entry(
        "chr-07",
        "dpoc",
        "chronic-diseases",
        "Doença pulmonar obstrutiva crónica",
        "dpoc",
        "pulmões",
        "tabagismo",
    ),
    entry(
        "chr-08", "osteoporose", "chronic-diseases", "Osteoporose", "osteoporose", "ossos", "cálcio"
    ),
    entry(
        "chr-09",
        "cancer-da-mama",
        "chronic-diseases",
        "Cancro da mama",
        "câncer de mama",
        "rastreamento",
        "oncologia",
    ),
    entry(
        "chr-10",
        "doenca-renal-cronica",
        "chronic-diseases",
        "Doença renal crónica",
        "rins",
        "doença renal",
        "diálise",
    ),
    entry(
        "chr-11",
        "artrite-reumatoide",
        "chronic-diseases",
        "Artrite reumatoide",
        "artrite",
        "articulações",
        "autoimune",
    ),
    entry("chr-12", "artrose", "chronic-diseases", "Artrose", "artrose", "articulações", "dor"),
    entry(
        "chr-13",
        "doenca-de-alzheimer",
        "chronic-diseases",
        "Doença de Alzheimer",
        "alzheimer",
        "demência",
        "memória",
    ),
    entry(
        "chr-14",
        "doenca-de-parkinson",
        "chronic-diseases",
        "Doença de Parkinson",
        "parkinson",
        "tremor",
        "neurologia",
    ),
    entry(
        "chr-15", "enxaqueca", "chronic-diseases", "Enxaqueca", "enxaqueca", "dor de cabeça", "dor"
    ),
    entry(
        "chr-16",
        "hipotireoidismo",
        "chronic-diseases",
        "Hipotireoidismo",
        "tireoide",
        "hormônios",
        "metabolismo",
    ),
    entry(
        "chr-17",
        "insuficiencia-cardiaca",
        "chronic-diseases",
        "Insuficiência cardíaca",
        "coração",
        "falta de ar",
        "cardiologia",
    ),
    entry(
        "chr-18", "gota", "chronic-diseases", "Gota (doença)", "gota", "ácido úrico", "articulações"
    ),
    entry(
        "chr-19",
        "fibromialgia",
        "chronic-diseases",
        "Fibromialgia",
        "fibromialgia",
        "dor crônica",
        "cansaço",
    ),
    entry(
        "chr-20",
        "lupus",
        "chronic-diseases",
        "Lúpus eritematoso sistêmico",
        "lúpus",
        "autoimune",
        "pele",
    ),
    # --- Infectious diseases and prevention --------------------------------------------
    entry("inf-01", "dengue", "infectious-diseases", "Dengue", "dengue", "mosquito", "arboviroses"),
    entry("inf-02", "gripe", "infectious-diseases", "Gripe", "gripe", "influenza", "vírus"),
    entry(
        "inf-03",
        "covid-19",
        "infectious-diseases",
        "COVID-19",
        "covid-19",
        "coronavírus",
        "pandemia",
    ),
    entry(
        "inf-04",
        "sarampo",
        "infectious-diseases",
        "Sarampo",
        "sarampo",
        "vacinação",
        "doenças virais",
    ),
    entry(
        "inf-05",
        "tuberculose",
        "infectious-diseases",
        "Tuberculose",
        "tuberculose",
        "bactérias",
        "pulmões",
    ),
    entry(
        "inf-06", "vacina", "infectious-diseases", "Vacina", "vacinas", "imunização", "prevenção"
    ),
    entry(
        "inf-07",
        "antibiotico",
        "infectious-diseases",
        "Antibiótico",
        "antibióticos",
        "bactérias",
        "medicamentos",
    ),
    entry(
        "inf-08",
        "resistencia-antimicrobiana",
        "infectious-diseases",
        "Resistência antimicrobiana",
        "resistência",
        "antibióticos",
        "superbactérias",
    ),
    entry(
        "inf-09",
        "febre-amarela",
        "infectious-diseases",
        "Febre amarela",
        "febre amarela",
        "mosquito",
        "vacinação",
    ),
    entry(
        "inf-10",
        "lavagem-das-maos",
        "infectious-diseases",
        "Lavagem das mãos",
        "higiene",
        "mãos",
        "prevenção",
    ),
    entry(
        "inf-11",
        "aids",
        "infectious-diseases",
        "Síndrome da imunodeficiência adquirida",
        "hiv",
        "aids",
        "infecções sexualmente transmissíveis",
    ),
    entry(
        "inf-12", "hepatite-b", "infectious-diseases", "Hepatite B", "hepatite", "fígado", "vírus"
    ),
    entry(
        "inf-13", "malaria", "infectious-diseases", "Malária", "malária", "mosquito", "parasitas"
    ),
    entry(
        "inf-14", "febre-zika", "infectious-diseases", "Febre zika", "zika", "mosquito", "gestação"
    ),
    entry(
        "inf-15",
        "chikungunya",
        "infectious-diseases",
        "Febre chikungunya",
        "chikungunya",
        "mosquito",
        "arboviroses",
    ),
    entry(
        "inf-16",
        "meningite",
        "infectious-diseases",
        "Meningite",
        "meningite",
        "cérebro",
        "vacinação",
    ),
    entry(
        "inf-17",
        "pneumonia",
        "infectious-diseases",
        "Pneumonia",
        "pneumonia",
        "pulmões",
        "infecção",
    ),
    entry(
        "inf-18",
        "infeccao-urinaria",
        "infectious-diseases",
        "Infecção urinária",
        "infecção urinária",
        "bexiga",
        "bactérias",
    ),
    entry(
        "inf-19",
        "herpes-zoster",
        "infectious-diseases",
        "Herpes-zóster",
        "herpes-zóster",
        "pele",
        "vírus",
    ),
    entry("inf-20", "varicela", "infectious-diseases", "Varicela", "catapora", "vírus", "pele"),
]


def http_get(url: str, attempts: int = 6) -> bytes:
    """Download a URL politely: identified client, pauses and back-off on throttling.

    Wikimedia answers 429 (Too Many Requests) when a client calls too fast; the
    request is retried after the delay the server asks for (`Retry-After`), or with
    an exponential back-off when it does not say.

    Args:
        url: Address to fetch.
        attempts: Maximum number of tries.

    Returns:
        The response body.

    Raises:
        urllib.error.HTTPError: If the server keeps refusing or answers another error.
    """
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body: bytes = response.read()
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 503) or attempt == attempts:
                raise
            retry_after = exc.headers.get("Retry-After")
            delay = float(retry_after) if retry_after and retry_after.isdigit() else 2.0**attempt
            print(f"     throttled ({exc.code}); waiting {delay:.0f}s")
            time.sleep(delay)
            continue
        time.sleep(PAUSE_SECONDS)
        return body
    raise AssertionError("unreachable")


# Editorial markers of the Wikipedia ("[carece de fontes]", "[1]"...) are not content.
EDITORIAL_MARKERS = re.compile(
    r"\[(?:carece de fontes|citação necessária|nota \d+|\d+)\]\??", re.IGNORECASE
)
# A heading glued to the end of a line ("...texto.==Referências==") by the extractor.
INLINE_HEADING = re.compile(r"\s*={2,6}[^=\n]+={2,6}\s*$")


def clean_section(text: str) -> str:
    """Clean the plain text of a section and separate its paragraphs.

    The API returns one paragraph per line; Markdown (and the chunker) separate
    paragraphs with a blank line, so lines are joined with blank lines.

    Args:
        text: Raw section text.

    Returns:
        The cleaned text, one paragraph per block.
    """
    paragraphs = []
    for line in text.splitlines():
        line = INLINE_HEADING.sub("", EDITORIAL_MARKERS.sub("", line))
        line = re.sub(r"[ \t]{2,}", " ", line)
        line = re.sub(r"\s+([,.;:!?)])", r"\1", line).strip()
        if line:
            paragraphs.append(line)
    return "\n\n".join(paragraphs)


def fetch_article(title: str) -> tuple[str, list[tuple[str, str]], str, int]:
    """Fetch a Wikipedia article as plain text split into sections.

    Args:
        title: Article title (redirects are followed).

    Returns:
        The canonical title, `(heading, text)` sections (the lead has an empty
        heading), the article URL and the revision id.

    Raises:
        LookupError: If the article does not exist.
    """
    params = {
        "action": "query",
        "format": "json",
        "formatversion": "2",
        "redirects": "1",
        "prop": "extracts|info|revisions",
        "explaintext": "1",
        "exsectionformat": "wiki",
        "inprop": "url",
        "rvprop": "ids",
        "titles": title,
    }
    payload = json.loads(http_get(f"{WIKIPEDIA_API}?{urllib.parse.urlencode(params)}"))
    page = payload["query"]["pages"][0]
    if page.get("missing") or not page.get("extract"):
        raise LookupError(f"Wikipedia article not found: {title}")

    sections: list[tuple[str, str]] = []
    heading = ""
    lines: list[str] = []
    skipping = False
    for line in page["extract"].splitlines():
        match = re.match(r"^(={2,6})\s*(.*?)\s*\1$", line.strip())
        if not match:
            lines.append(line)
            continue
        if not skipping:
            sections.append((heading, clean_section("\n".join(lines))))
        level = len(match.group(1))
        name = match.group(2)
        # A skipped top-level section also skips its sub-sections.
        if level == 2:
            skipping = name.lower() in SKIPPED_SECTIONS
        heading = f"{'#' * level} {name}"
        lines = []
    if not skipping:
        sections.append((heading, clean_section("\n".join(lines))))

    return page["title"], sections, page["fullurl"], int(page["revisions"][0]["revid"])


def build_body(sections: list[tuple[str, str]]) -> tuple[str, bool]:
    """Join sections into a Markdown body, cutting at a section boundary.

    Sections that only have a heading (their text lives in sub-sections) are kept
    with the sub-sections that follow.

    Args:
        sections: `(heading, text)` pairs; the first one is the lead.

    Returns:
        The body and whether sections were cut to respect MAX_WORDS.
    """
    parts: list[str] = []
    words = 0
    pending_heading = ""
    for heading, text in sections:
        if not text.strip():
            pending_heading = (
                f"{pending_heading}\n\n{heading}".strip() if heading else pending_heading
            )
            continue
        block = "\n\n".join(part for part in (pending_heading, heading, text.strip()) if part)
        pending_heading = ""
        size = len(block.split())
        if parts and words + size > MAX_WORDS:
            return "\n\n".join(parts), True
        parts.append(block)
        words += size
    return "\n\n".join(parts), False


def write_document(item: Entry, retrieved_at: str) -> int:
    """Download one catalog entry and write its Markdown file.

    Args:
        item: Catalog entry.
        retrieved_at: Retrieval date (ISO).

    Returns:
        Number of words in the body.
    """
    title, sections, url, revision = fetch_article(item.title)
    body, truncated = build_body(sections)
    front_matter = {
        "id": item.id,
        "title": title,
        "category": item.category,
        "tags": list(item.tags),
        "author": AUTHOR,
        "source_url": url,
        "source_revision": revision,
        "license": LICENSE,
        "license_url": LICENSE_URL,
        "retrieved_at": retrieved_at,
        "adapted": "Plain-text extraction; reference sections removed"
        + ("; cut at a section boundary" if truncated else ""),
    }
    header = yaml.safe_dump(front_matter, allow_unicode=True, sort_keys=False, width=1000)
    path = DOCUMENTS_DIR / f"{item.id}-{item.slug}.md"
    path.write_text(f"---\n{header}---\n{body}\n", encoding="utf-8")
    return len(body.split())


CATEGORY_NAMES = {
    "nutrition": "Nutrição",
    "mental-health": "Saúde mental",
    "sleep-exercise": "Sono e atividade física",
    "chronic-diseases": "Doenças crônicas",
    "infectious-diseases": "Doenças infecciosas e prevenção",
}


def write_attribution() -> None:
    """Write `data/README.md`: sources, license and the list of documents.

    CC BY-SA asks for the title, the author, the source, the license and an
    indication of changes; this file gathers them for the whole dataset. It is built
    from the files on disk, so it always matches what is committed.
    """
    rows = []
    for path in sorted(DOCUMENTS_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        meta = yaml.safe_load(text.split("---", 2)[1])
        words = len(text.split("---", 2)[2].split())
        rows.append(
            f"| `{meta['id']}` | {CATEGORY_NAMES[meta['category']]} | "
            f"[{meta['title']}]({meta['source_url']}) | {meta['source_revision']} | "
            f"{meta['retrieved_at']} | {words} |"
        )
    counts = {name: sum(f"| {name} |" in row for row in rows) for name in CATEGORY_NAMES.values()}
    readme = (
        f"""# Dataset

{len(rows)} real health articles from the **Portuguese Wikipedia**
([pt.wikipedia.org](https://pt.wikipedia.org)), written in Portuguese, used as the
document collection of the semantic search demo.

## License and attribution

- **Authors:** Colaboradores da Wikipédia (the full history of each article is linked
  from its page).
- **License:** [{LICENSE}]({LICENSE_URL}). The texts in `documents/` are distributed
  under the same license.
- **Changes:** the plain text of each article was extracted through the MediaWiki API;
  reference-only sections (references, external links, "see also"...) and editorial
  markers such as `[carece de fontes]` were removed; articles longer than
  {MAX_WORDS} words were cut at a section boundary. The `adapted` field of each file
  says which changes apply to it.
- **Disclaimer:** encyclopedic content, used only to demonstrate information retrieval.
  It is not medical advice.

The source URL, the revision id and the retrieval date of every article are stored in
its front matter, so the exact original text can be checked.

## Reproducing

```bash
uv run python scripts/fetch_dataset.py          # download every article again
uv run python scripts/fetch_dataset.py chr-02   # only some ids
```

The articles keep changing on Wikipedia; a new download may produce slightly different
texts (and a different dataset hash, which makes the ingestion rebuild the index).

## Categories

| Category | Documents |
|---|---|
"""
        + "\n".join(f"| {name} | {count} |" for name, count in counts.items())
        + """

## Documents

| ID | Category | Article | Revision | Retrieved | Words |
|---|---|---|---|---|---|
"""
        + "\n".join(rows)
        + "\n"
    )
    (DOCUMENTS_DIR.parent / "README.md").write_text(readme, encoding="utf-8")
    print(f"Attribution written to {DOCUMENTS_DIR.parent / 'README.md'}")


def main() -> int:
    """Download every document of the catalog (or only the given ids).

    Returns:
        Process exit code (1 when a document failed or is too short).
    """
    parser = argparse.ArgumentParser(description="Download the health articles of the dataset.")
    parser.add_argument("ids", nargs="*", help="Only fetch these document ids")
    parser.add_argument(
        "--readme-only", action="store_true", help="Only rebuild data/README.md from the files"
    )
    args = parser.parse_args()

    if args.readme_only:
        write_attribution()
        return 0

    DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)
    retrieved_at = datetime.now(UTC).date().isoformat()
    selected = [item for item in CATALOG if not args.ids or item.id in args.ids]
    failures = 0
    for item in selected:
        try:
            words = write_document(item, retrieved_at)
        except (LookupError, OSError, KeyError) as exc:
            print(f"FAIL {item.id}: {exc}")
            failures += 1
            continue
        short = words < MIN_WORDS
        failures += short
        print(f"{'SHORT' if short else 'ok   '} {item.id:7} {words:5} words  {item.title}")
    print(f"{len(selected) - failures}/{len(selected)} documents written to {DOCUMENTS_DIR}")
    write_attribution()
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
