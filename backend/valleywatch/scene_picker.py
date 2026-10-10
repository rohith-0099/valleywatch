"""Step 1: choose which satellite scenes to compare.

Radar change detection only works when the before and after images were taken
from the same position in the sky. Sentinel-1 flies fixed tracks called
"relative orbits". Two images on the same relative orbit see every slope from
the same angle, so any difference between them is a real change on the ground
and not a change of viewpoint. This module finds such a pair.
"""
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

import requests
from shapely.geometry import box, shape
from shapely.ops import unary_union

from .config import CATALOGUE_URL, Settings


def _bbox_wkt(bbox):
    west, south, east, north = bbox
    return (f"POLYGON(({west} {south},{east} {south},{east} {north},"
            f"{west} {north},{west} {south}))")


def _query_catalogue(filter_text):
    """Run one OData query and follow pagination until all results are read."""
    params = {"$filter": filter_text, "$orderby": "ContentDate/Start asc",
              "$top": 200, "$expand": "Attributes"}
    url, products = CATALOGUE_URL, []
    while url:
        response = requests.get(url, params=params, timeout=60)
        response.raise_for_status()
        payload = response.json()
        products.extend(payload.get("value", []))
        url, params = payload.get("@odata.nextLink"), None
    return products


def _parse_time(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def search_sentinel1(bbox, start, end):
    """List Sentinel-1 IW GRD dual-pol scenes touching the box in a time window."""
    filter_text = (
        "Collection/Name eq 'SENTINEL-1' and contains(Name,'_IW_GRDH_') "
        f"and OData.CSC.Intersects(area=geography'SRID=4326;{_bbox_wkt(bbox)}') "
        f"and ContentDate/Start ge {start.isoformat()}T00:00:00.000Z "
        f"and ContentDate/Start lt {end.isoformat()}T00:00:00.000Z")
    scenes, seen = [], set()
    for product in _query_catalogue(filter_text):
        attrs = {a["Name"]: a["Value"] for a in product.get("Attributes", [])}
        # We need both polarisations for the water/debris rules.
        if attrs.get("polarisationChannels") != "VV&VH":
            continue
        # The catalogue lists each acquisition twice (plain and COG format).
        key = product["Name"].replace("_COG", "")[:63]
        if key in seen:
            continue
        seen.add(key)
        scenes.append({
            "id": product["Name"],
            "start": _parse_time(product["ContentDate"]["Start"]),
            "relative_orbit": int(attrs["relativeOrbitNumber"]),
            "direction": attrs["orbitDirection"],
            "platform": "S1" + str(attrs.get("platformSerialIdentifier", "")),
            "footprint": shape(product["GeoFootprint"]),
        })
    return scenes


def _group_into_passes(scenes):
    """Merge scenes from one overpass.

    A single pass is often cut into several consecutive products. They share a
    track and a date, so we treat them as one image and union their footprints.
    """
    groups = defaultdict(list)
    for scene in scenes:
        key = (scene["relative_orbit"], scene["direction"], scene["start"].date())
        groups[key].append(scene)
    passes = []
    for (orbit, direction, day), members in groups.items():
        passes.append({
            "relative_orbit": orbit, "direction": direction, "date": day,
            "start": min(m["start"] for m in members),
            "platform": members[0]["platform"],
            "scene_ids": sorted(m["id"] for m in members),
            "footprint": unary_union([m["footprint"] for m in members]),
        })
    return passes


def pick_sentinel1_pair(bbox, flood_date, settings=None):
    """Choose the before/after pair to compare, and explain the choice.

    Rule: among tracks that cover the area, take the one whose first pass
    after the flood is soonest (flood water drains within days), then the one
    whose last pass before the flood is most recent.
    """
    settings = settings or Settings()
    area = box(*bbox)
    scenes = search_sentinel1(
        bbox, flood_date - timedelta(days=settings.search_days_before),
        flood_date + timedelta(days=settings.search_days_after + 1))
    passes = _group_into_passes(scenes)

    def coverage(p):
        return p["footprint"].intersection(area).area / area.area

    tracks = defaultdict(list)
    for p in passes:
        tracks[(p["relative_orbit"], p["direction"])].append(p)

    candidates = []
    for (orbit, direction), track_passes in tracks.items():
        # A pass on the flood date itself could be from before or after the
        # event, so it is used on neither side.
        before = [p for p in track_passes if p["date"] < flood_date]
        after = [p for p in track_passes if p["date"] > flood_date]
        if not before or not after:
            continue
        before.sort(key=lambda p: p["start"])
        b, a = before[-1], min(after, key=lambda p: p["start"])
        # The pass before "before", if it covers the area too. Comparing it
        # with "before" shows how much the area changes without a flood.
        earlier = [p for p in before[:-1] if coverage(p) >= settings.min_coverage]
        candidates.append({
            "relative_orbit": orbit, "direction": direction,
            "before": b, "after": a, "baseline": earlier[-1] if earlier else None,
            "days_before": (flood_date - b["date"]).days,
            "days_after": (a["date"] - flood_date).days,
            "coverage": min(coverage(b), coverage(a)),
        })
    if not candidates:
        raise RuntimeError(
            "No Sentinel-1 track has both a before and an after pass for this "
            f"area within the search window around {flood_date}.")

    covering = [c for c in candidates if c["coverage"] >= settings.min_coverage]
    if covering:
        chosen = min(covering, key=lambda c: (c["days_after"], c["days_before"]))
        coverage_note = ""
    else:
        chosen = max(candidates, key=lambda c: c["coverage"])
        coverage_note = (f" No track covers {settings.min_coverage:.0%} of the area, "
                         "so the track with the best coverage was used.")

    reason = (
        f"Relative orbit {chosen['relative_orbit']} ({chosen['direction'].lower()}) "
        f"was chosen from {len(candidates)} usable track(s): its first pass after the "
        f"flood is {chosen['days_after']} day(s) later and its last pass before is "
        f"{chosen['days_before']} day(s) earlier. Both images are on the same track, "
        f"so they view the terrain from the same angle. The pair covers "
        f"{chosen['coverage']:.0%} of the requested area.{coverage_note}")

    def describe(p):
        return {"date": p["date"].isoformat(), "start_utc": p["start"].isoformat(),
                "platform": p["platform"], "scene_ids": p["scene_ids"]}

    return {
        "relative_orbit": chosen["relative_orbit"],
        "direction": chosen["direction"],
        "before": describe(chosen["before"]),
        "after": describe(chosen["after"]),
        "baseline": describe(chosen["baseline"]) if chosen["baseline"] else None,
        "days_before": chosen["days_before"],
        "days_after": chosen["days_after"],
        "coverage": round(chosen["coverage"], 3),
        "reason": reason,
        "other_tracks": [
            {"relative_orbit": c["relative_orbit"], "direction": c["direction"],
             "before": c["before"]["date"].isoformat(),
             "after": c["after"]["date"].isoformat(),
             "coverage": round(c["coverage"], 3)}
            for c in candidates if c is not chosen],
    }


def list_sentinel2_scenes(bbox, flood_date, settings=None):
    """List Sentinel-2 L2A scenes around the date with their cloud cover.

    The cloud figure is for the whole 100 km tile, not for the requested box,
    so it is only a first hint. Step 3 checks clouds over the area itself.
    """
    settings = settings or Settings()
    start = flood_date - timedelta(days=settings.search_days_before)
    end = flood_date + timedelta(days=settings.search_days_after + 1)
    filter_text = (
        "Collection/Name eq 'SENTINEL-2' and contains(Name,'MSIL2A') "
        f"and OData.CSC.Intersects(area=geography'SRID=4326;{_bbox_wkt(bbox)}') "
        f"and ContentDate/Start ge {start.isoformat()}T00:00:00.000Z "
        f"and ContentDate/Start lt {end.isoformat()}T00:00:00.000Z")
    scenes = []
    for product in _query_catalogue(filter_text):
        attrs = {a["Name"]: a["Value"] for a in product.get("Attributes", [])}
        when = _parse_time(product["ContentDate"]["Start"])
        scenes.append({
            "id": product["Name"], "date": when.date().isoformat(),
            "side": "before" if when.date() < flood_date else "after",
            "tile_cloud_cover_percent": attrs.get("cloudCover"),
        })
    return scenes
