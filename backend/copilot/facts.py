"""The only facts the language model may use: functions over one run's outputs."""
import json
from pathlib import Path


class RunFacts:
    """Read-only view of a finished run folder."""

    def __init__(self, run_folder):
        self.folder = Path(run_folder)
        self.summary = json.loads((self.folder / "summary.json").read_text())
        self.settlements = self._features("settlements")
        self.bridges = self._features("bridges")
        self.road_hits = self._features("road_hits")

    def _features(self, name):
        path = self.folder / f"{name}.geojson"
        if not path.exists():
            return []
        rows = []
        for feature in json.loads(path.read_text())["features"]:
            row = dict(feature["properties"])
            geometry = feature.get("geometry")
            if geometry and geometry["type"] == "Point":
                row["longitude"] = round(geometry["coordinates"][0], 4)
                row["latitude"] = round(geometry["coordinates"][1], 4)
            rows.append(row)
        return rows

    @staticmethod
    def _derived_label(settlement):
        """Name for a settlement that was derived from building clusters."""
        if settlement.get("derived"):
            return (f"unnamed building cluster near {settlement.get('latitude')} N, "
                    f"{settlement.get('longitude')} E")
        return None

    # ---- Functions offered to the model --------------------------------------

    def get_overview(self):
        """Headline figures for the whole analysed area."""
        s = self.summary
        totals, damage, cutoff = s["totals"], s["damage"], s["cutoff"]
        return {
            "flood_date": s["inputs"]["flood_date"],
            "area_box_west_south_east_north": s["inputs"]["bbox_west_south_east_north"],
            "new_water_km2": totals["water_km2"],
            "debris_covered_km2": totals["debris_km2"],
            "buildings_hit": damage["buildings_hit"],
            "buildings_possibly_affected": damage.get("buildings_possibly_affected", 0),
            "buildings_mapped_in_area": damage["buildings_total"],
            "roads_hit_km": damage["roads_hit_km"],
            "roads_mapped_km": damage["roads_total_km"],
            "bridges_hit": damage["bridges_hit"],
            "bridges_mapped": damage["bridges_total"],
            "settlements_in_area": cutoff["settlements_in_box"],
            "settlements_without_vehicle_road": cutoff["no_vehicle_road"]["settlements"],
            "buildings_in_settlements_without_vehicle_road": cutoff["no_vehicle_road"]["buildings"],
            "settlements_with_no_route_at_all": cutoff["no_route_at_all"]["settlements"],
            "buildings_in_settlements_with_no_route_at_all": cutoff["no_route_at_all"]["buildings"],
            "settlements_cut_off_from_every_hospital_by_vehicle":
                cutoff["no_vehicle_road"]["cut_off_from_hospital"],
            "note": "Buildings are a rough guide to population; no population figure exists.",
        }

    def get_satellite_scenes(self):
        """Which satellite images and map data the analysis used."""
        s = self.summary
        radar, optical = s["sentinel1"], s["sentinel2"]["check"]
        return {
            "radar_image_before_flood": radar["before"]["date"],
            "radar_image_after_flood": radar["after"]["date"],
            "days_between_flood_and_radar_image_after": radar["days_after"],
            "radar_track": f"relative orbit {radar['relative_orbit']} {radar['direction'].lower()}",
            "analysis_mode": s["inputs"].get("mode", "quick"),
            "optical_images_used": optical.get("used", False),
            "percent_of_valley_with_clear_optical_view": optical.get("reach_zone_clear_percent"),
            "openstreetmap_snapshot_date": s["openstreetmap"]["snapshot_date"],
            "why_these_radar_images": radar["reason"],
        }

    def get_damage_details(self):
        """Damage counts split by confidence level and by hazard."""
        d = self.summary["damage"]
        return {
            "buildings_hit_by_confidence": d["buildings_hit_by_confidence"],
            "buildings_hit_by_hazard": d["buildings_hit_by_hazard"],
            "buildings_possibly_affected": d.get("buildings_possibly_affected", 0),
            "road_sections_hit": d["roads_hit_sections"],
            "road_sections_hit_by_confidence": d["roads_hit_sections_by_confidence"],
            "bridges_hit_by_confidence": d["bridges_hit_by_confidence"],
            "bridges_over_changed_river_but_not_hit": d.get("bridges_exposed_not_hit", 0),
            "meaning": "A hit is an estimate from 10 m satellite pixels, not a field report.",
        }

    def list_cut_off_settlements(self, level="vehicle", limit=10):
        """Cut-off settlements, largest first.

        level: "vehicle" = no road a vehicle can use; "any" = no route at
        all, not even a footpath.
        """
        level = "any" if level == "any" else "vehicle"
        limit = max(1, min(int(limit), 30))
        chosen = [s for s in self.settlements if s.get(f"cut_off_{level}")]
        chosen.sort(key=lambda s: -(s.get("buildings") or 0))
        rows = [{
            "name": s.get("name") or self._derived_label(s), "name_english": s.get("name_en"),
            "buildings": s.get("buildings"),
            "route_to_town": s.get(f"{level}_town_status"),
            "route_to_hospital": s.get(f"{level}_hospital_status"),
            "km_to_town_before_flood": s.get(f"{level}_town_km_before"),
            "km_to_hospital_before_flood": s.get(f"{level}_hospital_km_before"),
            "broken_road_osm_id": s.get(f"{level}_town_broken_link")
                                  or s.get(f"{level}_hospital_broken_link"),
            "latitude": s.get("latitude"), "longitude": s.get("longitude"),
        } for s in chosen[:limit]]
        return {"level": level, "total_matching": len(chosen), "listed": len(rows),
                "settlements": rows}

    def list_settlements_cut_off_from_hospital(self, limit=10):
        """Settlements that no vehicle can drive from to any hospital, largest first."""
        limit = max(1, min(int(limit), 30))
        chosen = [s for s in self.settlements if s.get("vehicle_hospital_status") == "cut off"]
        chosen.sort(key=lambda s: -(s.get("buildings") or 0))
        return {"total_matching": len(chosen), "listed": min(len(chosen), limit),
                "settlements": [{"name": s.get("name"), "name_english": s.get("name_en"),
                                 "buildings": s.get("buildings"),
                                 "km_to_hospital_before_flood": s.get("vehicle_hospital_km_before"),
                                 "reachable_on_foot": s.get("any_hospital_status")}
                                for s in chosen[:limit]]}

    def find_settlement(self, name):
        """Look up one settlement by (part of) its Nepali or English name."""
        wanted = str(name).strip().lower()
        found = [s for s in self.settlements
                 if wanted and (wanted in str(s.get("name") or "").lower()
                                or wanted in str(s.get("name_en") or "").lower())]
        return {"matches": len(found), "settlements": [{
            "name": s.get("name"), "name_english": s.get("name_en"),
            "buildings": s.get("buildings"),
            "vehicle_road_to_town": s.get("vehicle_town_status"),
            "vehicle_road_to_hospital": s.get("vehicle_hospital_status"),
            "any_route_to_town": s.get("any_town_status"),
            "any_route_to_hospital": s.get("any_hospital_status"),
            "km_to_town_before_flood": s.get("vehicle_town_km_before") or s.get("any_town_km_before"),
            "km_to_town_now": s.get("vehicle_town_km_after") or s.get("any_town_km_after"),
        } for s in found[:5]]}

    def list_hit_bridges(self, limit=10):
        """Bridges judged hit, highest confidence first."""
        limit = max(1, min(int(limit), 30))
        order = {"high": 0, "medium": 1, "low": 2}
        hit = [b for b in self.bridges if b.get("hit")]
        hit.sort(key=lambda b: order.get(b.get("confidence_level"), 3))
        return {"total_hit": len(hit), "listed": min(len(hit), limit), "bridges": [{
            "osm_id": b.get("osm_id"), "road_type": b.get("highway"), "name": b.get("name"),
            "confidence": b.get("confidence_level"), "reason": b.get("reason"),
            "length_m": b.get("length_m")} for b in hit[:limit]]}

    def get_reliability(self):
        """How far the result can be trusted, and what the system cannot do."""
        s = self.summary
        test = s.get("acceptance_test") or {}
        share = (test.get("no_flood_as_percent_of_flood") or {}).get("total")
        return {
            "self_check": ("The same rules were run on satellite images from before the "
                           "flood. The area they map there is false alarm."),
            "false_alarm_percent_of_mapped_area": share,
            "percent_of_valley_floor_radar_cannot_see":
                s["totals"]["corridor_not_mapped_by_radar_percent"],
            "polygons_by_confidence": s["totals"]["polygons_by_confidence"],
            "limitations": LIMITATIONS["en"],
        }


