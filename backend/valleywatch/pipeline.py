"""Run the analysis end to end: area + flood date -> flood map and damage list."""
import argparse
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.warp import Resampling, reproject

from . import fetch
from .config import Settings
from .corridor import river_corridor
from .cutoff import analyse_cutoff
from .damage import assess_damage
from .flood_mask import CLASS_DEBRIS, CLASS_WATER, detect_flood_and_debris, merge_tracks
from .optical import optical_evidence
from .osm import fetch_osm_layers, fetch_routing_layers
from .quicklook import save_quicklook
from .refine import acceptance_test, fused_map, score_confidence
from .scene_picker import list_sentinel2_scenes, pick_sentinel1_pair
from .terrain import terrain_mask
from .vectorize import masks_to_polygons

REPO_ROOT = Path(__file__).resolve().parents[2]


def _run_name(bbox, flood_date):
    """Folder name built only from the inputs, so repeated runs reuse the cache."""
    return f"{flood_date.isoformat()}_" + "_".join(f"{v:.3f}" for v in bbox)


def output_name(bbox, flood_date, settings):
    """Results folder. Thorough runs get their own, so both can be compared."""
    return _run_name(bbox, flood_date) + ("_thorough" if settings.use_second_track else "")


def _read_onto_grid(path, grid):
    """Read a raster and resample it onto the reference grid.

    Separate downloads can differ by a pixel in size or origin. Putting all
    rasters on one grid makes pixel-by-pixel comparison valid.
    """
    with rasterio.open(path) as src:
        bands = np.full((src.count, grid["height"], grid["width"]), np.nan, dtype=np.float32)
        for i in range(src.count):
            reproject(rasterio.band(src, i + 1), bands[i],
                      dst_transform=grid["transform"], dst_crs=grid["crs"],
                      dst_nodata=np.nan, resampling=Resampling.bilinear)
    return bands


def _timed_progress(progress):
    """Wrap a progress callback so every message carries the elapsed time."""
    started = time.time()

    def report(message):
        elapsed = int(time.time() - started)
        progress(f"[{elapsed // 60:02d}:{elapsed % 60:02d}] {message}")
    return report


