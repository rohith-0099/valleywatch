"""Download satellite data from the Copernicus Data Space openEO service.

Processing runs on the Copernicus servers, so we never handle the raw 1 GB
products ourselves. Sentinel-1 is orthorectified there with the Copernicus
30 m DEM, which puts every pixel at its true map position even on slopes.
"""
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import openeo
from dotenv import load_dotenv

from .config import OPENEO_URL

REPO_ROOT = Path(__file__).resolve().parents[2]

# Green, red, near infrared and short-wave infrared: enough for a vegetation
# index and a water index.
S2_BANDS = ["B03", "B04", "B08", "B11"]


def connect():
    """Open an authenticated openEO session.

    If CDSE_CLIENT_ID and CDSE_CLIENT_SECRET are set (in .env), log in with
    them: no browser is needed, which suits a live demo. Otherwise fall back
    to a browser login; openEO then stores a refresh token for later runs.
    """
    load_dotenv(REPO_ROOT / ".env")
    conn = openeo.connect(OPENEO_URL)
    client_id = os.environ.get("CDSE_CLIENT_ID")
    client_secret = os.environ.get("CDSE_CLIENT_SECRET")
    if client_id and client_secret:
        return conn.authenticate_oidc_client_credentials(
            client_id=client_id, client_secret=client_secret)
    return conn.authenticate_oidc()


def utm_epsg_for(bbox):
    """EPSG code of the UTM zone at the box centre.

    We work in UTM so that pixels are square and measured in metres, which
    slope and area calculations need.
    """
    west, south, east, north = bbox
    zone = int(((west + east) / 2 + 180) // 6) + 1
    return (32600 if (south + north) / 2 >= 0 else 32700) + zone


def bbox_area_km2(bbox):
    """Approximate ground area of a longitude/latitude box."""
    import math
    west, south, east, north = bbox
    height_km = (north - south) * 111.0
    width_km = (east - west) * 111.0 * math.cos(math.radians((south + north) / 2))
    return height_km * width_km


def _extent(bbox):
    west, south, east, north = bbox
    return {"west": west, "south": south, "east": east, "north": north}


def backscatter_cube(conn, bbox, day, direction, resolution_m):
    """VV and VH backscatter for one pass (identified by date and direction)."""
    day = date.fromisoformat(day) if isinstance(day, str) else day
    cube = conn.load_collection(
        "SENTINEL1_GRD",
        spatial_extent=_extent(bbox),
        temporal_extent=[day.isoformat(), (day + timedelta(days=1)).isoformat()],
        bands=["VV", "VH"],
        # Keep only the chosen pass direction, in case an ascending and a
        # descending pass fall on the same calendar day.
        properties={"sat:orbit_state": lambda v: v == direction.lower()},
    )
    # sigma0 on the ellipsoid, orthorectified with the Copernicus DEM. We do
    # not need radiometric terrain flattening: the before and after images
    # share one viewing geometry, so slope brightness cancels in their ratio.
    cube = cube.sar_backscatter(coefficient="sigma0-ellipsoid",
                                elevation_model="COPERNICUS_30")
    cube = cube.reduce_dimension(dimension="t", reducer="mean")
    return cube.resample_spatial(resolution=resolution_m, projection=utm_epsg_for(bbox))


def dem_cube(conn, bbox, resolution_m):
    """Copernicus 30 m DEM, resampled onto the radar pixel grid."""
    cube = conn.load_collection("COPERNICUS_30", spatial_extent=_extent(bbox),
                                bands=["DEM"])
    cube = cube.reduce_dimension(dimension="t", reducer="max")
    return cube.resample_spatial(resolution=resolution_m,
                                 projection=utm_epsg_for(bbox), method="bilinear")


def sentinel2_clear_composite_cube(conn, bbox, start, end, resolution_m):
    """Cloud-free Sentinel-2 composite of a time window.

    Clouds are removed pixel by pixel with the scene classification band, so
    a mostly cloudy scene still contributes wherever it has a gap over the
    area. Each output pixel is the median of its clear observations; pixels
    with no clear observation in the window stay empty.
    """
    cube = conn.load_collection(
        "SENTINEL2_L2A", spatial_extent=_extent(bbox),
        temporal_extent=[start.isoformat(), end.isoformat()],
        bands=S2_BANDS + ["SCL"])
    # Scene classification values that are not clear ground: 0-3 are no
    # data, defective, dark and cloud shadow; 7-10 are unclassified, clouds
    # and cirrus. Vegetation (4), bare soil (5), water (6), snow (11) remain.
    scl = cube.band("SCL")
    not_clear = (scl < 4) | ((scl > 6) & (scl < 11))
    clear = cube.filter_bands(S2_BANDS).mask(not_clear)
    composite = clear.reduce_dimension(dimension="t", reducer="median")
    return composite.resample_spatial(resolution=resolution_m,
                                      projection=utm_epsg_for(bbox))


def _with_retry(action, label, progress, attempts=6):
    """Run a server request, retrying after a wait when the server is busy.

    The free tier limits how many requests run at once (HTTP 429) and the
    service sometimes fails on its own side (HTTP 5xx). Both usually pass
    after a short wait.
    """
    for attempt in range(1, attempts + 1):
        try:
            return action()
        except openeo.rest.OpenEoApiPlainError as error:
            status = error.http_status_code or 0
            if not (status == 429 or status >= 500) or attempt == attempts:
                raise
            wait_s = 15 * attempt
            progress(f"{label}: server answered {status}, retrying in {wait_s} s")
            time.sleep(wait_s)


def _download_one(request, use_batch, progress):
    """Fetch one raster, unless a previous run already cached it."""
    path, label = Path(request["path"]), request["label"]
    if path.exists():
        progress(f"{label}: using cached file")
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write to a temporary name first so an interrupted download can never
    # be mistaken for a complete cached file.
    partial = path.with_suffix(".part.tif")
    progress(f"{label}: requested")
    if use_batch:
        _with_retry(lambda: request["cube"].execute_batch(
            str(partial), out_format="GTiff", title=f"ValleyWatch {label}",
            print=lambda message: progress(f"{label}: {message}")), label, progress)
    else:
        _with_retry(lambda: request["cube"].download(str(partial), format="GTiff"),
                    label, progress)
    partial.rename(path)
    progress(f"{label}: done")
    return path


def download_all(requests, bbox, settings, progress=print):
    """Fetch several rasters at the same time.

    requests: list of {'label', 'cube', 'path', 'optional'}.
    Returns {label: path}. A failed optional request maps to the error text
    instead of stopping the run; a failed required request raises.
    """
    use_batch = bbox_area_km2(bbox) > settings.max_live_area_km2
    results = {}
    with ThreadPoolExecutor(max_workers=settings.parallel_downloads) as pool:
        futures = {r["label"]: pool.submit(_download_one, r, use_batch, progress)
                   for r in requests}
        for request in requests:
            label = request["label"]
            try:
                results[label] = futures[label].result()
            except Exception as error:  # noqa: BLE001 - reported to the user below
                if not request.get("optional"):
                    raise
                progress(f"{label}: not available ({error})")
                results[label] = f"failed: {error}"
    return results
