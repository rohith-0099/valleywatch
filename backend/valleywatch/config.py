"""All tunable settings for the flood-mapping pipeline live here.

Nothing in this file is specific to one valley. The only inputs the pipeline
needs are a bounding box and a flood date; everything below is a default that
can be overridden from the command line or the API.
"""
from dataclasses import dataclass

CATALOGUE_URL = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products"
OPENEO_URL = "openeo.dataspace.copernicus.eu"


@dataclass
class Settings:
    # --- Scene picker ---
    # Sentinel-1 repeats the same track every 12 days (6 with two satellites),
    # so 36 days back always contains at least two passes of every track.
    search_days_before: int = 36
    search_days_after: int = 24
    # A scene pair must cover at least this fraction of the requested box.
    min_coverage: float = 0.90

    # --- Raster grid ---
    resolution_m: float = 10.0  # native Sentinel-1 GRD pixel spacing

    # --- Speckle filter ---
    lee_window: int = 5          # 5x5 pixels = 50 m, keeps narrow rivers visible
    equivalent_looks: float = 4.4  # ENL of Sentinel-1 IW GRDH products

    # --- Change thresholds (dB) ---
    # The threshold adapts to each area: a pixel counts as "changed" when its
    # change is more than `noise_sigmas` robust standard deviations away from
    # the typical (median) change of the whole image.
    noise_sigmas: float = 3.0
    # The adaptive threshold is never allowed outside these limits. The lower
    # limit is the fallback when the image is very quiet.
    min_change_db: float = 3.0
    max_change_db: float = 6.0

    # --- Permanent water (seen in the BEFORE image) ---
    # Calm open water is very dark in radar. Pixels this dark before the event
    # were already water (or radar shadow) and are not new flooding.
    permanent_water_vv_db: float = -17.0
    permanent_water_vh_db: float = -24.0

    # --- Terrain masks ---
    max_slope_deg: float = 30.0      # water does not pond on steeper ground
    # Sentinel-1 IW incidence angle runs from about 30 to 46 degrees. We use
    # the middle of the swath because the exact per-pixel value is not needed
    # once a safety margin is added.
    incidence_angle_deg: float = 38.0
    geometry_margin_deg: float = 5.0

    # --- Clean-up ---
    min_patch_m2: float = 1000.0     # 10 pixels; smaller patches are speckle
