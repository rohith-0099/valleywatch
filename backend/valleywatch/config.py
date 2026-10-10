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

    # --- River corridor (from the DEM only) ---
    # A cell is "river" when at least this much land drains through it.
    river_min_catchment_km2: float = 10.0
    # The corridor is all ground less than this height above the nearest
    # river cell. Flood water and debris travel along the valley floor, so
    # detections outside the corridor are treated as unrelated change.
    corridor_max_hand_m: float = 40.0
    # Inside the corridor the slope limit is relaxed: in a gorge the 30 m DEM
    # blurs the river bed into the valley walls and makes it look steep.
    corridor_max_slope_deg: float = 45.0

    # --- Hysteresis ---
    # Pixels with a weaker change (this fraction of the threshold) are kept
    # when they touch a confident detection. This follows thin channels.
    hysteresis_low_fraction: float = 0.6

    # --- Debris rule ---
    # A VV rise alone is kept only for patches at least this large; smaller
    # patches must also show a VH rise.
    debris_large_patch_m2: float = 3000.0

    # --- Pre-event baseline ---
    # Confidence is multiplied by this where the ground was already changing
    # between the two images taken before the flood.
    baseline_confidence_factor: float = 0.5

    # --- Sentinel-2 check ---
    ndvi_vegetated: float = 0.4       # NDVI above this = vegetated
    ndvi_drop: float = 0.25           # NDVI fall that counts as vegetation loss
    ndvi_stable: float = 0.10         # NDVI fall below this = vegetation intact
    water_index_min: float = 0.0      # MNDWI above this = open water
    optical_confirm_bonus: float = 0.25
    optical_disagree_factor: float = 0.6
    optical_only_confidence: float = 0.5
    optical_min_patch_m2: float = 3000.0

    # --- Live runs ---
    # Boxes up to this size are fetched by direct download (minutes). Larger
    # boxes need batch jobs (much slower) and must be asked for explicitly.
    max_live_area_km2: float = 400.0
    parallel_downloads: int = 2       # concurrent requests the free tier allows

    # --- Damage overlay ---
    # Map positions are uncertain by about one 10 m pixel, so a feature this
    # close to a hazard polygon is reported as a low-confidence hit.
    feature_tolerance_m: float = 10.0
    min_road_hit_m: float = 10.0      # shorter overlaps are pixel-edge noise
    # A bridge counts as hit when the hazard reaches one of its ends.
    bridge_end_radius_m: float = 15.0
    bridge_debris_cover: float = 0.5  # or when debris covers this share of it

    # --- Clean-up ---
    min_patch_m2: float = 1000.0     # 10 pixels; smaller patches are speckle
