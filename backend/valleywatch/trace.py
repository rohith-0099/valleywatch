"""Step 8 (bonus): trace a flood's path down the valley from any point.

Water runs downhill. Starting at the chosen point we step from DEM cell to
DEM cell, always to the neighbour the terrain drains into (the same flow
directions used to find the river corridor), until the edge of the area.
Settlements near that line are listed in the order the flood would reach
them. Only the Copernicus DEM and pre-event OpenStreetMap are used.
"""
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from shapely.geometry import LineString, Point

from .config import Settings
from .corridor import FLOW_STEPS, river_corridor

NEAR_PATH_M = 500.0  # a settlement this close to the path is "along" it


def trace_flood_path(dem_path, settlements_path, longitude, latitude, settings=None):
    """Follow the terrain downhill from a point.

    Returns {'path': GeoJSON LineString in WGS84, 'length_km',
    'drop_m' (height lost along the path), 'settlements': [...]} with the
    settlements ordered from upstream to downstream.
    """
    settings = settings or Settings()
    with rasterio.open(dem_path) as src:
        dem, transform, crs = src.read(1).astype("float32"), src.transform, src.crs
    routing = river_corridor(dem, transform, crs, settings)["coarse"]
    flow, coarse_transform = routing["flow_direction"], routing["transform"]
    rows, cols = flow.shape

    start = gpd.GeoSeries([Point(longitude, latitude)], crs=4326).to_crs(crs).iloc[0]
    col, row = (int(v) for v in ~coarse_transform * (start.x, start.y))
    if not (0 <= row < rows and 0 <= col < cols):
        raise ValueError("The point is outside the analysed area.")

    # Walk downhill. `seen` stops the walk if flow directions ever loop.
    cells, seen = [], set()
    while 0 <= row < rows and 0 <= col < cols and (row, col) not in seen:
        seen.add((row, col))
        cells.append((row, col))
        step = FLOW_STEPS.get(int(flow[row, col]))
        if step is None:  # edge of the data or a cell with no outflow
            break
        row, col = row + step[0], col + step[1]
    if len(cells) < 2:
        raise ValueError("The terrain has no downhill direction from this point.")

    # Cell centres as map coordinates.
    points = [coarse_transform * (c + 0.5, r + 0.5) for r, c in cells]
    line = LineString(points)
    factor = routing["factor"]

    def height(cell):
        r, c = cell
        block = dem[r * factor:(r + 1) * factor, c * factor:(c + 1) * factor]
        return float(np.nanmean(block)) if np.isfinite(block).any() else None

    # The last cells may lie in the empty edge of the DEM: use the last
    # cell that has a height.
    start_height = height(cells[0])
    end_height = next((h for h in map(height, reversed(cells)) if h is not None), None)

    listed = []
    if Path(settlements_path).exists() and json.loads(Path(settlements_path).read_text())["features"]:
        places = gpd.read_file(settlements_path).to_crs(crs)
        places["offset_m"] = places.distance(line)
        near = places[places["offset_m"] <= NEAR_PATH_M].copy()
        # Distance along the path to the point nearest each settlement.
        near["along_km"] = [line.project(g) / 1000 for g in near.geometry]
        for _, place in near.sort_values("along_km").iterrows():
            listed.append({
                "name": place.get("name"), "name_en": place.get("name_en"),
                "buildings": int(place.get("buildings") or 0),
                "km_downstream_of_start": round(float(place["along_km"]), 1),
                "metres_from_path": int(round(float(place["offset_m"]))),
                "cut_off_vehicle": bool(place.get("cut_off_vehicle")),
                "cut_off_any": bool(place.get("cut_off_any")),
            })

    path_wgs84 = gpd.GeoSeries([line], crs=crs).to_crs(4326).iloc[0]
    return {
        "path": {"type": "Feature", "properties": {},
                 "geometry": {"type": "LineString",
                              "coordinates": [[round(x, 6), round(y, 6)]
                                              for x, y in path_wgs84.coords]}},
        "length_km": round(line.length / 1000, 1),
        "drop_m": (int(round(start_height - end_height))
                   if start_height is not None and end_height is not None else None),
        "settlements": listed,
        "note": (f"Steepest-descent path on the 30 m Copernicus DEM, inside the analysed box "
                 f"only. Settlements within {int(NEAR_PATH_M)} m of the path are listed. This "
                 "shows where water would run, not how far or how deep a flood would reach."),
    }