LIMITATIONS = {
    "en": [
        "Satellites pass only every few days, so this cannot warn of a flood in advance.",
        "Radar cannot see steep valley walls; damage there may be missed.",
        "A feature marked as hit is an estimate from 10 m pixels, not a field-verified report.",
        "OpenStreetMap is incomplete in remote areas, so buildings and trails are undercounted.",
        "Building counts are only a rough guide to how many people live in a place.",
        "Roads outside the analysed box are assumed intact.",
    ],
    "ne": [
        "भू-उपग्रह केही दिनको अन्तरमा मात्र आउँछ, त्यसैले यसले बाढीको पूर्वसूचना दिन सक्दैन।",
        "राडारले ठाडो भिरालो देख्न सक्दैन; त्यहाँको क्षति छुट्न सक्छ।",
        "प्रभावित भनिएको संरचना १० मिटर पिक्सेलबाट गरिएको अनुमान हो, स्थलगत प्रमाणित विवरण होइन।",
        "दुर्गम क्षेत्रमा OpenStreetMap अपूर्ण छ, त्यसैले भवन र गोरेटो कम गनिएका हुन सक्छन्।",
        "भवन सङ्ख्या जनसङ्ख्याको मोटामोटी सङ्केत मात्र हो।",
        "विश्लेषण क्षेत्रबाहिरका सडक सग्लै छन् भनी मानिएको छ।",
    ],
}

