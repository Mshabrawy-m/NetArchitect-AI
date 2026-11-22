"""Minimal, dependency-free Arabic shaping and bidi for PDF export.

The mapping below is an explicit subset of the Unicode Arabic Presentation
Forms-B table. It covers every Arabic letter that appears in the application's
Arabic catalog, so no shaping library, HarfBuzz binding, or network resource is
needed. The helpers are pure functions: they never read fonts, write files, or
consult the clock.

Shaping keeps the logical character order and only substitutes presentation
forms. ReportLab's TTFont draws glyphs left to right, so callers must pass the
shaped text through :func:`logical_to_visual` before drawing it.
"""

from __future__ import annotations

from pathlib import Path

ARABIC_FONT_NAME = "NotoNaskhArabic"
ARABIC_FONT_PATH = Path(__file__).with_name("fonts") / (
    "NotoNaskhArabic-Regular.ttf"
)

# (isolated, final, initial, medial). An empty slot means that the letter does
# not have that joining form (alef-like and right-joining-only letters).
_PRESENTATION_FORMS: dict[str, tuple[str, str, str, str]] = {
    "\u0621": ("\ufe80", "", "", ""),  # hamza
    "\u0622": ("\ufe81", "\ufe82", "", ""),  # alef with madda
    "\u0623": ("\ufe83", "\ufe84", "", ""),  # alef with hamza above
    "\u0624": ("\ufe85", "\ufe86", "", ""),  # waw with hamza
    "\u0625": ("\ufe87", "\ufe88", "", ""),  # alef with hamza below
    "\u0626": ("\ufe89", "\ufe8a", "\ufe8b", "\ufe8c"),  # yeh with hamza
    "\u0627": ("\ufe8d", "\ufe8e", "", ""),  # alef
    "\u0628": ("\ufe8f", "\ufe90", "\ufe91", "\ufe92"),  # beh
    "\u0629": ("\ufe93", "\ufe94", "", ""),  # teh marbuta
    "\u062a": ("\ufe95", "\ufe96", "\ufe97", "\ufe98"),  # teh
    "\u062b": ("\ufe99", "\ufe9a", "\ufe9b", "\ufe9c"),  # theh
    "\u062c": ("\ufe9d", "\ufe9e", "\ufe9f", "\ufea0"),  # jeem
    "\u062d": ("\ufea1", "\ufea2", "\ufea3", "\ufea4"),  # hah
    "\u062e": ("\ufea5", "\ufea6", "\ufea7", "\ufea8"),  # khah
    "\u062f": ("\ufea9", "\ufeaa", "", ""),  # dal
    "\u0630": ("\ufeab", "\ufeac", "", ""),  # thal
    "\u0631": ("\ufead", "\ufeae", "", ""),  # reh
    "\u0632": ("\ufeaf", "\ufeb0", "", ""),  # zain
    "\u0633": ("\ufeb1", "\ufeb2", "\ufeb3", "\ufeb4"),  # seen
    "\u0634": ("\ufeb5", "\ufeb6", "\ufeb7", "\ufeb8"),  # sheen
    "\u0635": ("\ufeb9", "\ufeba", "\ufebb", "\ufebc"),  # sad
    "\u0636": ("\ufebd", "\ufebe", "\ufebf", "\ufec0"),  # dad
    "\u0637": ("\ufec1", "\ufec2", "\ufec3", "\ufec4"),  # tah
    "\u0638": ("\ufec5", "\ufec6", "\ufec7", "\ufec8"),  # zah
    "\u0639": ("\ufec9", "\ufeca", "\ufecb", "\ufecc"),  # ain
    "\u063a": ("\ufecd", "\ufece", "\ufecf", "\ufed0"),  # ghain
    "\u0641": ("\ufed1", "\ufed2", "\ufed3", "\ufed4"),  # feh
    "\u0642": ("\ufed5", "\ufed6", "\ufed7", "\ufed8"),  # qaf
    "\u0643": ("\ufed9", "\ufeda", "\ufedb", "\ufedc"),  # kaf
    "\u0644": ("\ufedd", "\ufede", "\ufedf", "\ufee0"),  # lam
    "\u0645": ("\ufee1", "\ufee2", "\ufee3", "\ufee4"),  # meem
    "\u0646": ("\ufee5", "\ufee6", "\ufee7", "\ufee8"),  # noon
    "\u0647": ("\ufee9", "\ufeea", "\ufeeb", "\ufeec"),  # heh
    "\u0648": ("\ufeed", "\ufeee", "", ""),  # waw
    "\u0649": ("\ufeef", "\ufef0", "", ""),  # alef maksura
    "\u064a": ("\ufef1", "\ufef2", "\ufef3", "\ufef4"),  # yeh
}

