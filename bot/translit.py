"""Uzbek Latin → Cyrillic transliteration.

Used only for the MAʼLUMOT Word document, whose headings are Cyrillic while
DEPARTMENT and NAME are written in Latin.

Order matters: multi-character sequences are tried before single letters, so
``sh`` becomes ``ш`` rather than ``сҳ``, and the apostrophe in ``oʻ``/``gʻ`` is
consumed as a modifier before the standalone tutuq belgisi rule can turn it
into ``ъ``.

Transliteration is never perfect for proper nouns. If a name comes out wrong,
write that entry of NAME in Cyrillic directly — text already in Cyrillic is
passed through untouched.
"""

from __future__ import annotations

# Every apostrophe shape people actually type, plus the correct modifier letters.
APOSTROPHES = "'‘’ʻʼʽ`´"

# Longest first. Keys are lowercase; capitalisation is handled by the caller.
_MULTI: tuple[tuple[str, str], ...] = (
    ("o" + "APOS", "ў"),
    ("g" + "APOS", "ғ"),
    ("sh", "ш"),
    ("ch", "ч"),
    ("ya", "я"),
    ("yo", "ё"),
    ("yu", "ю"),
    ("ye", "е"),
    ("ts", "ц"),
)

_SINGLE: dict[str, str] = {
    "a": "а",
    "b": "б",
    "c": "ц",
    "d": "д",
    "e": "е",  # word-initial handled separately -> э
    "f": "ф",
    "g": "г",
    "h": "ҳ",
    "i": "и",
    "j": "ж",
    "k": "к",
    "l": "л",
    "m": "м",
    "n": "н",
    "o": "о",
    "p": "п",
    "q": "қ",
    "r": "р",
    "s": "с",
    "t": "т",
    "u": "у",
    "v": "в",
    "w": "в",
    "x": "х",
    "y": "й",
    "z": "з",
    "ō": "ў",
    "ǒ": "ў",
    "ģ": "ғ",
    "ğ": "ғ",
}

# Pre-expand the "APOS" placeholder into one rule per apostrophe shape.
_RULES: list[tuple[str, str]] = []
for _pattern, _replacement in _MULTI:
    if "APOS" in _pattern:
        base = _pattern.replace("APOS", "")
        for mark in APOSTROPHES:
            _RULES.append((base + mark, _replacement))
    else:
        _RULES.append((_pattern, _replacement))
_RULES.sort(key=lambda pair: len(pair[0]), reverse=True)


def _match_case(latin: str, cyrillic: str) -> str:
    """Carry the Latin source's capitalisation onto the Cyrillic result."""
    if latin[0].isupper():
        return cyrillic.upper() if len(latin) > 1 and latin[1:].isupper() else cyrillic.capitalize()
    return cyrillic


def _is_word_start(text: str, position: int) -> bool:
    if position == 0:
        return True
    previous = text[position - 1]
    return not (previous.isalpha() or previous in APOSTROPHES)


def transliterate(text: str | None) -> str:
    """Latin Uzbek → Cyrillic. Digits, punctuation and Cyrillic pass through."""
    if not text:
        return ""

    out: list[str] = []
    i = 0
    length = len(text)

    while i < length:
        chunk = text[i : i + 3]
        lowered = chunk.casefold()
        matched = False

        for pattern, replacement in _RULES:
            if not lowered.startswith(pattern):
                continue
            # "Yoʻldoshev" is y + oʻ, not yo + ʼ. If a rule would swallow an
            # o or g that an apostrophe belongs to, let the longer oʻ/gʻ rule
            # have it on the next pass.
            following = text[i + len(pattern) : i + len(pattern) + 1]
            if pattern[-1] in "og" and following in APOSTROPHES:
                continue
            source = text[i : i + len(pattern)]
            out.append(_match_case(source, replacement))
            i += len(pattern)
            matched = True
            break
        if matched:
            continue

        char = text[i]
        lower = char.casefold()

        if lower == "e":
            replacement = "э" if _is_word_start(text, i) else "е"
            out.append(_match_case(char, replacement))
            i += 1
            continue

        if char in APOSTROPHES:
            # Tutuq belgisi: only meaningful between letters (maʼlumot).
            after = text[i + 1] if i + 1 < length else ""
            before = text[i - 1] if i else ""
            out.append("ъ" if before.isalpha() and after.isalpha() else "")
            i += 1
            continue

        if lower in _SINGLE:
            out.append(_match_case(char, _SINGLE[lower]))
            i += 1
            continue

        out.append(char)
        i += 1

    return "".join(out)


def split_name(full_name: str) -> tuple[str, str]:
    """``"Asadov Javoxir Alisherovich"`` → ``("Asadov", "Javoxir Alisherovich")``.

    The template wants the surname on its own line above the rest, so this is
    "first word up to the first space", exactly as A.docx specifies.
    """
    cleaned = " ".join((full_name or "").split())
    if not cleaned:
        return "", ""
    surname, _, rest = cleaned.partition(" ")
    return surname, rest