def run_flood_mapping(bbox, flood_date, settings=None, data_dir=None, output_dir=None,
                      progress=print):
    """Map new water and debris for a bounding box (W, S, E, N) and flood date.

    `progress` receives one short text message per step; the dashboard uses
    it to show what the pipeline is doing.
    """
    settings = settings or Settings()
    report = _timed_progress(progress)
    name = _run_name(bbox, flood_date)
    data_dir = Path(data_dir or REPO_ROOT / "data" / name)
    output_dir = Path(output_dir or REPO_ROOT / "outputs" / output_name(bbox, flood_date, settings))
    output_dir.mkdir(parents=True, exist_ok=True)

    # ---- Step 1: choose scenes -------------------------------------------
    report("Finding satellite scenes")
    pair = pick_sentinel1_pair(bbox, flood_date, settings)
    report(pair["reason"])
    sentinel2_scenes = list_sentinel2_scenes(bbox, flood_date, settings)

    # ---- Step 2a: download everything, several requests at a time ---------
    report("Downloading radar images, elevation and optical images")
    conn = fetch.connect()
    resolution = settings.resolution_m
    tracks = [pair]
    if settings.use_second_track and pair["second_track"]:
        tracks.append(pair["second_track"])
        second = pair["second_track"]
        report(f"Second radar track: orbit {second['relative_orbit']} "
               f"({second['direction'].lower()}), {second['before']['date']} to "
               f"{second['after']['date']}, looking from the opposite side")
    requests = []
    for number, track in enumerate(tracks):
        for side in ("before", "after", "baseline"):
            if track[side] is None:
                continue
            day, orbit = track[side]["date"], track["relative_orbit"]
            requests.append({
                "label": f"radar orbit {orbit} {side} ({day})",
                "cube": fetch.backscatter_cube(conn, bbox, day, track["direction"], resolution),
                "path": data_dir / f"s1_{side}_{day}_orbit{orbit}.tif",
                # Only the primary before/after pair is essential.
                "optional": number > 0 or side == "baseline",
                "key": (number, side)})
    requests.append({"label": "elevation", "cube": fetch.dem_cube(conn, bbox, resolution),
                     "path": data_dir / "dem.tif", "optional": False, "key": "dem"})
    window = timedelta(days=settings.search_days_before)
    optical_windows = {
        # An earlier window, compared with "before", is the optical no-flood test.
        "earlier": (flood_date - 2 * window, flood_date - window),
        "before": (flood_date - window, flood_date),
        "after": (flood_date + timedelta(days=1),
                  flood_date + timedelta(days=settings.search_days_after + 1))}
    for side, (start, end) in optical_windows.items():
        requests.append({
            "label": f"optical {side} ({start} to {end})",
            "cube": fetch.sentinel2_clear_composite_cube(conn, bbox, start, end, resolution),
            "path": data_dir / f"s2_{side}_{start}_{end}.tif",
            "optional": True, "key": f"s2_{side}"})
    downloaded = fetch.download_all(requests, bbox, settings, report)
    paths = {r["key"]: downloaded[r["label"]] for r in requests}

    def available(key):
        return isinstance(paths.get(key), Path)

    # ---- Step 2b: put everything on the grid of the primary before image ---
    report("Aligning images")
    with rasterio.open(paths[0, "before"]) as src:
        grid = {"transform": src.transform, "crs": src.crs,
                "height": src.height, "width": src.width}
        bounds = src.bounds
    pixel_m = abs(grid["transform"].a)

    def radar_image(key):
        stack = _read_onto_grid(paths[key], grid)
        return {"VV": stack[0], "VH": stack[1]}

    dem = _read_onto_grid(paths["dem"], grid)[0]

    # ---- Step 2c: river zones from the DEM ---------------------------------
    report("Finding the river corridor")
    zones = river_corridor(dem, grid["transform"], grid["crs"], settings)
    corridor = zones["corridor"]

    # ---- Step 2d: radar detection, once per track ---------------------------
    radar_runs, tracks_used = [], []
    for number, track in enumerate(tracks):
        if not (available((number, "before")) and available((number, "after"))):
            report(f"Radar orbit {track['relative_orbit']}: images not available, skipped")
            continue
        report(f"Detecting flood and debris, radar orbit {track['relative_orbit']}")
        # Layover and shadow depend on the look direction, so each track
        # gets its own terrain mask.
        terrain = terrain_mask(dem, pixel_m, track["direction"], settings)
        baseline = radar_image((number, "baseline")) if available((number, "baseline")) else None
        radar_runs.append(detect_flood_and_debris(
            radar_image((number, "before")), radar_image((number, "after")), terrain,
            corridor, zones["reach"], pixel_m, settings, baseline=baseline))
        tracks_used.append(track["relative_orbit"])
    result = merge_tracks(radar_runs)
    result["corridor"] = corridor

    # ---- Step 3: optical evidence where the sky was clear -------------------
    bands = fetch.S2_BANDS
    evidence = quiet_evidence = None
    if available("s2_before") and available("s2_after"):
        report("Checking against optical images")
        s2_before = dict(zip(bands, _read_onto_grid(paths["s2_before"], grid)))
        s2_after = dict(zip(bands, _read_onto_grid(paths["s2_after"], grid)))
        evidence = optical_evidence(s2_before, s2_after, settings)
        if available("s2_earlier"):
            s2_earlier = dict(zip(bands, _read_onto_grid(paths["s2_earlier"], grid)))
            quiet_evidence = optical_evidence(s2_earlier, s2_before, settings)
        reach_pixels = max(int((zones["reach"] & result["has_data"]).sum()), 1)
        result["optical"] = {"used": True, "reach_zone_clear_percent": round(
            100 * float((evidence["clear"] & zones["reach"]).sum()) / reach_pixels, 1)}
    else:
        report("No usable optical images; result is from radar only")
        result["optical"] = {"used": False, "reason": "No Sentinel-2 composite available: "
                             + "; ".join(str(paths[k]) for k in ("s2_before", "s2_after")
                                         if not available(k))}

    # ---- Final map: combine sources, grow from the valley floor, keep the
    # ---- connected flood path, score confidence ------------------------------
    report("Building the final map")
    fused = fused_map(result["water"], result["debris"], result["water_core"], evidence,
                      zones, pixel_m, settings)
    result.update(fused)
    result["confidence"] = score_confidence(result["classes"], result["source"],
                                            result["checked"], result["already_changing"],
                                            result["water_second_track_only"], settings)

    # ---- Acceptance test: the same rules on images from before the flood ----
    report("Running the no-flood acceptance test")
    acceptance = acceptance_test(result, evidence, quiet_evidence, zones, pixel_m, settings)
    acceptance["no_flood_radar_dates"] = [
        [t["baseline"]["date"], t["before"]["date"]] for t in tracks if t["baseline"]]
    acceptance["no_flood_optical_windows"] = [
        [d.isoformat() for d in optical_windows[k]] for k in ("earlier", "before")]

    # ---- Outputs -------------------------------------------------------------
    report("Writing outputs")
    polygons = masks_to_polygons(result["classes"], result["confidence"],
                                 result["change_vv_db"], result["source"],
                                 grid["transform"], grid["crs"])
    polygons.to_file(output_dir / "flood_debris.geojson", driver="GeoJSON")

    pixel_km2 = pixel_m ** 2 / 1e6
    mapped = result["has_data"]
    summary = {
        "inputs": {"bbox_west_south_east_north": list(bbox),
                   "flood_date": flood_date.isoformat(),
                   "mode": "thorough" if settings.use_second_track else "quick"},
        "sentinel1": pair,
        "sentinel2": {
            "windows": {side: [start.isoformat(), end.isoformat()]
                        for side, (start, end) in optical_windows.items()},
            "check": result["optical"],
            "scenes_in_catalogue": sentinel2_scenes},
        "grid": {"crs": str(grid["crs"]), "pixel_m": pixel_m,
                 "width": grid["width"], "height": grid["height"]},
        "thresholds": result["thresholds"],
        "radar_orbits_used": tracks_used,
        "river_min_catchment_km2": zones["river_min_catchment_km2"],
        "acceptance_test": acceptance,
        "totals": {
            "water_km2": round(float((result["classes"] == CLASS_WATER).sum()) * pixel_km2, 3),
            "debris_km2": round(float((result["classes"] == CLASS_DEBRIS).sum()) * pixel_km2, 3),
            "area_km2_by_source": {
                label: round(float((result["source"] == code).sum()) * pixel_km2, 3)
                for label, code in (("radar only", 1), ("radar and optical", 2),
                                    ("optical only", 3), ("radar, optical disagrees", 4))},
            "water_polygons": int((polygons["hazard"] == "water").sum()),
            "debris_polygons": int((polygons["hazard"] == "debris").sum()),
            "polygons_by_confidence": polygons["confidence_level"].value_counts().to_dict(),
            "polygons_by_source": polygons["source"].value_counts().to_dict(),
            "corridor_km2": round(float((corridor & mapped).sum()) * pixel_km2, 2),
            "reach_zone_km2": round(float((zones["reach"] & mapped).sum()) * pixel_km2, 2),
            # Share of the corridor where radar could not judge at all.
            "corridor_not_mapped_by_radar_percent": round(
                100 * float((result["not_mapped"] & corridor).sum())
                / max(int((corridor & mapped).sum()), 1), 1),
            "not_mapped_terrain_percent": round(
                100 * float(result["not_mapped"].sum()) / max(int(mapped.sum()), 1), 1),
            "permanent_water_km2": round(float(result["permanent_water"].sum()) * pixel_km2, 3),
        },
        "settings": settings.__dict__,
        "attribution": [
            f"Contains modified Copernicus Sentinel data {flood_date.year}.",
            "Produced using Copernicus WorldDEM-30 © DLR e.V. 2010–2014 and © Airbus "
            "Defence and Space GmbH 2014–2018 provided under COPERNICUS by the "
            "European Union and ESA; all rights reserved.",
        ],
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2))

    # Class raster, kept for later steps and for validation.
    profile = {"driver": "GTiff", "height": grid["height"], "width": grid["width"],
               "count": 1, "dtype": "uint8", "crs": grid["crs"],
               "transform": grid["transform"], "compress": "deflate", "nodata": 255}
    with rasterio.open(output_dir / "classes.tif", "w", **profile) as dst:
        dst.write(np.where(mapped, result["classes"], 255).astype(np.uint8), 1)

    result["terrain"] = None
    title = (f"Flood date {flood_date}  |  Sentinel-1 relative orbit "
             f"{pair['relative_orbit']} {pair['direction'].lower()}  |  "
             f"before {pair['before']['date']}  after {pair['after']['date']}")
    extent = (bounds.left, bounds.right, bounds.bottom, bounds.top)
    save_quicklook(result, extent, output_dir / "quicklook.png", title)

    report(f"Finished. Outputs written to {output_dir}")
    print(json.dumps({k: summary[k] for k in ("totals", "acceptance_test")}, indent=2))
    return summary