# Function descriptions sent to the model (OpenAI-style tool schema).
TOOLS = [
    {"name": "get_overview", "description": "Headline figures: flooded and debris area, "
     "buildings, roads and bridges hit, settlements cut off.", "parameters": {}},
    {"name": "get_satellite_scenes", "description": "Dates of the satellite images used, "
     "the radar track, optical coverage and the map snapshot date.", "parameters": {}},
    {"name": "get_damage_details", "description": "Damage counts by confidence level and hazard.",
     "parameters": {}},
    {"name": "list_cut_off_settlements", "description": "Cut-off settlements, largest first. "
     "level 'vehicle' = no vehicle road, 'any' = no route at all.",
     "parameters": {"level": {"type": "string", "enum": ["vehicle", "any"]},
                    "limit": {"type": "integer"}}},
    {"name": "list_settlements_cut_off_from_hospital", "description": "Settlements from which "
     "no vehicle can reach any hospital, largest first.",
     "parameters": {"limit": {"type": "integer"}}},
    {"name": "find_settlement", "description": "Status of one settlement, looked up by name "
     "(Nepali or English, partial names allowed).",
     "parameters": {"name": {"type": "string"}}, "required": ["name"]},
    {"name": "list_hit_bridges", "description": "Bridges judged hit, with confidence and reason.",
     "parameters": {"limit": {"type": "integer"}}},
    {"name": "get_reliability", "description": "False-alarm level, radar blind share and the "
     "list of things the system cannot do.", "parameters": {}},
]


def tool_schemas():
    return [{"type": "function", "function": {
        "name": t["name"], "description": t["description"],
        "parameters": {"type": "object", "properties": t["parameters"],
                       "required": t.get("required", [])}}} for t in TOOLS]


def call_tool(facts, name, arguments):
    """Run one function by name. Unknown names and bad arguments return an error text."""
    if name not in {t["name"] for t in TOOLS}:
        return {"error": f"There is no function called {name}."}
    try:
        return getattr(facts, name)(**(arguments or {}))
    except (TypeError, ValueError) as error:
        return {"error": f"Bad arguments for {name}: {error}"}
