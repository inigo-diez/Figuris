"""Find references to figures in article text: 'Fig. 2b', 'Figs. 2–4', '(Extended Data Fig. 1a,c)'.

Each mention names one figure label (normalized like caption labels, e.g.
'Figure 2', 'Extended Data Figure 1', 'Scheme 1') and the panels it cites.
Supplementary figures keep their prefix, so they never match a main figure.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

HEAD = re.compile(
    r"(?<![A-Za-z])"
    r"(?P<prefix>(?:Extended\s+Data|Supplementary|Suppl\.?|Supplemental)\s+)?"
    r"(?P<word>Figures?|FIGURES?|Figs?\.?|FIGS?\.?|Figuras?|Schemes?|SCHEMES?)"
    r"\s*(?=\d|[IVX]+(?![A-Za-z]))"
)
NUMBER = re.compile(r"(?P<num>\d{1,3})(?!\d)(?![.,]\d)|(?P<roman>[IVX]{1,5})(?![A-Za-z\d])")
_PANEL = r"(?P<a>[a-zA-Z])(?:\s*[–—-]\s*(?P<b>[a-zA-Z]))?"
# "2b", "2a–c" or "3(b)"; a closing parenthesis only belongs to the panel if it opened one.
PANELS = (re.compile(rf"\({_PANEL}\)"), re.compile(rf"{_PANEL}(?![A-Za-z])"))
SEPARATOR = re.compile(r"\s*(?P<sep>,|;|and|&|[–—-]|to)\s*")
ROMAN = {"I": 1, "V": 5, "X": 10}
MENTIONS_VERSION = "mentions/0.1"


@dataclass
class Mention:
    label: str
    number: str
    panels: list[str] = field(default_factory=list)
    start: int = 0
    end: int = 0
    text: str = ""


def _roman(token: str) -> int:
    total, prev = 0, 0
    for ch in reversed(token):
        value = ROMAN[ch]
        total = total - value if value < prev else total + value
        prev = max(prev, value)
    return total


def _expand(a: str, b: str | None) -> list[str]:
    if not b or ord(b) < ord(a) or ord(b) - ord(a) > 12:
        return [a] if not b else [a, b]
    return [chr(c) for c in range(ord(a), ord(b) + 1)]


def _label(prefix: str | None, word: str, number: str) -> str:
    noun = "Scheme" if word.lower().startswith("scheme") else "Figure"
    if prefix:
        prefix = " ".join(prefix.split())
        prefix = "Extended Data" if prefix.lower().startswith("extended") else "Supplementary"
        return f"{prefix} {noun} {number}"
    return f"{noun} {number}"


def _panels(text: str, pos: int) -> tuple[list[str], int] | None:
    for pattern in PANELS:
        match = pattern.match(text, pos)
        if match:
            return _expand(match.group("a"), match.group("b")), match.end()
    return None


def find_mentions(text: str) -> list[Mention]:
    mentions: list[Mention] = []
    for head in HEAD.finditer(text):
        refs: list[tuple[str, list[str], int]] = []  # (number, panels, end)
        pos = head.end()
        allow_roman = not head.group("word").lower().startswith("scheme")
        pending_range = False
        while True:
            number = NUMBER.match(text, pos)
            if number and (number.group("num") or (allow_roman and not refs)):
                value = number.group("num") or str(_roman(number.group("roman")))
                pos = number.end()
                panels: list[str] = []
                panel = _panels(text, pos)
                if panel and number.group("num"):
                    panels, pos = panel
                if pending_range and refs and value.isdigit() and refs[-1][0].isdigit():
                    first, last = int(refs[-1][0]) + 1, int(value)
                    if 0 < last - first < 20:
                        refs += [(str(n), [], pos) for n in range(first, last)]
                refs.append((value, panels, pos))
                pending_range = False
            elif refs and refs[-1][1]:
                # More panels of the previous figure: "Fig. 2a, c" or "Fig. 2C and D".
                panel = _panels(text, pos)
                if not panel or panel[0][0].islower() != refs[-1][1][0].islower():
                    break
                refs[-1][1].extend(panel[0])
                pos = panel[1]
                refs[-1] = (refs[-1][0], refs[-1][1], pos)
            else:
                break
            separator = SEPARATOR.match(text, pos)
            if not separator:
                break
            pending_range = separator.group("sep") in {"–", "—", "-", "to"}
            pos = separator.end()
        end = refs[-1][2] if refs else head.end()
        for number, panels, _ in refs:
            mentions.append(
                Mention(
                    label=_label(head.group("prefix"), head.group("word"), number),
                    number=number,
                    panels=sorted(set(panels), key=panels.index),
                    start=head.start(),
                    end=end,
                    text=text[head.start() : end],
                )
            )
    return mentions
