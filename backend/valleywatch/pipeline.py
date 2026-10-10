"""Run Steps 1 to 3 end to end: area + flood date -> flood and debris map."""
import argparse
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import rasterio
from rasterio.warp import Resampling, reproject

from . import fetch
from .config import Settings
from .corridor import river_corridor
from .flood_mask import CLASS_DEBRIS, CLASS_WATER, detect_flood_and_debris
from .optical import fuse_with_optical, optical_evidence
from .quicklook import save_quicklook
from .scene_picker import list_sentinel2_scenes, pick_sentinel1_pair
from .terrain import terrain_mask
from .vectorize import masks_to_polygons

REPO_ROOT = Path(__file__).resolve().parents[2]


def _run_name(bbox, flood_date):
    """Folder name built only from the inputs, so repeated runs reuse the cache."""
    return f"{flood_date.isoformat()}_" + "_".join(f"{v:.3f}" for v in bbox)


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
    output_dir = Path(output_dir or REPO_ROOT / "outputs" / name)
    output_dir.mkdir(parents=True, exist_ok=True)

    # ---- Step 1: choose scenes -------------------------------------------
    report("Finding satellite scenes")
    pair = pick_sentinel1_pair(bbox, flood_date, settings)
    report(pair["reason"])
    sentinel2_scenes = list_sentinel2_scenes(bbox, flood_date, settings)

    # ---- Step 2a: download everything, several requests at a time ---------
    report("Downloading radar images, elevation and optical images")
    conn = fetch.connect()
    track = f"orbit{pair['relative_orbit']}"
    resolution = settings.resolution_m
    requests = []
    for side in ("before", "after", "baseline"):
        if pair[side] is None:
            continue
        day = pair[side]["date"]
        requests.append({
            "label": f"radar {side} ({day})",
            "cube": fetch.backscatter_cube(conn, bbox, day, pair["direction"], resolution),
            "path": data_dir / f"s1_{side}_{day}_{track}.tif",
            # The flood map needs before and after; the baseline is a bonus.
            "optional": side == "baseline", "key": side})
    requests.append({"label": "elevation", "cube": fetch.dem_cube(conn, bbox, resolution),
                     "path": data_dir / "dem.tif", "optional": False, "key": "dem"})
    optical_windows = {
        "before": (flood_date - timedelta(days=settings.search_days_before), flood_date),
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

    # ---- Step 2b: put everything on the grid of the before image ----------
    report("Aligning images")
    with rasterio.open(paths["before"]) as src:
        grid = {"transform": src.transform, "crs": src.crs,
                "height": src.height, "width": src.width}
        bounds = src.bounds
    pixel_m = abs(grid["transform"].a)

    def radar_image(key):
        stack = _read_onto_grid(paths[key], grid)
        return {"VV": stack[0], "VH": stack[1]}

    before, after = radar_image("before"), radar_image("after")
    baseline = radar_image("baseline") if available("baseline") else None
    dem = _read_onto_grid(paths["dem"], grid)[0]

    # ---- Step 2c: terrain masks and river corridor from the DEM -----------
    report("Finding the river corridor and radar blind zones")
    terrain = terrain_mask(dem, pixel_m, pair["direction"], settings)
    corridor = river_corridor(dem, grid["transform"], grid["crs"], settings)["corridor"]

    # ---- Step 2d: classify -------------------------------------------------
    report("Detecting flood and debris")
    result = detect_flood_and_debris(before, after, terrain, corridor, pixel_m,
                                     settings, baseline=baseline)
    radar_only = {
        "water_km2": float((result["classes"] == CLASS_WATER).sum()) * pixel_m ** 2 / 1e6,
        "debris_km2": float((result["classes"] == CLASS_DEBRIS).sum()) * pixel_m ** 2 / 1e6}

    # ---- Step 3: optical check where the sky was clear ---------------------
    if available("s2_before") and available("s2_after"):
        report("Checking against optical images")
        bands = fetch.S2_BANDS
        s2_before = dict(zip(bands, _read_onto_grid(paths["s2_before"], grid)))
        s2_after = dict(zip(bands, _read_onto_grid(paths["s2_after"], grid)))
        fuse_with_optical(result, optical_evidence(s2_before, s2_after, settings),
                          pixel_m, settings)
    else:
        report("No usable optical images; result is from radar only")
        result["source"] = (result["classes"] > 0).astype(np.uint8)
        result["optical"] = {"used": False, "reason": "No Sentinel-2 composite available: "
                             + "; ".join(str(paths[k]) for k in ("s2_before", "s2_after")
                                         if not available(k))}

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
                   "flood_date": flood_date.isoformat()},
        "sentinel1": pair,
        "sentinel2": {
            "windows": {side: [start.isoformat(), end.isoformat()]
                        for side, (start, end) in optical_windows.items()},
            "check": result["optical"],
            "scenes_in_catalogue": sentinel2_scenes},
        "grid": {"crs": str(grid["crs"]), "pixel_m": pixel_m,
                 "width": grid["width"], "height": grid["height"]},
        "thresholds": result["thresholds"],
        "baseline": result["baseline"],
        "totals": {
            "water_km2": round(float((result["classes"] == CLASS_WATER).sum()) * pixel_km2, 3),
            "debris_km2": round(float((result["classes"] == CLASS_DEBRIS).sum()) * pixel_km2, 3),
            "radar_only_water_km2": round(radar_only["water_km2"], 3),
            "radar_only_debris_km2": round(radar_only["debris_km2"], 3),
            "water_polygons": int((polygons["hazard"] == "water").sum()),
            "debris_polygons": int((polygons["hazard"] == "debris").sum()),
            "polygons_by_confidence": polygons["confidence_level"].value_counts().to_dict(),
            "polygons_by_source": polygons["source"].value_counts().to_dict(),
            "corridor_km2": round(float((corridor & mapped).sum()) * pixel_km2, 2),
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

    title = (f"Flood date {flood_date}  |  Sentinel-1 relative orbit "
             f"{pair['relative_orbit']} {pair['direction'].lower()}  |  "
             f"before {pair['before']['date']}  after {pair['after']['date']}")
    extent = (bounds.left, bounds.right, bounds.bottom, bounds.top)
    save_quicklook(result, extent, output_dir / "quicklook.png", title)

    report(f"Finished. Outputs written to {output_dir}")
    print(json.dumps({k: summary[k] for k in ("totals", "baseline")}, indent=2))
    print(json.dumps(summary["sentinel2"]["check"], indent=2))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bbox", nargs=4, type=float, required=True,
                        metavar=("WEST", "SOUTH", "EAST", "NORTH"))
    parser.add_argument("--date", required=True, help="Flood date, YYYY-MM-DD")
    parser.add_argument("--large", action="store_true",
                        help="Allow a box above the live-run size (slow batch jobs)")
    args = parser.parse_args()
    settings = Settings()
    area = fetch.bbox_area_km2(args.bbox)
    if area > settings.max_live_area_km2 and not args.large:
        sys.exit(f"The box covers {area:.0f} km2. Live runs are limited to "
                 f"{settings.max_live_area_km2:.0f} km2 so they finish in minutes. "
                 "Choose a smaller box, or add --large to run slow batch jobs.")
    run_flood_mapping(tuple(args.bbox), date.fromisoformat(args.date), settings)


if __name__ == "__main__":
    main()