def run_damage_and_cutoff(bbox, flood_date, settings=None, data_dir=None, output_dir=None,
                       progress=print):
    """Steps 4 and 5: damage overlay and cut-off settlements for this run."""
    settings = settings or Settings()
    name = _run_name(bbox, flood_date)
    data_dir = Path(data_dir or REPO_ROOT / "data" / name)
    output_dir = Path(output_dir or REPO_ROOT / "outputs" / output_name(bbox, flood_date, settings))

    progress("Checking roads and buildings")
    output_dir.mkdir(parents=True, exist_ok=True)
    layers, snapshot = fetch_osm_layers(bbox, flood_date, data_dir, progress)
    hazards = gpd.read_file(output_dir / "flood_debris.geojson")
    damage = assess_damage(hazards, layers, fetch.utm_epsg_for(bbox), settings)
    for layer in ("buildings_hit", "road_hits", "bridges"):
        path = output_dir / f"{layer}.geojson"
        if len(damage[layer]):
            damage[layer].to_file(path, driver="GeoJSON")
        else:
            path.write_text(json.dumps({"type": "FeatureCollection", "features": []}))

    # Add the damage figures to the run summary written by the flood step.
    summary_path = output_dir / "summary.json"
    summary = json.loads(summary_path.read_text())
    summary["openstreetmap"] = {"snapshot_date": snapshot.isoformat(),
                                "features": {k: int(len(v)) for k, v in layers.items()}}
    summary["damage"] = damage["totals"]
    if "© OpenStreetMap contributors." not in summary["attribution"]:
        summary["attribution"].append("© OpenStreetMap contributors.")

    # ---- Step 5: cut-off settlements ----------------------------------------
    progress("Finding cut-off settlements")
    routing_layers = fetch_routing_layers(bbox, flood_date, data_dir,
                                          settings.routing_buffer_km, progress)
    cutoff = analyse_cutoff(layers, routing_layers, damage["road_hits"], damage["bridges"],
                            bbox, fetch.utm_epsg_for(bbox), settings)
    for layer in ("settlements", "broken_links", "lost_routes"):
        path = output_dir / f"{layer}.geojson"
        if len(cutoff[layer]):
            cutoff[layer].to_file(path, driver="GeoJSON")
        else:  # GeoJSON writers reject an empty table, so write the empty file by hand
            path.write_text(json.dumps({"type": "FeatureCollection", "features": []}))
    summary["cutoff"] = cutoff["totals"]
    summary_path.write_text(json.dumps(summary, indent=2))
    print(json.dumps({"damage": damage["totals"], "cutoff": cutoff["totals"]}, indent=2))
    return summary


def run_analysis(bbox, flood_date, settings=None, progress=print):
    """Everything built so far, in order."""
    run_flood_mapping(bbox, flood_date, settings, progress=progress)
    return run_damage_and_cutoff(bbox, flood_date, settings, progress=progress)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bbox", nargs=4, type=float, required=True,
                        metavar=("WEST", "SOUTH", "EAST", "NORTH"))
    parser.add_argument("--date", required=True, help="Flood date, YYYY-MM-DD")
    parser.add_argument("--large", action="store_true",
                        help="Allow a box above the live-run size (slow batch jobs)")
    parser.add_argument("--thorough", action="store_true",
                        help="Also use a second radar track from the opposite side (slower)")
    args = parser.parse_args()
    settings = Settings()
    settings.use_second_track = args.thorough
    area = fetch.bbox_area_km2(args.bbox)
    if area > settings.max_live_area_km2 and not args.large:
        sys.exit(f"The box covers {area:.0f} km2. Live runs are limited to "
                 f"{settings.max_live_area_km2:.0f} km2 so they finish in minutes. "
                 "Choose a smaller box, or add --large to run slow batch jobs.")
    run_analysis(tuple(args.bbox), date.fromisoformat(args.date), settings)


if __name__ == "__main__":
    main()
