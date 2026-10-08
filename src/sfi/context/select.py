"""Choose the article passages sent with a figure: those that mention it.

Passages from the back matter (references, declarations) are ignored. Long
passages are cut to a window of sentences around the mentions. When the
passages do not fit in the character budget, Methods passages are dropped
first, then the latest ones; what was left out is reported, never hidden.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sfi.analysis.schema import ContextPassage
from sfi.domain.models import Figure, Passage

CONTEXT_VERSION = "context/0.1"
METHODS = re.compile(r"method|experimental|materials|statistic|procedure", re.IGNORECASE)
SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\[])")


@dataclass(frozen=True)
class ContextConfig:
    max_chars: int = 6000
    max_passage_chars: int = 1600
    window_sentences: int = 2

    def as_dict(self) -> dict:
        return {
            "version": CONTEXT_VERSION,
            "max_chars": self.max_chars,
            "max_passage_chars": self.max_passage_chars,
            "window_sentences": self.window_sentences,
        }


@dataclass
class FigureContext:
    passages: list[ContextPassage]
    note: str | None  # why there is no or partial context


def _window(passage: Passage, starts: list[int], config: ContextConfig) -> tuple[int, int]:
    """Character range covering the sentences around the mentions."""
    text = passage.text
    if len(text) <= config.max_passage_chars:
        return 0, len(text)
    bounds = [0] + [m.end() for m in SENTENCE_END.finditer(text)] + [len(text)]
    sentences = list(zip(bounds[:-1], bounds[1:], strict=True))
    hits = [i for i, (a, b) in enumerate(sentences) if any(a <= s < b for s in starts)]
    first = max(0, min(hits) - config.window_sentences)
    last = min(len(sentences) - 1, max(hits) + config.window_sentences)
    start, end = sentences[first][0], sentences[last][1]
    if end - start > config.max_passage_chars:
        # Very long sentences: keep a fixed window around the first mention.
        center = starts[0]
        start = max(0, center - config.max_passage_chars // 2)
        end = min(len(text), start + config.max_passage_chars)
    return start, end


DEFAULT_CONFIG = ContextConfig()


def select_context(
    figure: Figure, passages: list[Passage], config: ContextConfig = DEFAULT_CONFIG
) -> FigureContext:
    if not figure.label:
        return FigureContext([], "La figura no tiene etiqueta: no se pueden buscar menciones.")
    candidates = []
    for passage in passages:
        if passage.back_matter:
            continue
        mentions = [m for m in passage.mentions if m.label == figure.label]
        if mentions:
            candidates.append((passage, mentions))
    if not candidates:
        return FigureContext([], f"El texto del artículo no menciona «{figure.label}».")

    windows = []
    for passage, mentions in candidates:
        start, end = _window(passage, [m.start for m in mentions], config)
        windows.append((passage, mentions, start, end))

    # Budget: results/discussion before methods, earlier before later.
    chosen, used = [], 0
    ranked = sorted(windows, key=lambda w: (bool(METHODS.search(w[0].section or "")), w[0].ordinal))
    for window in ranked:
        size = window[3] - window[2]
        if used + size <= config.max_chars or not chosen:
            chosen.append(window)
            used += size
    chosen.sort(key=lambda w: w[0].ordinal)

    context = [
        ContextPassage(
            ref=f"p{passage.ordinal}",
            passage_id=passage.id,
            page=passage.page_at(start) + 1,
            section=passage.section,
            text=passage.text[start:end],
            offset=start,
            mentions=[m.text for m in mentions if start <= m.start < end],
            truncated=(start, end) != (0, len(passage.text)),
            segments=[(s.page_index + 1, s.char_start) for s in passage.segments],
        )
        for passage, mentions, start, end in chosen
    ]
    left_out = len(windows) - len(chosen)
    note = (
        f"{left_out} de {len(windows)} pasajes que mencionan la figura no caben en el contexto."
        if left_out
        else None
    )
    return FigureContext(context, note)
