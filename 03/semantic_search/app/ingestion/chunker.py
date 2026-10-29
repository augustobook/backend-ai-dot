"""Split posts into chunks that fit the embedding model and keep their context.

Why chunk at all:
- The model only reads a fixed number of tokens; text beyond that window would be
  truncated silently and could never be found.
- One vector per whole post averages many topics together. Smaller chunks give
  sharper vectors, so a query matches the passage that actually answers it, and the
  result can show that passage.

Strategy:
1. Split the body into sections (`##` to `######` headings), then into paragraphs.
   Each section is labeled with its heading path ("Causas > Virologia"), glued to its
   first paragraph. A heading with no text below it (a parent whose text lives in its
   sub-sections) never becomes a chunk of its own: it only survives in the path of its
   sub-headings. Fenced code blocks are kept whole.
2. Sections smaller than `min_tokens` are joined to the next section (or the previous
   one, for the last section) when both fit the budget: a 20-token chunk makes a weak
   vector. Each joined section keeps its own label.
3. Pack consecutive paragraphs of the same section into chunks up to the token
   budget. Apart from the joins above, chunks never cross a section boundary, so each
   one stays on one subtopic.
4. When a section needs more than one chunk, the next chunk starts with the last
   sentences of the previous one (overlap), so an idea split between two chunks is
   still complete in at least one of them.
5. The post title is prepended to every chunk: a chunk from the middle of a post
   would otherwise lose the context of what the post is about.
"""

import functools
import hashlib
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from app.ingestion.loader import Document
from app.llm.metadata import ChunkEnrichment

logger = logging.getLogger(__name__)

TokenCounter = Callable[[str], int]
"""Counts the tokens of a text with the embedding model's tokenizer."""

HEADING_PATTERN = re.compile(r"^(#{2,6})\s+(.*)$")
HEADING_PATH_SEPARATOR = " > "

# Bump when the chunking logic changes: the manifest records it, so the next ingestion
# rebuilds the index even though the documents did not change.
# v2: heading paths, no heading-only chunks, small sections joined to a neighbor.
CHUNKER_VERSION = "2"
FENCE_PATTERN = re.compile(r"^\s*(```|~~~)")
SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?…:;])\s+")
PARAGRAPH_SEPARATOR = "\n\n"


class Chunk(BaseModel):
    """A piece of a post that is embedded and indexed on its own.

    Attributes:
        chunk_id: Stable 63-bit integer id (used as the FAISS id).
        document_id: Id of the post the chunk belongs to.
        position: 0-based order of the chunk inside the post.
        text: Title + passage, as shown to the user.
        enrichment: What the LLM wrote about the chunk at ingestion, if anything.
        enrichment_text: The enrichment rendered within its token budget; appended to
            `text` to form `search_text`.
    """

    model_config = ConfigDict(frozen=True)

    chunk_id: int
    document_id: str
    position: int
    text: str
    enrichment: ChunkEnrichment | None = None
    enrichment_text: str = ""

    @property
    def search_text(self) -> str:
        """Return the text that is embedded, indexed by BM25 and read by the re-ranker.

        Returns:
            `text`, followed by the enrichment when there is one.
        """
        if not self.enrichment_text:
            return self.text
        return f"{self.text}{PARAGRAPH_SEPARATOR}{self.enrichment_text}"

    def question_ids(self) -> list[tuple[int, str]]:
        """Return the id and text of every question of the enrichment.

        Each question is a vector of its own in the question index; its id derives
        from the chunk id and the question position, so it is stable and never needs
        to be stored.

        Returns:
            `(question id, question)` pairs, empty without enrichment.
        """
        if self.enrichment is None:
            return []
        return [
            (make_chunk_id(f"{self.chunk_id}:q", index), question)
            for index, question in enumerate(self.enrichment.questions)
        ]


@dataclass(frozen=True)
class _Block:
    """A paragraph-level unit of a section.

    Attributes:
        text: Text of the block.
        is_code: Whether the block is a fenced code block (never split).
    """

    text: str
    is_code: bool = False


