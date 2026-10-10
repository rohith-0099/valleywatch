"""The copilot may not type numbers: it writes placeholders that code fills."""
from copilot.check import numbers_typed_by_model
from copilot.slots import fill, to_slots


def test_placeholders_are_clean_and_get_filled():
    view, registry = to_slots("get_overview", {}, {"buildings_hit": 1997, "bridges_hit": 40,
                                                  "flood_date": "2026-08-26"}, "en")
    assert view["buildings_hit"]["write_this"] == "{buildings_hit}"
    raw = "{buildings_hit} buildings and {bridges_hit} bridges were hit on {flood_date}."
    assert numbers_typed_by_model(raw) == []
    assert fill(raw, registry) == ("1,997 buildings and 40 bridges were hit on 2026-08-26.", [])


def test_typed_numbers_are_caught():
    assert numbers_typed_by_model("About 2,000 buildings in 12 villages.") == ["2000", "12"]
    assert numbers_typed_by_model("१५०० भवन") == ["1500"]
    assert numbers_typed_by_model("Seven bridges were hit.") == ["7"]


def test_list_numbering_and_question_numbers_are_allowed():
    assert numbers_typed_by_model("1. {cut_off_vehicle_1}\n2. {cut_off_vehicle_2}") == []
    assert numbers_typed_by_model("Here are the 5 largest.", "Give the 5 largest") == []


def test_unknown_placeholder_is_reported():
    assert fill("{made_up_figure} people", {"buildings_hit": "1,997"}) == (
        "{made_up_figure} people", ["made_up_figure"])


def test_rows_keep_name_and_number_together():
    result = {"settlements": [{"name": "A", "buildings": 706, "km_to_town_before_flood": 9.13},
                              {"name": "B", "buildings": 12, "km_to_town_before_flood": None}]}
    _, registry = to_slots("list_cut_off_settlements", {"level": "any"}, result, "en")
    assert registry["cut_off_any_1"] == "A: 706 buildings; town was 9.13 km away by road"
    assert "B: 12 buildings" in registry["cut_off_any_2"]
