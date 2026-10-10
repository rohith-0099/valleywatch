"""Check that every number in generated text exists in the computed data.

A language model can state a figure that looks right and is wrong. So before
any text is shown we pull out every number in it and look for each one among
the values the model actually received from the fact functions. A number
passes if it equals a data value, or is that value rounded to fewer
decimals. Anything else fails the text.
"""
import re

DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
NUMBER = re.compile(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?")
# "1." or "2)" at the start of a line is list numbering, not a figure.
LIST_MARKER = re.compile(r"(?m)^\s*\d+[.)]\s")


# Small numbers written as words are figures too ("two settlements"). "one"
# is left out: it is mostly used as an ordinary word.
NUMBER_WORDS = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
                "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12}
WORD = re.compile(r"\b(" + "|".join(NUMBER_WORDS) + r")\b", re.IGNORECASE)


def _parse(token):
    token = token.replace(",", "")
    decimals = len(token.split(".")[1]) if "." in token else 0
    return float(token), decimals


def numbers_in_text(text):
    """All figures in a text as (value, decimals, original token)."""
    cleaned = LIST_MARKER.sub(" ", text.translate(DEVANAGARI_DIGITS))
    cleaned = WORD.sub(lambda m: str(NUMBER_WORDS[m.group().lower()]), cleaned)
    found = []
    for match in NUMBER.finditer(cleaned):
        token = match.group().rstrip(",")
        value, decimals = _parse(token)
        found.append((value, decimals, token))
    return found


def numbers_in_data(data):
    """Every number in a nested fact structure, including digits inside strings
    (dates, identifiers), so that "28 August 2026" is supported by "2026-08-28"."""
    values = set()

    def walk(item):
        if isinstance(item, bool) or item is None:
            return
        if isinstance(item, (int, float)):
            values.add(float(item))
        elif isinstance(item, str):
            for part in re.findall(r"\d+(?:\.\d+)?", item.translate(DEVANAGARI_DIGITS)):
                values.add(float(part))
        elif isinstance(item, dict):
            for value in item.values():
                walk(value)
        elif isinstance(item, (list, tuple)):
            for value in item:
                walk(value)

    walk(data)
    return values


def unsupported_numbers(text, data, question=""):
    """Tokens in `text` that match nothing in `data` (or in the user's question)."""
    allowed = numbers_in_data(data) | numbers_in_data(question)
    missing = []
    for value, decimals, token in numbers_in_text(text):
        tolerance = 0.5 * 10 ** (-decimals) + 1e-9
        if not any(abs(abs(a) - abs(value)) <= tolerance for a in allowed):
            missing.append(token)
    return missing