def make_chunk_id(document_id: str, position: int) -> int:
    """Derive a stable id from the document id and the chunk position.

    The same chunk always gets the same id across ingestions, which keeps ids
    meaningful in logs and makes incremental updates possible. FAISS ids are signed
    64-bit integers, so the value is masked to 63 bits to stay positive.

    Args:
        document_id: Id of the post.
        position: 0-based position of the chunk in the post.

    Returns:
        A positive integer below 2**63.
    """
    digest = hashlib.sha256(f"{document_id}:{position}".encode()).digest()
    return int.from_bytes(digest[:8], "big") & ((1 << 63) - 1)


def split_sections(body: str) -> list[list[_Block]]:
    """Split a Markdown body into sections made of paragraph blocks.

    Each section is labeled with the path of the headings above it, e.g.
    "Causas > Virologia" for a `### Virologia` under `## Causas`: the sub-section
    alone would not say what it is about. A heading with no text below it is not a
    section: articles often open a section (`## Causas`) directly with a sub-heading,
    and emitting that heading alone would create a chunk with a single word. It only
    lives on in the path of its sub-headings; with no sub-heading, it is dropped.

    Args:
        body: Markdown body of a post.

    Returns:
        One list of blocks per section, in order. The heading path is merged into the
        first paragraph of its section.
    """
    sections: list[list[_Block]] = [[]]
    path: list[tuple[int, str]] = []
    pending_label: str | None = None
    paragraph: list[str] = []
    code: list[str] | None = None

    def flush_paragraph() -> None:
        nonlocal pending_label
        text = "\n".join(paragraph).strip()
        paragraph.clear()
        if not text:
            return
        if pending_label is not None:
            text = f"{pending_label}\n{text}"
            pending_label = None
        sections[-1].append(_Block(text))

    def add_code(text: str) -> None:
        nonlocal pending_label
        if pending_label is not None:
            sections[-1].append(_Block(pending_label))
            pending_label = None
        sections[-1].append(_Block(text, is_code=True))

    for line in body.splitlines():
        # Inside a fenced code block every line belongs to the block, blank lines too.
        if code is not None:
            code.append(line)
            if FENCE_PATTERN.match(line):
                add_code("\n".join(code))
                code = None
            continue
        if FENCE_PATTERN.match(line):
            flush_paragraph()
            code = [line]
            continue

        heading = HEADING_PATTERN.match(line)
        if heading:
            flush_paragraph()
            level = len(heading.group(1))
            # Leaving a section closes its sub-sections too.
            while path and path[-1][0] >= level:
                path.pop()
            path.append((level, heading.group(2).strip()))
            sections.append([])
            # The label of a heading that had no text is simply replaced here.
            pending_label = HEADING_PATH_SEPARATOR.join(text for _, text in path)
            continue

        if line.strip():
            paragraph.append(line)
        else:
            flush_paragraph()

    flush_paragraph()
    # An unterminated fence is kept as code rather than being lost.
    if code is not None:
        add_code("\n".join(code))
    return [section for section in sections if section]


