"""Validation rules for explanations (docs/EXPLANATION_SCHEMA.md).

Errors make the analysis ``invalid`` (or ``incomplete`` when required content
is missing) so it is never shown as reliable; warnings are displayed but do not
change the status. What cannot be checked automatically is left to evaluation:
numbers in ``observed`` claims are read from the image and only the model saw it.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence

from sfi.analysis.schema import (
    AnalysisStatus,
    ContextPassage,
    Explanation,
    TokenRef,
    ValidationIssue,
)

# Part of every stored analysis: when the rules change, stored outputs are revalidated
# locally (no new model call) instead of being trusted under the old rules.
# 0.5: numbers read in the figure. 0.6: no rule change; forces stored analyses reused
# under another run to be revalidated so their passages are re-linked (remap_context).
VALIDATOR_VERSION = "validate/0.6"

# Missing required content: the response is incomplete rather than wrong.
INCOMPLETE_CODES = {"missing_summary", "missing_layout", "no_claims"}

_CHAR_MAP = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "“": '"',
        "”": '"',
        "‐": "-",
        "‑": "-",
        "‒": "-",
        "–": "-",
        "—": "-",
        "−": "-",
        "­": "",
    }
)
_NUMBER = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)?")
_UNITS = {
    word: value
    for value, word in enumerate(
        [
            "zero",
            "one",
            "two",
            "three",
            "four",
            "five",
            "six",
            "seven",
            "eight",
            "nine",
            "ten",
            "eleven",
            "twelve",
            "thirteen",
            "fourteen",
            "fifteen",
            "sixteen",
            "seventeen",
            "eighteen",
            "nineteen",
        ]
    )
}
_TENS = {
    word: 10 * value
    for value, word in enumerate(
        ["_", "_", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
    )
    if word != "_"
}
_SYNONYMS = {"single": 1, "both": 2, "pair": 2, "twice": 2, "double": 2, "triplicate": 3}


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).translate(_CHAR_MAP)
    return re.sub(r"\s+", " ", text).strip().casefold()


def _normalized_with_map(text: str, alnum: bool) -> tuple[str, list[int]]:
    """Normalized text plus, for each of its characters, the index in the original."""
    out: list[str] = []
    index: list[int] = []
    previous_space = True
    for i, raw in enumerate(text):
        for char in unicodedata.normalize("NFKC", raw).translate(_CHAR_MAP).casefold():
            if alnum:
                if not char.isalnum():
                    continue
            elif char.isspace():
                if previous_space:
                    continue
                char = " "
            out.append(char)
            index.append(i)
            previous_space = char == " "
    return "".join(out), index


def locate_quote(quote: str, text: str, allow_gaps: bool = False) -> tuple[int, int] | None:
    """(start, end) of a literal quote in the text, or None.

    Tolerates whitespace, typographic quotes, dashes, ligatures, case and line-break
    hyphenation, and an ellipsis between fragments that appear in order. With
    ``allow_gaps``, each sentence of the quote must appear literally and in order,
    but text between sentences may have been left out.
    """
    pieces = [p for p in re.split(r"\.\.\.|…|\[\.\.\.\]", quote) if p.strip()]
    if allow_gaps:
        pieces = [s for piece in pieces for s in re.split(r"(?<=[.!?;:])\s+", piece) if s.strip()]
    if not pieces:
        return None
    for alnum in (False, True):
        haystack, index = _normalized_with_map(text, alnum)
        position, start = 0, None
        for piece in pieces:
            needle = _normalized_with_map(piece, alnum)[0].strip()
            found = haystack.find(needle, position) if needle else -1
            if found < 0:
                break
            start = found if start is None else start
            position = found + len(needle)
        else:
            return index[start], index[position - 1] + 1
    return None


def quote_in_text(quote: str, text: str) -> bool:
    return locate_quote(quote, text) is not None


def quote_match(quote: str, text: str) -> str | None:
    """'exact', 'gaps' (literal sentences in order, text between them left out) or None."""
    if locate_quote(quote, text) is not None:
        return "exact"
    if locate_quote(quote, text, allow_gaps=True) is not None:
        return "gaps"
    return None


def _numbers(text: str) -> set[str]:
    return {n.replace(",", ".") for n in _NUMBER.findall(unicodedata.normalize("NFKC", text))}


def _spelled_numbers(text: str) -> set[str]:
    """English numbers written in words: 'two', 'fifty-six', 'one hundred and five'."""
    found: set[int] = set()
    current: int | None = None
    for word in [*re.findall(r"[a-z]+", normalize_text(text)), ""]:
        value = _UNITS.get(word, _TENS.get(word))
        if value is not None:
            if current is None:
                current = value
            elif current >= 100 and current % 100 == 0:
                current += value  # one hundred five
            elif current % 100 >= 20 and current % 10 == 0 and value < 10:
                current += value  # fifty six
            else:
                found.add(current)
                current = value
        elif word == "hundred" and current is not None and current < 10:
            current *= 100
        elif word == "and" and current is not None and current >= 100 and current % 100 == 0:
            continue
        else:
            if current is not None:
                found.add(current)
                current = None
            if word in _SYNONYMS:
                found.add(_SYNONYMS[word])
    return {str(n) for n in found}


def _number_supported(number: str, evidence: str) -> bool:
    return number in _numbers(evidence) or number in _spelled_numbers(evidence)


def _panel_key(label: str) -> str:
    key = normalize_text(label)
    key = re.sub(r"^(panel|panels|fig(ure)?\.?)\s*", "", key)
    return key.strip("() .,:")


def validate_explanation(
    explanation: Explanation,
    caption: str | None,
    context: Sequence[ContextPassage] = (),
    figure_text: str | None = None,
) -> list[ValidationIssue]:
    """Check an explanation against its sources.

    ``figure_text`` is the text printed inside the figure (PDF text layer and OCR, see
    sfi.extract.evidence); when given, exact numbers that "observed" claims read in the
    image must appear in it or in the caption. That check is a warning until the OCR is
    measured (E03): OCR can miss a value that is there.
    """
    issues: list[ValidationIssue] = []

    def add(code: str, message: str, severity: str = "error", claim_id: str | None = None):
        issues.append(
            ValidationIssue(code=code, severity=severity, message=message, claim_id=claim_id)
        )

    if not explanation.summary.strip():
        add("missing_summary", "The explanation has no summary.")
    if not explanation.layout.description.strip():
        add("missing_layout", "The explanation does not say how to read the figure.")
    if not explanation.claims:
        add("no_claims", "The explanation has no claims.")
    if not explanation.role_in_article.text.strip():
        add(
            "missing_role_in_article",
            "The explanation does not say what the figure contributes to the article.",
            severity="warning",
        )

    claims = {}
    for claim in explanation.claims:
        if claim.id in claims:
            add("duplicate_claim_id", f"Claim id {claim.id!r} is repeated.", claim_id=claim.id)
        claims[claim.id] = claim

    for field, ids in (
        ("main_findings", explanation.main_findings),
        ("interpretation", explanation.interpretation.claim_ids),
        ("role_in_article", explanation.role_in_article.claim_ids),
        ("limitations", explanation.limitations),
    ):
        for claim_id in ids:
            if claim_id not in claims:
                add("unknown_claim_ref", f"{field} refers to unknown claim {claim_id!r}.")
    for claim_id in explanation.limitations:
        if claim_id in claims and claims[claim_id].type != "uncertain":
            add(
                "limitation_not_uncertain",
                f"Limitation {claim_id!r} is not an 'uncertain' claim.",
                severity="warning",
                claim_id=claim_id,
            )
    if not explanation.limitations and not (explanation.limitations_justification or "").strip():
        add(
            "no_limitations",
            "No limitations listed and no justification given.",
            severity="warning",
        )
    # Traceability: every main finding points to the figure, the caption or a passage.
    for claim_id in explanation.main_findings:
        claim = claims.get(claim_id)
        if claim is not None and claim.type != "uncertain" and not claim.evidence:
            add(
                "untraceable_finding",
                f"Main finding {claim_id} cites no evidence.",
                claim_id=claim_id,
            )

    panels = {_panel_key(p.label) for p in explanation.layout.panels}

    def check_panel(label: str | None, where: str, claim_id: str | None, severity: str) -> None:
        if label is None or not label.strip():
            return
        if _panel_key(label) not in panels:
            add(
                "unknown_panel",
                f"{where} cites panel {label!r}, which is not in layout.panels.",
                severity=severity,
                claim_id=claim_id,
            )

    caption_text = caption or ""
    passages = {p.ref: p for p in context}
    all_context = " ".join(p.text for p in context)

    def gaps_warning(claim_id: str, where: str) -> None:
        add(
            "quote_with_gaps",
            f"Claim {claim_id} joins literal sentences of {where} that are not contiguous.",
            severity="warning",
            claim_id=claim_id,
        )

    for claim in explanation.claims:
        for label in claim.panels:
            check_panel(label, f"Claim {claim.id}", claim.id, "error")
        sources: list[str] = []  # text that supports the claim's numbers
        for evidence in claim.evidence:
            quote = (evidence.quote or "").strip()
            if evidence.kind == "figure_region":
                check_panel(evidence.panel, f"Evidence of {claim.id}", claim.id, "error")
            elif evidence.kind == "caption":
                if not caption_text.strip():
                    add(
                        "caption_evidence_without_caption",
                        f"Claim {claim.id} cites the caption, but the figure has none.",
                        claim_id=claim.id,
                    )
                elif not quote:
                    add(
                        "missing_quote",
                        f"Claim {claim.id} cites the caption without a quote.",
                        claim_id=claim.id,
                    )
                elif (match := quote_match(quote, caption_text)) is None:
                    add(
                        "quote_not_in_caption",
                        f"Claim {claim.id} quotes text that is not in the caption: {quote!r}.",
                        claim_id=claim.id,
                    )
                else:
                    if match == "gaps":
                        gaps_warning(claim.id, "the caption")
                    sources.append(caption_text)
            else:  # text_span
                if not context:
                    add(
                        "text_evidence_without_passages",
                        f"Claim {claim.id} cites the article text, but no passage was given.",
                        claim_id=claim.id,
                    )
                    continue
                if not quote:
                    add(
                        "missing_quote",
                        f"Claim {claim.id} cites passage {evidence.passage_id!r} without a quote.",
                        claim_id=claim.id,
                    )
                    continue
                cited = passages.get(evidence.passage_id or "")
                match = quote_match(quote, cited.text) if cited is not None else None
                if match is not None:
                    if match == "gaps":
                        gaps_warning(claim.id, cited.ref)
                    sources.append(cited.text)
                    continue
                elsewhere = next((p for p in context if quote_match(quote, p.text)), None)
                if elsewhere is not None:
                    add(
                        "wrong_passage",
                        f"Claim {claim.id} attributes its quote to {evidence.passage_id!r}; "
                        f"it is in {elsewhere.ref}.",
                        severity="warning",
                        claim_id=claim.id,
                    )
                    sources.append(elsewhere.text)
                elif cited is None:
                    add(
                        "unknown_passage",
                        f"Claim {claim.id} cites passage {evidence.passage_id!r}, which was not "
                        "given, and its quote is not in any passage.",
                        claim_id=claim.id,
                    )
                else:
                    add(
                        "quote_not_in_text",
                        f"Claim {claim.id} quotes text that is not in {cited.ref}: {quote!r}.",
                        claim_id=claim.id,
                    )

        if claim.type == "author_stated" and not any(
            e.kind in {"caption", "text_span"} for e in claim.evidence
        ):
            add(
                "author_stated_without_source",
                f"Claim {claim.id} is author_stated but cites neither the caption nor a passage.",
                claim_id=claim.id,
            )
        # Numbers attributed to the authors must come from the caption or the passages they
        # cite. Numbers the model infers are flagged too; numbers read from the image cannot
        # be checked here.
        if claim.type in {"author_stated", "model_inference"} and not claim.approximate:
            evidence_text = " ".join(sources) + " " + caption_text
            if claim.type == "model_inference":
                evidence_text += " " + all_context
            unsupported = sorted(
                n for n in _numbers(claim.text) if not _number_supported(n, evidence_text)
            )
            if unsupported:
                add(
                    "number_not_in_evidence",
                    f"Claim {claim.id} states {', '.join(unsupported)}, not found in the cited "
                    "caption or passages and not marked approximate.",
                    severity="error" if claim.type == "author_stated" else "warning",
                    claim_id=claim.id,
                )
        if figure_text is not None and claim.type == "observed" and not claim.approximate:
            printed = figure_text + " " + caption_text
            unread = sorted(n for n in _numbers(claim.text) if not _number_supported(n, printed))
            if unread:
                add(
                    "number_not_in_figure",
                    f"Claim {claim.id} reads {', '.join(unread)} in the figure, but the text "
                    "found in the figure (PDF text and OCR) does not contain it; OCR can miss "
                    "very small or stylised text, so check the figure.",
                    severity="warning",
                    claim_id=claim.id,
                )

    for axis in explanation.visual_encoding.axes:
        check_panel(axis.panel, f"Axis {axis.axis}", None, "warning")
    for entry in explanation.visual_encoding.legend:
        check_panel(entry.panel, "Legend entry", None, "warning")
    for bar in explanation.visual_encoding.scale_bars:
        check_panel(bar.panel, "Scale bar", None, "warning")
    return issues


def locate_text_spans(
    explanation: Explanation, context: Sequence[ContextPassage]
) -> list[tuple[str, int, ContextPassage, int, int]]:
    """(claim id, evidence index, passage, start, end) of every text_span quote found.

    Offsets are relative to the text sent; a quote attributed to the wrong passage is
    located in the passage that contains it.
    """
    found = []
    for claim in explanation.claims:
        for index, evidence in enumerate(claim.evidence):
            if evidence.kind != "text_span" or not (evidence.quote or "").strip():
                continue
            ordered = sorted(context, key=lambda p, ref=evidence.passage_id: p.ref != ref)
            span = next(
                (
                    (passage, located)
                    for gaps in (False, True)
                    for passage in ordered
                    if (located := locate_quote(evidence.quote, passage.text, gaps))
                ),
                None,
            )
            if span:
                found.append((claim.id, index, span[0], *span[1]))
    return found


def status_from_issues(issues: list[ValidationIssue]) -> AnalysisStatus:
    errors = [i for i in issues if i.severity == "error"]
    if any(i.code in INCOMPLETE_CODES for i in errors):
        return AnalysisStatus.INCOMPLETE
    if errors:
        return AnalysisStatus.INVALID
    return AnalysisStatus.OK


MAX_TOKEN_REFS = 3  # an axis value such as "10" can be printed in several places


def resolve_token_refs(explanation: Explanation, tokens: Sequence) -> list[TokenRef]:
    """Where each number that a claim reads in the image is printed in the figure.

    ``tokens`` are the figure's EvidenceToken objects. Only exact (not approximate)
    numbers of observed and inferred claims are linked.
    """
    refs: list[TokenRef] = []
    numbers_by_token = [_numbers(t.text) for t in tokens]
    for claim in explanation.claims:
        if claim.type not in {"observed", "model_inference"} or claim.approximate:
            continue
        for number in sorted(set(_numbers(claim.text))):
            hits = [t for t, found in zip(tokens, numbers_by_token, strict=True) if number in found]
            refs.extend(
                TokenRef(
                    claim_id=claim.id,
                    value=number,
                    text=t.text,
                    bbox_normalized=t.bbox_normalized,
                    source=t.source,
                )
                for t in hits[:MAX_TOKEN_REFS]
            )
    return refs
