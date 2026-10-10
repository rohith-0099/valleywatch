"""Compare a ValleyWatch run with the Copernicus EMS reference maps.

Usage (from the backend folder):

    python -m validation.emsr927 --run ../outputs/<run folder> --activation EMSR927

Measure only: this script reads the finished outputs of a run and the
reference products, and writes scores. It feeds nothing back.

Attribution: European Union, Copernicus Emergency Management Service data.
"""
import argparse
import io
import json
import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests
from shapely.geometry import box

API = "https://rapidmapping.emergency.copernicus.eu/backend/dashboard-api/public-activations/"
ATTRIBUTION = "European Union, Copernicus Emergency Management Service data"
# Reference damage grades counted as "damaged". "Possibly damaged" is scored
# separately because the analysts themselves were unsure.
DAMAGED = ("Destroyed", "Damaged")
POSSIBLY = ("Possibly damaged",)
# How close two maps must be to count as the same building, road or bridge.
# Positions differ between OpenStreetMap and the reference by a pixel or two.
BUILDING_MATCH_M, ROAD_MATCH_M, BRIDGE_MATCH_M = 15.0, 15.0, 30.0


def download_reference(activation, folder):
    """Fetch every finished product of an activation. Returns product folders."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    meta_path = folder / "activation.json"
    if not meta_path.exists():
        response = requests.get(API, params={"code": activation}, timeout=120)
        response.raise_for_status()
        meta_path.write_text(response.text)
    products = []
    for aoi in json.loads(meta_path.read_text())["results"][0]["aois"]:
        for product in aoi.get("products", []):
            url = product.get("downloadPath")
            if not url:  # cancelled products (for example persistent cloud)
                continue
            target = folder / Path(url).stem
            if not target.exists():
                data = requests.get(url, timeout=600)
                data.raise_for_status()
                zipfile.ZipFile(io.BytesIO(data.content)).extractall(target)
            images = [f"{i.get('sensorName')} {str(i.get('acquisitionTime'))[:10]}"
                      for i in product.get("images", []) if i.get("sensorName")]
            products.append({"folder": target, "aoi": aoi.get("name"),
                             "aoi_number": aoi.get("number"), "product": Path(url).stem,
                             "reference_images": images})
    return products


def _layer(folder, name, crs):
    """Read one reference layer (empty table when the product lacks it)."""
    files = sorted(Path(folder).glob(f"*_{name}_*.json"))
    if not files:
        return gpd.GeoDataFrame({"damage_gra": []}, geometry=[], crs=crs)
    return gpd.read_file(files[0]).to_crs(crs)


def _read_run_layer(run, name, crs):
    path = Path(run) / f"{name}.geojson"
    if not path.exists() or not json.loads(path.read_text())["features"]:
        return gpd.GeoDataFrame({"hit": []}, geometry=[], crs=crs)
    return gpd.read_file(path).to_crs(crs)


def _rate(part, whole):
    return round(part / whole, 3) if whole else None


def extent_scores(ours, reference, area):
    """Overlap of our flood/debris area with the reference event area, inside `area`."""
    ours_area = ours.union_all().intersection(area) if len(ours) else area.buffer(-1e9)
    ref_area = reference.union_all().intersection(area) if len(reference) else area.buffer(-1e9)
    overlap = ours_area.intersection(ref_area).area
    return {
        "reference_km2": round(ref_area.area / 1e6, 3),
        "ours_km2": round(ours_area.area / 1e6, 3),
        "overlap_km2": round(overlap / 1e6, 3),
        # Of what we mapped, how much the reference also maps.
        "precision": _rate(overlap, ours_area.area),
        # Of what the reference maps, how much we found.
        "recall": _rate(overlap, ref_area.area),
        "iou": _rate(overlap, ours_area.union(ref_area).area),
    }


def point_scores(ours, reference, match_m):
    """Match two sets of features by distance.

    recall: share of reference features with one of ours within `match_m`.
    precision: share of ours with a reference feature within `match_m`.
    """
    found = (int((reference.distance(ours.union_all()) <= match_m).sum())
             if len(ours) and len(reference) else 0)
    confirmed = (int((ours.distance(reference.union_all()) <= match_m).sum())
                 if len(ours) and len(reference) else 0)
    return {"reference": int(len(reference)), "ours": int(len(ours)),
            "reference_found": found, "ours_confirmed": confirmed,
            "recall": _rate(found, len(reference)), "precision": _rate(confirmed, len(ours))}


def road_scores(ours, reference, match_m):
    """Same idea for roads, measured in kilometres of line."""
    ref_km = float(reference.length.sum()) / 1000
    ours_km = float(ours.length.sum()) / 1000
    found = (float(reference.intersection(ours.buffer(match_m).union_all()).length.sum()) / 1000
             if len(ours) and len(reference) else 0.0)
    confirmed = (float(ours.intersection(reference.buffer(match_m).union_all()).length.sum()) / 1000
                 if len(ours) and len(reference) else 0.0)
    return {"reference_km": round(ref_km, 2), "ours_km": round(ours_km, 2),
            "reference_found_km": round(found, 2), "ours_confirmed_km": round(confirmed, 2),
            "recall": _rate(found, ref_km), "precision": _rate(confirmed, ours_km)}


def validate(run, activation, reference_folder):
    run = Path(run)
    summary = json.loads((run / "summary.json").read_text())
    crs = summary["grid"]["crs"]
    run_box = gpd.GeoSeries([box(*summary["inputs"]["bbox_west_south_east_north"])],
                            crs=4326).to_crs(crs).iloc[0]

    hazards = _read_run_layer(run, "flood_debris", crs)
    buildings = _read_run_layer(run, "buildings_hit", crs)
    road_hits = _read_run_layer(run, "road_hits", crs)
    bridges = _read_run_layer(run, "bridges", crs)
    hit_bridges = bridges[bridges["hit"].astype(bool)] if len(bridges) else bridges

    rows = []
    for product in download_reference(activation, reference_folder):
        folder = product["folder"]
        aoi = _layer(folder, "areaOfInterestA", crs)
        if aoi.empty:
            continue
        aoi_polygon = aoi.union_all()
        area = aoi_polygon.intersection(run_box)
        coverage = area.area / aoi_polygon.area
        row = {"aoi": product["aoi"], "product": product["product"],
               "reference_images": product["reference_images"],
               "share_of_aoi_inside_run_box": round(coverage, 3)}
        if coverage < 0.5:
            row["skipped"] = "less than half of this area lies inside the run box"
            rows.append(row)
            continue

        def inside(frame):
            return frame[frame.intersects(area)] if len(frame) else frame

        event = _layer(folder, "observedEventA", crs)
        row["reference_event_types"] = (event["event_type"].value_counts().to_dict()
                                        if "event_type" in event.columns else {})
        row["extent"] = extent_scores(hazards, event, area)
        strong = hazards[hazards["confidence_level"].isin(["high", "medium"])] if len(hazards) else hazards
        row["extent_high_and_medium_confidence_only"] = extent_scores(strong, event, area)

        ref_buildings = inside(_layer(folder, "builtUpP", crs))
        ours_buildings = inside(buildings)
        if len(ours_buildings):
            ours_buildings = ours_buildings.assign(geometry=ours_buildings.geometry.centroid)
        # Older runs have no "status" column: every listed building is a hit.
        is_hit = (ours_buildings["status"] == "hit" if "status" in ours_buildings.columns
                  else pd.Series(True, index=ours_buildings.index))
        ref_damaged = ref_buildings[ref_buildings["damage_gra"].isin(DAMAGED)]
        row["reference_building_grades"] = ref_buildings["damage_gra"].value_counts().to_dict()
        row["buildings_vs_destroyed_or_damaged"] = point_scores(
            ours_buildings[is_hit], ref_damaged, BUILDING_MATCH_M)
        row["buildings_incl_possibly_affected_vs_destroyed_or_damaged"] = point_scores(
            ours_buildings, ref_damaged, BUILDING_MATCH_M)
        row["buildings_vs_any_grade_incl_possibly"] = point_scores(
            ours_buildings[is_hit],
            ref_buildings[ref_buildings["damage_gra"].isin(DAMAGED + POSSIBLY)], BUILDING_MATCH_M)

        ref_roads = inside(_layer(folder, "transportationL", crs))
        row["reference_road_grades_km"] = (
            (ref_roads.length.groupby(ref_roads["damage_gra"]).sum() / 1000).round(2).to_dict())
        row["roads_vs_destroyed_or_damaged"] = road_scores(
            inside(road_hits), ref_roads[ref_roads["damage_gra"].isin(DAMAGED)], ROAD_MATCH_M)

        ref_points = inside(_layer(folder, "transportationP", crs))
        ref_bridges = ref_points[ref_points["obj_type"].astype(str).str.contains("Bridge", na=False)] \
            if "obj_type" in ref_points.columns else ref_points
        row["bridges_vs_destroyed_or_damaged"] = point_scores(
            inside(hit_bridges), ref_bridges[ref_bridges["damage_gra"].isin(DAMAGED)], BRIDGE_MATCH_M)
        rows.append(row)

    report = {"activation": activation, "run": run.name, "attribution": ATTRIBUTION,
              "note": "Measured once on finished outputs. No setting was tuned to these scores.",
              "match_distances_m": {"buildings": BUILDING_MATCH_M, "roads": ROAD_MATCH_M,
                                    "bridges": BRIDGE_MATCH_M},
              "areas": rows}
    out = run / f"validation_{activation}.json"
    out.write_text(json.dumps(report, indent=2))
    return report


def print_table(report):
    lines = []
    for row in report["areas"]:
        if "skipped" in row:
            lines.append({"area / product": f"{row['aoi']} / {row['product'][-16:]}",
                          "note": row["skipped"]})
            continue
        e, b, r, g = (row["extent"], row["buildings_vs_destroyed_or_damaged"],
                      row["roads_vs_destroyed_or_damaged"], row["bridges_vs_destroyed_or_damaged"])
        lines.append({
            "area / product": f"{row['aoi']} / {row['product'][-16:]}",
            "ref km2": e["reference_km2"], "ours km2": e["ours_km2"],
            "IoU": e["iou"], "precision": e["precision"], "recall": e["recall"],
            "bldg recall": f"{b['reference_found']}/{b['reference']}",
            "bldg precision": f"{b['ours_confirmed']}/{b['ours']}",
            "bldg recall +possibly": "{reference_found}/{reference}".format(
                **row["buildings_incl_possibly_affected_vs_destroyed_or_damaged"]),
            "road recall km": f"{r['reference_found_km']}/{r['reference_km']}",
            "bridge recall": f"{g['reference_found']}/{g['reference']}",
            "bridge precision": f"{g['ours_confirmed']}/{g['ours']}"})
    pd.set_option("display.width", 250)
    print(pd.DataFrame(lines).to_string(index=False))
    print(report["attribution"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, help="Folder of a finished pipeline run")
    parser.add_argument("--activation", default="EMSR927")
    parser.add_argument("--reference", default=None, help="Where to keep reference downloads")
    args = parser.parse_args()
    reference = args.reference or Path(args.run).resolve().parents[1] / "data" / args.activation.lower()
    print_table(validate(args.run, args.activation, reference))


if __name__ == "__main__":
    main()