class MarkdownChunker:
    """Section-aware chunker with a token budget and sentence-level overlap.

    Args:
        count_tokens: Tokenizer-based token counter.
        max_tokens: Maximum tokens per chunk, title included.
        overlap_tokens: Maximum tokens carried over from the previous chunk.
        min_tokens: Sections smaller than this are joined to a neighbor section when
            both fit the budget; 0 never joins sections.

    Raises:
        ValueError: If the budget, the overlap or the minimum are invalid.
    """

    def __init__(
        self,
        count_tokens: TokenCounter,
        max_tokens: int,
        overlap_tokens: int,
        min_tokens: int = 0,
    ) -> None:
        if max_tokens <= 0:
            raise ValueError("max_tokens must be positive")
        if not 0 <= overlap_tokens < max_tokens:
            raise ValueError("overlap_tokens must be >= 0 and smaller than max_tokens")
        if not 0 <= min_tokens < max_tokens:
            raise ValueError("min_tokens must be >= 0 and smaller than max_tokens")
        self._min_tokens = min_tokens
        # Tokenizing is the expensive part of chunking, and the packing loop asks for
        # the size of the same blocks again and again: cache the counts per text.
        self._count = functools.lru_cache(maxsize=8192)(count_tokens)
        self._separator_tokens = count_tokens(PARAGRAPH_SEPARATOR)
        self._max_tokens = max_tokens
        self._overlap_tokens = overlap_tokens

    def chunk(self, document: Document) -> list[Chunk]:
        """Split a post into indexed chunks.

        Args:
            document: The post to split.

        Returns:
            The chunks in reading order, each one starting with the post title.
        """
        texts = self.split(document.title, document.body)
        return [
            Chunk(
                chunk_id=make_chunk_id(document.id, position),
                document_id=document.id,
                position=position,
                text=text,
            )
            for position, text in enumerate(texts)
        ]

    def split(self, title: str, body: str) -> list[str]:
        """Split a body into chunk texts, each prefixed with the title.

        Args:
            title: Post title, repeated at the top of every chunk.
            body: Markdown body.

        Returns:
            Chunk texts; an empty list when the body has no text.

        Raises:
            ValueError: If the title alone does not fit the token budget.
        """
        header = f"{title.strip()}{PARAGRAPH_SEPARATOR}"
        budget = self._max_tokens - self._count(header)
        if budget <= 0:
            raise ValueError(f"The title alone exceeds the chunk budget: {title!r}")

        chunks: list[str] = []
        for section in self._merge_small_sections(split_sections(body), budget):
            for passage in self._pack_section(section, budget):
                chunks.append(f"{header}{passage}")
        return chunks

    def _merge_small_sections(
        self, sections: list[list[_Block]], budget: int
    ) -> list[list[_Block]]:
        """Join each section smaller than `min_tokens` to a neighbor section.

        The next section is tried first, then the previous one; a join only happens
        when both sections fit the budget together, so a join never splits any text.
        A joined section is checked again, since it may still be small.

        Args:
            sections: Sections in reading order.
            budget: Tokens available for a passage (title excluded).

        Returns:
            The sections after the joins.
        """
        if self._min_tokens == 0:
            return sections
        merged = [list(section) for section in sections]
        index = 0
        while index < len(merged):
            if len(merged) == 1 or self._tokens(merged[index]) >= self._min_tokens:
                index += 1
                continue
            for neighbor in (index + 1, index - 1):
                if not 0 <= neighbor < len(merged):
                    continue
                first, second = sorted((index, neighbor))
                joined = [*merged[first], *merged[second]]
                if self._tokens(joined) <= budget:
                    merged[first : second + 1] = [joined]
                    index = first
                    break
            else:
                index += 1
        return merged

    def _pack_section(self, blocks: list[_Block], budget: int) -> list[str]:
        """Greedily pack the blocks of one section into passages.

        Args:
            blocks: Paragraph blocks of the section.
            budget: Tokens available for the passage (title excluded).

        Returns:
            Passage texts for this section.
        """
        units = [unit for block in blocks for unit in self._fit_block(block, budget)]
        passages: list[str] = []
        current: list[_Block] = []

        for unit in units:
            candidate = [*current, unit]
            if current and self._tokens(candidate) > budget:
                passages.append(self._join(current))
                # Start the next passage with the tail of the previous one, but only
                # if the overlap still leaves room for the new block.
                overlap = self._overlap_from(current)
                current = (
                    [overlap, unit]
                    if overlap and self._tokens([overlap, unit]) <= budget
                    else [unit]
                )
            else:
                current = candidate

        if current:
            passages.append(self._join(current))
        return passages

    def _fit_block(self, block: _Block, budget: int) -> list[_Block]:
        """Break a block that is larger than the budget into smaller blocks.

        Paragraphs are split by sentences and, as a last resort, by words. A code
        block is only split (by lines) when it alone exceeds the budget, because
        otherwise it could never be embedded in full.

        Args:
            block: The block to fit.
            budget: Tokens available for the passage.

        Returns:
            One or more blocks, each within the budget.
        """
        if self._count(block.text) <= budget:
            return [block]
        if block.is_code:
            logger.warning("Code block larger than the chunk budget; splitting it by lines")
            splitters: list[tuple[Callable[[str], list[str]], str]] = [(str.splitlines, "\n")]
        else:
            splitters = [(SENTENCE_BOUNDARY.split, " "), (str.split, " ")]
        return self._fit_text(block.text, block.is_code, budget, splitters)

    def _fit_text(
        self,
        text: str,
        is_code: bool,
        budget: int,
        splitters: list[tuple[Callable[[str], list[str]], str]],
    ) -> list[_Block]:
        """Split a text with the first splitter, recursing on pieces that are still too big.

        Args:
            text: Text to fit.
            is_code: Whether the text comes from a code block.
            budget: Tokens available for the passage.
            splitters: Remaining (split function, join separator) pairs, coarsest first.

        Returns:
            Blocks within the budget.
        """
        if self._count(text) <= budget:
            return [_Block(text, is_code)]
        if not splitters:
            return self._split_by_characters(text, is_code, budget)

        split, separator = splitters[0]
        pieces = [piece for piece in split(text) if piece.strip()]
        if len(pieces) <= 1:
            return self._fit_text(text, is_code, budget, splitters[1:])

        # Pack consecutive pieces back together while they fit, so the result does
        # not degrade into one block per sentence.
        packed: list[str] = []
        current: list[str] = []
        for piece in pieces:
            if current and self._count(separator.join([*current, piece])) > budget:
                packed.append(separator.join(current))
                current = []
            current.append(piece)
        packed.append(separator.join(current))

        return [
            fitted
            for piece in packed
            for fitted in self._fit_text(piece, is_code, budget, splitters[1:])
        ]

    def _split_by_characters(self, text: str, is_code: bool, budget: int) -> list[_Block]:
        """Hard-split a text with no usable boundaries (e.g. a gigantic word).

        Args:
            text: Text that cannot be split by lines, sentences or words.
            is_code: Whether the text comes from a code block.
            budget: Tokens available for the passage.

        Returns:
            Pieces within the budget, shrinking each one until it fits.
        """
        pieces: list[_Block] = []
        while text:
            size = len(text)
            while size > 1 and self._count(text[:size]) > budget:
                size = max(1, size * 3 // 4)
            pieces.append(_Block(text[:size], is_code))
            text = text[size:]
        return pieces

    def _overlap_from(self, blocks: list[_Block]) -> _Block | None:
        """Collect the last sentences of a passage, up to the overlap budget.

        Args:
            blocks: Blocks of the passage that was just closed.

        Returns:
            A block with the trailing sentences, or None when there is no overlap
            (overlap disabled, or the passage ends with code).
        """
        if self._overlap_tokens == 0 or blocks[-1].is_code:
            return None
        sentences = SENTENCE_BOUNDARY.split(blocks[-1].text)
        selected: list[str] = []
        for sentence in reversed(sentences):
            candidate = " ".join([sentence, *selected])
            if self._count(candidate) > self._overlap_tokens:
                break
            selected.insert(0, sentence)
        # Repeating the whole block would duplicate it instead of overlapping.
        if not selected or (len(selected) == len(sentences) and len(blocks) == 1):
            return None
        return _Block(" ".join(selected))

    def _tokens(self, blocks: list[_Block]) -> int:
        """Count the tokens of blocks joined as a passage.

        The count is the sum of the (cached) block counts plus the separators, instead
        of re-tokenizing the whole passage for every candidate block. Subword
        tokenizers split on whitespace before tokenizing, so blocks joined by blank
        lines tokenize independently and the sum matches the joined text.

        Args:
            blocks: Blocks to join.

        Returns:
            Token count of the joined text.
        """
        separators = self._separator_tokens * (len(blocks) - 1)
        return sum(self._count(block.text) for block in blocks) + separators

    @staticmethod
    def _join(blocks: list[_Block]) -> str:
        """Join blocks with blank lines, as in the original Markdown.

        Args:
            blocks: Blocks to join.

        Returns:
            The passage text.
        """
        return PARAGRAPH_SEPARATOR.join(block.text for block in blocks)
