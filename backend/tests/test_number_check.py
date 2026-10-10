"""The copilot's number check must catch invented figures."""
from copilot.check import unsupported_numbers

DATA = {"water_km2": 3.321, "buildings_hit": 1997, "after": "2026-08-28", "false_alarm": 3.8}


def test_exact_and_rounded_numbers_pass():
    text = "About 3.3 km2 of new water and 1,997 buildings, seen on 28 August 2026."
    assert unsupported_numbers(text, DATA) == []


def test_invented_numbers_fail():
    assert unsupported_numbers("Around 2,000 buildings in 12 villages.", DATA) == ["2,000", "12"]


def test_devanagari_digits_and_number_words_are_checked():
    assert unsupported_numbers("१९९७ भवन", DATA) == []
    assert unsupported_numbers("१५०० भवन", DATA) == ["1500"]
    assert unsupported_numbers("Seven bridges were hit.", DATA) == ["Seven".lower()] or \
        unsupported_numbers("Seven bridges were hit.", DATA) == ["7"]


def test_list_numbering_is_not_a_figure():
    assert unsupported_numbers("1. First point\n2. Second point", DATA) == []


def test_numbers_from_the_question_are_allowed():
    assert unsupported_numbers("Here are the 5 largest.", DATA, "Give the 5 largest") == []
