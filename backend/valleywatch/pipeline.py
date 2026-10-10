"""Run Steps 1 and 2 end to end: area + flood date -> flood and debris map."""
import argparse
import json
from datetime import date
from pathlib import Path

import numpy as np
import rasterio
from rasterio.warp import Resampling, reproject

from . import s1_fetch
from .config import Settings
from .flood_mask import CLASS_DEBRIS, CLASS_WATER, detect_flood_and_debris
from .quicklook import save_quicklook
from .scene_picker import list_sentinel2_scenes, pick_sentinel1_pair
from .vectorize import masks_to_polygons

REPO_ROOT = Path(__file__).resolve().parents[2]


def _run_name(bbox, flood_date):
    """Folder name built only from the inputs, so repeated runs reuse the cache."""
    return f"{flood_date.isoformat()}_" + "_".join(f"{v:.3f}" for v in bbox)


def _read_onto_grid(path, grid):
    """Read a raster and resample it onto the reference grid.

    Separate downloads can differ by a pixel in size or origin. Putting all
    three rasters on one grid makes pixel-by-pixel comparison valid.
    """
    with rasterio.open(path) as src:
        bands = np.full((src.count, grid["height"], grid["width"]), np.nan, dtype=np.float32)
        for i in range(src.count):
            reproject(rasterio.band(src, i + 1), bands[i],
                      dst_transform=grid["transform"], dst_crs=grid["crs"],
                      dst_nodata=np.nan, resampling=Resampling.bilinear)
    return bands


def run_flood_mapping(bbox, flood_date, settings=None, data_dir=None, output_dir=None):
    """Map new water and debris for a bounding box (W, S, E, N) and flood date."""
    settings = settings or Settings()
    name = _run_name(bbox, flood_date)
    data_dir = Path(data_dir or REPO_ROOT / "data" / name)
    output_dir = Path(output_dir or REPO_ROOT / "outputs" / name)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: choose scenes.
    pair = pick_sentinel1_pair(bbox, flood_date, settings)
    print(pair["reason"])
    sentinel2 = list_sentinel2_scenes(bbox, flood_date, settings)

    # Step 2a: download backscatter for both dates and the DEM.
    conn = s1_fetch.connect()
    track = f"orbit{pair['relative_orbit']}"
    paths = {}
    for side in ("before", "after"):
        day = pair[side]["date"]
        print(f"Fetching {side} image ({day}) ...")
        paths[side] = s1_fetch.fetch_backscatter(
            conn, bbox, day, pair["direction"],
            data_dir / f"s1_{side}_{day}_{track}.tif", settings.resolution_m)
    print("Fetching Copernicus DEM ...")
    paths["dem"] = s1_fetch.fetch_dem(conn, bbox, data_dir / "dem.tif", settings.resolution_m)

    # Step 2b: put everything on the grid of the before image.
    with rasterio.open(paths["before"]) as src:
        grid = {"transform": src.transform, "crs": src.crs,
                "height": src.height, "width": src.width}
        bounds = src.bounds
    pixel_m = abs(grid["transform"].a)
    stacks = {side: _read_onto_grid(paths[side], grid) for side in ("before", "after")}
    dem = _read_onto_grid(paths["dem"], grid)[0]
    before = {"VV": stacks["before"][0], "VH": stacks["before"][1]}
    after = {"VV": stacks["after"][0], "VH": stacks["after"][1]}

    # Step 2c: classify.
    result = detect_flood_and_debris(before, after, dem, pixel_m,
                                     pair["direction"], settings)

    # Outputs.
    polygons = masks_to_polygons(result["classes"], result["confidence"],
                                 result["change_vv_db"], grid["transform"], grid["crs"])
    geojson_path = output_dir / "flood_debris.geojson"
    polygons.to_file(geojson_path, driver="GeoJSON")

    pixel_km2 = pixel_m ** 2 / 1e6
    mapped = result["has_data"]
    summary = {
        "inputs": {"bbox_west_south_east_north": list(bbox),
                   "flood_date": flood_date.isoformat()},
        "sentinel1": pair,
        "sentinel2_candidates": sentinel2,
        "grid": {"crs": str(grid["crs"]), "pixel_m": pixel_m,
                 "width": grid["width"], "height": grid["height"]},
        "thresholds": result["thresholds"],
        "totals": {
            "water_km2": round(float((result["classes"] == CLASS_WATER).sum()) * pixel_km2, 3),
            "debris_km2": round(float((result["classes"] == CLASS_DEBRIS).sum()) * pixel_km2, 3),
            "water_polygons": int((polygons["hazard"] == "water").sum()),
            "debris_polygons": int((polygons["hazard"] == "debris").sum()),
            # How much of the area the radar could not judge at all.
            "not_mapped_terrain_percent": round(
                100 * float((result["terrain"]["any"] & mapped).sum()) / max(int(mapped.sum()), 1), 1),
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

    print(json.dumps(summary["totals"], indent=2))
    print(f"Outputs written to {output_dir}")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bbox", nargs=4, type=float, required=True,
                        metavar=("WEST", "SOUTH", "EAST", "NORTH"))
    parser.add_argument("--date", required=True, help="Flood date, YYYY-MM-DD")
    args = parser.parse_args()
    run_flood_mapping(tuple(args.bbox), date.fromisoformat(args.date))


if __name__ == "__main__":
    main()
