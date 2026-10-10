"""Download terrain-corrected Sentinel-1 backscatter and the Copernicus DEM.

Processing runs on the Copernicus Data Space openEO service, so we never
handle the raw 1 GB radar products ourselves. The service orthorectifies each
image with the Copernicus 30 m DEM, which puts every pixel at its true map
position even on steep slopes.
"""
from datetime import date, timedelta
from pathlib import Path

import openeo

from .config import OPENEO_URL

# Above this many pixels a request is too large for a direct download and is
# sent as a batch job instead (slower to start, but no timeout).
SYNC_PIXEL_LIMIT = 4_000_000


def connect():
    """Open an authenticated openEO session.

    The first run prints a link for a browser login. openEO then stores a
    refresh token on disk, so later runs need no interaction.
    """
    return openeo.connect(OPENEO_URL).authenticate_oidc()


def utm_epsg_for(bbox):
    """EPSG code of the UTM zone at the box centre.

    We work in UTM so that pixels are square and measured in metres, which
    slope and area calculations need.
    """
    west, south, east, north = bbox
    zone = int(((west + east) / 2 + 180) // 6) + 1
    return (32600 if (south + north) / 2 >= 0 else 32700) + zone


def _extent(bbox):
    west, south, east, north = bbox
    return {"west": west, "south": south, "east": east, "north": north}


def _approx_pixels(bbox, resolution_m):
    west, south, east, north = bbox
    height_m = (north - south) * 111_000
    width_m = (east - west) * 111_000 * 0.9
    return (height_m / resolution_m) * (width_m / resolution_m)


def _save(cube, path, bbox, resolution_m, title):
    path = Path(path)
    if path.exists():  # cached from an earlier run
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    if _approx_pixels(bbox, resolution_m) <= SYNC_PIXEL_LIMIT:
        cube.download(str(path), format="GTiff")
    else:
        cube.execute_batch(str(path), out_format="GTiff", title=title)
    return path


def fetch_backscatter(conn, bbox, day, direction, path, resolution_m=10.0):
    """Fetch VV and VH backscatter for one pass (identified by date and direction)."""
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
    cube = cube.resample_spatial(resolution=resolution_m,
                                 projection=utm_epsg_for(bbox))
    return _save(cube, path, bbox, resolution_m, f"ValleyWatch S1 {day}")


def fetch_dem(conn, bbox, path, resolution_m=10.0):
    """Fetch the Copernicus 30 m DEM, resampled onto the radar pixel grid."""
    cube = conn.load_collection("COPERNICUS_30", spatial_extent=_extent(bbox),
                                bands=["DEM"])
    cube = cube.reduce_dimension(dimension="t", reducer="max")
    cube = cube.resample_spatial(resolution=resolution_m,
                                 projection=utm_epsg_for(bbox), method="bilinear")
    return _save(cube, path, bbox, resolution_m, "ValleyWatch DEM")
