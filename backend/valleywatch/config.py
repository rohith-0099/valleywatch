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
    # Which cells count as "river". In "adaptive" mode the rule follows the
    # box: a river is any stream draining at least `river_fraction_of_largest`
    # of the biggest drainage area found inside the box (never less than
    # `river_min_catchment_km2`). This works for a great river and a small
    # one alike. "fixed" mode uses `river_fixed_catchment_km2` instead.
    river_catchment_mode: str = "adaptive"
    river_fraction_of_largest: float = 0.02
    river_min_catchment_km2: float = 5.0
    river_fixed_catchment_km2: float = 100.0
    # The corridor is all ground less than this height above the nearest
    # river cell. Flood water and debris travel along the valley floor, so
    # detections outside the corridor are treated as unrelated change.
    corridor_max_hand_m: float = 20.0
    # Inside the corridor the slope limit is relaxed: in a gorge the 30 m DEM
    # blurs the river bed into the valley walls and makes it look steep.
    corridor_max_slope_deg: float = 45.0
    # A flood runs downstream without gaps. Detections are kept only on
    # river reaches downstream of a confident patch at least this large.
    seed_min_area_m2: float = 5000.0
    # Where radar is blind (gorges), optical alone may start a flood path,
    # but only from a patch this large: small optical patches are often
    # fields or leftover cloud shadow.
    optical_seed_min_area_m2: float = 20000.0

    # --- Hysteresis ---
    # Pixels with a weaker change (this fraction of the threshold) are kept
    # when they touch a confident detection. This follows thin channels.
    hysteresis_low_fraction: float = 0.6

    # --- Debris rule ---
    # A VV rise alone is kept only for patches at least this large; smaller
    # patches must also show a VH rise.
    debris_large_patch_m2: float = 3000.0

    # --- Sentinel-2 check ---
    s2_reflectance_scale: float = 10000.0  # stored value / scale = reflectance
    ndvi_vegetated: float = 0.4       # NDVI above this = vegetated
    ndvi_drop: float = 0.25           # NDVI fall that counts as vegetation loss
    ndvi_stable: float = 0.10         # NDVI fall below this = vegetation intact
    ndvi_bare_max: float = 0.3        # after the event the pixel must be this bare
    # Cloud and terrain shadow is dark in every band and fakes a loss of
    # greenness. Real sediment is bright, so darker pixels are rejected.
    shadow_max_reflectance: float = 0.08
    water_index_min: float = 0.0      # MNDWI above this = open water
    water_green_min: float = 0.06     # muddy flood water is bright in green
    optical_min_patch_m2: float = 3000.0

    # --- Confidence by agreement of sources ---
    score_radar_and_optical: float = 0.9   # high
    score_optical_only: float = 0.6        # medium
    score_radar_water_unchecked: float = 0.6  # medium: no clear optical view
    score_radar_only: float = 0.3          # low
    # Subtracted where the ground was already changing before the flood.
    score_already_changing_penalty: float = 0.3

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
    # A bridge is judged on the ground just beyond each end of its deck,
    # this far along the bridge line onto the bank.
    bridge_approach_m: float = 10.0

    # --- Clean-up ---
    min_patch_m2: float = 1000.0     # 10 pixels; smaller patches are speckle
