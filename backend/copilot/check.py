"""Check that the model typed no number of its own.

The model must write placeholders such as {buildings_hit}; code fills them
in (see `slots.py`). So in the model's raw text, any digit outside a
placeholder is a number the model made up or copied by hand, and the text
is rejected. Numbers that the user typed in the question are allowed back
("the 5 largest").
"""
import re

from .slots import PLACEHOLDER

DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
NUMBER = re.compile(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?")
# "1." or "2)" at the start of a line is list numbering, not a figure.
LIST_MARKER = re.compile(r"(?m)^\s*\d+[.)]\s")
# Small numbers written as words are figures too ("two settlements"). "one"
# is left out: it is mostly used as an ordinary word.
NUMBER_WORDS = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
                "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12}
WORD = re.compile(r"\b(" + "|".join(NUMBER_WORDS) + r")\b", re.IGNORECASE)


def _numbers(text):
    cleaned = LIST_MARKER.sub(" ", text.translate(DEVANAGARI_DIGITS))
    cleaned = WORD.sub(lambda m: str(NUMBER_WORDS[m.group().lower()]), cleaned)
    return [m.group().rstrip(",").replace(",", "") for m in NUMBER.finditer(cleaned)]


def numbers_typed_by_model(raw_text, question=""):
    """Numbers in the model's raw text that are not placeholders.

    An empty list means the text is clean.
    """
    without_placeholders = PLACEHOLDER.sub(" ", raw_text)
    allowed = {float(n) for n in _numbers(question)}
    return [n for n in _numbers(without_placeholders) if float(n) not in allowed]
