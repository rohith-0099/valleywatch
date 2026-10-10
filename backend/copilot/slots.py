"""Placeholders ("slots"): how numbers get into the model's text.

The model is not allowed to type a number. Each fact it receives comes with
a placeholder such as {buildings_hit}; the model writes the placeholder and
this code swaps in the value afterwards. So a figure cannot be invented,
miscopied, or attached to the wrong thing: {bridges_hit} can only ever
become the bridge count.

Rows of a list (a settlement with its building count, a bridge with its
confidence) are single placeholders rendered here as one piece, so a name
and its numbers cannot be mixed up between rows.
"""
import re

PLACEHOLDER = re.compile(r"\{([a-z0-9_]+)\}")

ROW_TEXT = {
    "en": {
        "cut_off": "{name}: {buildings} buildings; town was {km} km away by road",
        "hospital": "{name}: {buildings} buildings; hospital was {km} km away by road",
        "bridge": "{kind} bridge {label}, {length} m long, confidence {confidence} ({reason})",
        "settlement": "{name}: {buildings} buildings; vehicle road to town: {v_town}; vehicle road "
                      "to hospital: {v_hospital}; any route to town: {a_town}; any route to "
                      "hospital: {a_hospital}",
        "unknown": "unknown", "unnamed": "unnamed settlement", "none": "none",
    },
    "ne": {
        "cut_off": "{name}: {buildings} भवन; बजार सडकबाट {km} कि.मि. टाढा थियो",
        "hospital": "{name}: {buildings} भवन; अस्पताल सडकबाट {km} कि.मि. टाढा थियो",
        "bridge": "{kind} पुल {label}, लम्बाइ {length} मि., विश्वसनीयता {confidence} ({reason})",
        "settlement": "{name}: {buildings} भवन; बजारसम्म सवारी सडक: {v_town}; अस्पतालसम्म सवारी "
                      "सडक: {v_hospital}; बजारसम्म कुनै बाटो: {a_town}; अस्पतालसम्म कुनै बाटो: "
                      "{a_hospital}",
        "unknown": "थाहा छैन", "unnamed": "नाम नभएको बस्ती", "none": "कुनै छैन",
    },
}


def _show(value):
    """A value as it should appear in text."""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        return f"{value:,}".rstrip("0").rstrip(".") if "." in f"{value:,}" else f"{value:,}"
    return str(value)


def _unit(key):
    """Unit that belongs to a fact, read from the end of its name."""
    if key.endswith("_km2"):
        return " km²"
    if key.endswith("_km"):
        return " km"
    if "percent" in key:
        return "%"
    return ""


def _name(row, words):
    name, english = row.get("name"), row.get("name_english")
    if name and english and english != name:
        return f"{name} ({english})"
    return name or english or words["unnamed"]


def _row_text(kind, row, words):
    blank = words["unknown"]
    if kind in ("cut_off", "hospital"):
        km = row.get("km_to_town_before_flood" if kind == "cut_off" else "km_to_hospital_before_flood")
        return words[kind].format(name=_name(row, words), buildings=_show(row.get("buildings") or 0),
                                  km=_show(km) if km is not None else blank)
    if kind == "bridge":
        return words["bridge"].format(
            kind=row.get("road_type") or "", label=row.get("name") or row.get("osm_id") or "",
            length=_show(row.get("length_m")) if row.get("length_m") is not None else blank,
            confidence=row.get("confidence") or blank, reason=row.get("reason") or "")
    return words["settlement"].format(
        name=_name(row, words), buildings=_show(row.get("buildings") or 0),
        v_town=row.get("vehicle_road_to_town") or blank,
        v_hospital=row.get("vehicle_road_to_hospital") or blank,
        a_town=row.get("any_route_to_town") or blank,
        a_hospital=row.get("any_route_to_hospital") or blank)


# For each function with a list: where the rows are, the row kind, and the
# start of its placeholder names.
LISTS = {
    "list_cut_off_settlements": ("settlements", "cut_off", "cut_off"),
    "list_settlements_cut_off_from_hospital": ("settlements", "hospital", "no_hospital"),
    "find_settlement": ("settlements", "settlement", "found"),
    "list_hit_bridges": ("bridges", "bridge", "bridge"),
}


def to_slots(function, arguments, result, language):
    """Turn a function result into (what the model sees, {placeholder: text}).

    The model sees every value next to the placeholder it must write.
    """
    words = ROW_TEXT[language]
    view, registry = {}, {}

    def add(key, value):
        # The unit is part of the filled-in text, so it cannot be left off
        # or changed by the model.
        registry[key] = _show(value) + (_unit(key) if not isinstance(value, str) else "")
        return {"value": value, "unit_included": _unit(key).strip() or None,
                "write_this": "{" + key + "}"}

    rows_key, kind, prefix = LISTS.get(function, (None, None, None))
    if function == "list_cut_off_settlements":
        prefix = f"{prefix}_{arguments.get('level', 'vehicle')}"

    for key, value in result.items():
        if key == rows_key:
            lines = []
            for number, row in enumerate(value, start=1):
                slot = f"{prefix}_{number}"
                registry[slot] = _row_text(kind, row, words)
                lines.append({"shows": registry[slot], "write_this": "{" + slot + "}"})
            registry[f"{prefix}_list"] = ("\n".join(f"- {registry[f'{prefix}_{i}']}"
                                                    for i in range(1, len(value) + 1))
                                          or words["none"])
            view[key] = {"rows": lines, "whole_list_write_this": "{" + prefix + "_list}"}
        elif isinstance(value, dict):
            view[key] = {sub: add(f"{key}_{sub}", item) for sub, item in value.items()
                         if isinstance(item, (int, float, str))}
        elif isinstance(value, list):
            name = f"{prefix + '_' if prefix else ''}{key}"
            # Short lists of numbers (a bounding box) read best on one line;
            # lists of sentences become bullet points.
            if all(isinstance(item, (int, float)) for item in value):
                registry[name] = ", ".join(_show(item) for item in value)
            else:
                registry[name] = "\n".join(f"- {item}" for item in value)
            view[key] = {"items": value, "write_this": "{" + name + "}"}
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            view[key] = add(f"{prefix + '_' if prefix else ''}{key}", value)
        elif isinstance(value, str) and re.search(r"\d", value):
            # Text holding digits (dates, "10 m pixels") is also a placeholder.
            view[key] = add(f"{prefix + '_' if prefix else ''}{key}", value)
        else:
            view[key] = value
    return view, registry


def fill(text, registry):
    """Replace placeholders with their values. Returns (text, unknown names)."""
    unknown = []

    def swap(match):
        key = match.group(1)
        if key not in registry:
            unknown.append(key)
            return match.group(0)
        return registry[key]

    return PLACEHOLDER.sub(swap, text), unknown