# lam + alef ligatures: (isolated, final).
_LAM_ALEF: dict[str, tuple[str, str]] = {
    "\u0627": ("\ufefb", "\ufefc"),
    "\u0622": ("\ufef5", "\ufef6"),
    "\u0623": ("\ufef7", "\ufef8"),
    "\u0625": ("\ufef9", "\ufefa"),
}

_TATWEEL = "\u0640"
_LAM_INITIAL = "\ufedf"
_LAM_MEDIAL = "\ufee0"

# Arabic punctuation and Arabic-Indic digits are RTL for run purposes.
_ARABIC_RANGES = (
    (0x0600, 0x06FF),
    (0x0750, 0x077F),
    (0x08A0, 0x08FF),
    (0xFB50, 0xFDFF),
    (0xFE70, 0xFEFF),
)


def is_arabic_char(character: str) -> bool:
    """Return whether one character belongs to an Arabic Unicode block."""
    if not character:
        return False
    codepoint = ord(character)
    return any(start <= codepoint <= end for start, end in _ARABIC_RANGES)


def contains_arabic(text: str) -> bool:
    """Return whether ``text`` contains any Arabic character."""
    if not text:
        return False
    return any(is_arabic_char(character) for character in text)


def _is_transparent(character: str) -> bool:
    """Return whether a character is preserved but ignored for joining."""
    if character == _TATWEEL:
        return True
    codepoint = ord(character)
    return 0x064B <= codepoint <= 0x065F


def _neighbours(text: str) -> tuple[list[str | None], list[str | None]]:
    """Return the nearest shaping letter to the left and right of each index."""
    length = len(text)
    previous: list[str | None] = [None] * length
    following: list[str | None] = [None] * length
    last: str | None = None
    for index, character in enumerate(text):
        previous[index] = last
        if character in _PRESENTATION_FORMS:
            last = character
        elif not _is_transparent(character):
            last = None
    last = None
    for index in range(length - 1, -1, -1):
        character = text[index]
        following[index] = last
        if character in _PRESENTATION_FORMS:
            last = character
        elif not _is_transparent(character):
            last = None
    return previous, following


def shape_arabic(text: str) -> str:
    """Replace Arabic letters with context-appropriate presentation forms.

    Tatweel and diacritics are copied verbatim and are transparent to the
    joining decision. Latin text, digits, and punctuation are untouched.
    """
    if not text:
        return text
    characters = list(text)
    previous, following = _neighbours(text)
    shaped: list[str] = []
    for index, character in enumerate(characters):
        forms = _PRESENTATION_FORMS.get(character)
        if forms is None:
            shaped.append(character)
            continue
        before = previous[index]
        after = following[index]
        joins_left = bool(before and _PRESENTATION_FORMS[before][2])
        joins_right = bool(after and _PRESENTATION_FORMS[after][1])
        if joins_left and joins_right and forms[3]:
            shaped.append(forms[3])
        elif joins_left and forms[1]:
            shaped.append(forms[1])
        elif joins_right and forms[2]:
            shaped.append(forms[2])
        else:
            shaped.append(forms[0])
    # Optional lam-alef ligatures. Only directly adjacent letters are merged so
    # diacritics keep their original position relative to their base letter.
    for index in range(len(shaped) - 1):
        if shaped[index] not in (_LAM_INITIAL, _LAM_MEDIAL):
            continue
        alef = characters[index + 1]
        ligature = _LAM_ALEF.get(alef)
        if ligature is None:
            continue
        expected_final = _PRESENTATION_FORMS[alef][1]
        if shaped[index + 1] != expected_final:
            continue
        shaped[index] = ligature[1] if shaped[index] == _LAM_MEDIAL else ligature[0]
        shaped[index + 1] = ""
    return "".join(shaped)


def logical_to_visual(text: str) -> str:
    """Order shaped runs for ReportLab's left-to-right glyph drawing.

    RTL runs are emitted in reverse paragraph order and their characters are
    reversed, while LTR runs (IPs, CIDRs, URLs, Latin words) keep their exact
    internal order. Call :func:`shape_arabic` first when joining forms matter.
    """
    if not text:
        return text
    runs: list[tuple[str, list[str]]] = []
    current_direction = ""
    for character in text:
        direction = "rtl" if is_arabic_char(character) else "ltr"
        if not runs or direction != current_direction:
            runs.append((direction, []))
            current_direction = direction
        runs[-1][1].append(character)
    if len(runs) == 1:
        direction, characters = runs[0]
        if direction == "rtl":
            return "".join(reversed(characters))
        return text
    visual: list[str] = []
    for direction, characters in reversed(runs):
        visual.append(
            "".join(reversed(characters))
            if direction == "rtl"
            else "".join(characters)
        )
    return "".join(visual)


__all__ = [
    "ARABIC_FONT_NAME",
    "ARABIC_FONT_PATH",
    "contains_arabic",
    "is_arabic_char",
    "logical_to_visual",
    "shape_arabic",
]
