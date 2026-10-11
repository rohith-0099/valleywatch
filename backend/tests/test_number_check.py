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
    result = {"level": "any",
              "settlements": [{"name": "A", "buildings": 706, "km_to_town_before_flood": 9.13},
                              {"name": "B", "buildings": 12, "km_to_town_before_flood": None}]}
    _, registry = to_slots("list_cut_off_settlements", {"level": "any"}, result, "en")
    assert registry["cut_off_any_1"] == "A: 706 buildings; town was 9.13 km away by road"
    assert "B: 12 buildings" in registry["cut_off_any_2"]


def test_null_arguments_fall_back_to_defaults():
    from copilot.facts import call_tool, tool_schemas

    class Facts:
        def list_hit_bridges(self, limit=10):
            return {"limit_used": limit}

    assert call_tool(Facts(), "list_hit_bridges", {"limit": None}) == {"limit_used": 10}
    limit = next(t for t in tool_schemas() if t["function"]["name"] == "list_hit_bridges")
    assert "null" in limit["function"]["parameters"]["properties"]["limit"]["type"]


def test_misspelt_placeholder_is_caught_and_level_comes_from_the_result():
    assert fill("{Cut_Off_None_1}", {})[1] == ["Cut_Off_None_1"]
    result = {"level": "vehicle", "settlements": [{"name": "A", "buildings": 3}]}
    _, registry = to_slots("list_cut_off_settlements", {"level": None}, result, "en")
    assert "cut_off_vehicle_1" in registry


def test_units_come_from_the_fact_name():
    _, registry = to_slots("get_overview", {}, {"flooded_area_km2": 3.5, "percent_of_box": 12.0,
                                                "road_km": 4.25, "bridges_hit": 0}, "en")
    assert registry == {"flooded_area_km2": "3.5 km²", "percent_of_box": "12%",
                        "road_km": "4.25 km", "bridges_hit": "0"}


def test_empty_list_says_none_in_the_report_language():
    assert to_slots("list_hit_bridges", {}, {"bridges": []}, "en")[1] == {"bridge_list": "none"}
    assert to_slots("list_hit_bridges", {}, {"bridges": []}, "ne")[1] == {"bridge_list": "कुनै छैन"}
