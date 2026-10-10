"""Pre-event OpenStreetMap data from the ohsome API.

The rules allow OpenStreetMap only as it was BEFORE the event, because
mappers edit the map after a disaster (often tracing the damage itself).
ohsome serves the map as it stood at any past moment, so we ask for a
snapshot dated before the flood and never touch the live map.
"""
import json
from datetime import date, datetime, timedelta
from pathlib import Path

import geopandas as gpd
import requests

OHSOME_URL = "https://api.ohsome.org/v1"
USER_AGENT = {"User-Agent": "ValleyWatch (educational hackathon prototype)"}

# What we ask for. Filters use the ohsome filter language.
LAYER_FILTERS = {
    "buildings": "building=* and geometry:polygon",
    "roads": "highway=* and type:way and geometry:line",
    "places": "place in (city, town, village, hamlet, isolated_dwelling) and type:node",
    "health": "amenity in (hospital, clinic, doctors) or healthcare=*",
}


def snapshot_date(flood_date):
    """Latest map date we may use: the day before the flood, or the newest
    data ohsome holds if that is older."""
    response = requests.get(f"{OHSOME_URL}/metadata", headers=USER_AGENT, timeout=60)
    response.raise_for_status()
    newest_text = response.json()["extractRegion"]["temporalExtent"]["toTimestamp"]
    newest = datetime.fromisoformat(newest_text.replace("Z", "+00:00")).date()
    return min(flood_date - timedelta(days=1), newest)


def _request_features(bbox, snapshot, filter_text):
    """Features that existed at 00:00 UTC on the snapshot date."""
    box = ",".join(str(v) for v in bbox)
    query = {"bboxes": box, "time": snapshot.isoformat(), "filter": filter_text,
             "properties": "tags"}
    response = requests.post(f"{OHSOME_URL}/elements/geometry", data=query,
                             headers=USER_AGENT, timeout=300)
    if response.status_code == 403:
        # The snapshot endpoint is sometimes closed on the public server. The
        # history endpoint of the same API returns every version of each
        # feature with the period it was valid; the versions still valid at
        # the end of a one-day window ARE the snapshot.
        day_before = snapshot - timedelta(days=1)
        query["time"] = f"{day_before.isoformat()},{snapshot.isoformat()}"
        response = requests.post(f"{OHSOME_URL}/elementsFullHistory/geometry", data=query,
                                 headers=USER_AGENT, timeout=300)
        response.raise_for_status()
        window_end = f"{snapshot.isoformat()}T00:00:00Z"
        return [f for f in response.json()["features"]
                if f["properties"].get("@validTo") == window_end]
    response.raise_for_status()
    return response.json()["features"]


def fetch_osm_layers(bbox, flood_date, cache_dir, progress=print):
    """Download (or load from cache) all pre-event layers for the box.

    Returns (layers, snapshot) where layers maps a layer name to a
    GeoDataFrame in WGS84.
    """
    snapshot = snapshot_date(flood_date)
    if snapshot >= flood_date:
        raise RuntimeError("OpenStreetMap snapshot must be dated before the flood.")
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    layers = {}
    for name, filter_text in LAYER_FILTERS.items():
        path = cache_dir / f"osm_{name}_{snapshot.isoformat()}.geojson"
        if not path.exists():
            progress(f"OpenStreetMap {name}: requesting snapshot of {snapshot}")
            features = _request_features(bbox, snapshot, filter_text)
            for feature in features:
                # Keep the OSM id under a plain name; drop ohsome bookkeeping.
                props = feature["properties"]
                props["osm_id"] = props.pop("@osmId", None)
                for key in [k for k in props if k.startswith("@")]:
                    del props[key]
            path.write_text(json.dumps({"type": "FeatureCollection", "features": features}))
        if json.loads(path.read_text())["features"]:
            layers[name] = gpd.read_file(path)
        else:
            layers[name] = gpd.GeoDataFrame({"osm_id": []}, geometry=[], crs=4326)
        progress(f"OpenStreetMap {name}: {len(layers[name])} features")
    return layers, snapshot
