"""Step 2: turn a before/after radar pair into water and debris masks.

Radar brightness ("backscatter") depends on surface roughness:

* calm water is a mirror, reflects the beam away and looks dark, so new
  water shows as a strong DROP in backscatter;
* fresh rubble, boulders and churned mud are rough and scatter strongly, so
  debris shows as a strong RISE in backscatter.
"""
import numpy as np
from scipy import ndimage
from skimage.morphology import remove_small_objects

from .terrain import terrain_mask

CLASS_WATER, CLASS_DEBRIS = 1, 2


def to_db(power):
    """Convert linear backscatter to decibels (zero or negative becomes NaN)."""
    power = np.where(power > 0, power, np.nan)
    return 10.0 * np.log10(power)


def lee_filter(power, window, looks):
    """Lee speckle filter on linear backscatter.

    Radar images are grainy ("speckle"). The Lee filter averages flat areas
    but keeps edges: where local variance is no more than speckle would give,
    it returns the local mean; where it is higher, it keeps the pixel.
    """
    valid = np.isfinite(power)
    filled = np.where(valid, power, 0.0)
    # Local mean and variance over valid pixels only.
    weight = ndimage.uniform_filter(valid.astype(float), window)
    weight = np.where(weight > 0, weight, np.nan)
    mean = ndimage.uniform_filter(filled, window) / weight
    mean_sq = ndimage.uniform_filter(filled ** 2, window) / weight
    variance = np.maximum(mean_sq - mean ** 2, 0.0)
    speckle_var = 1.0 / looks  # relative variance of fully developed speckle
    signal_var = np.maximum((variance - mean ** 2 * speckle_var) / (1 + speckle_var), 0.0)
    gain = np.where(variance > 0, signal_var / np.where(variance > 0, variance, 1), 0.0)
    out = mean + gain * (filled - mean)
    return np.where(valid, out, np.nan)


def adaptive_threshold(change_db, usable, settings):
    """Pick the change threshold (dB) for this particular image.

    Most of any image did not flood, so the bulk of the change values is just
    noise plus an overall shift (for example wetter soil after rain). We
    measure that with the median and the MAD, which a small flooded fraction
    cannot distort, and call a pixel changed when it is `noise_sigmas` beyond.
    Returns (centre, threshold).
    """
    values = change_db[usable & np.isfinite(change_db)]
    if values.size < 1000:
        return 0.0, settings.min_change_db
    centre = float(np.median(values))
    sigma = 1.4826 * float(np.median(np.abs(values - centre)))
    threshold = settings.noise_sigmas * sigma
    threshold = min(max(threshold, settings.min_change_db), settings.max_change_db)
    return centre, float(threshold)


def detect_flood_and_debris(before, after, dem, pixel_m, direction, settings):
    """Classify every pixel as water, debris or neither.

    before / after: dicts with linear 'VV' and 'VH' arrays on the same grid.
    Returns a dict with the class raster, a 0-1 confidence raster, the change
    images, the masks used and the thresholds chosen.
    """
    # 1. Speckle filter, then decibels.
    db = {}
    for name, image in (("before", before), ("after", after)):
        for band in ("VV", "VH"):
            filtered = lee_filter(image[band], settings.lee_window, settings.equivalent_looks)
            db[name, band] = to_db(filtered)

    # 2. Log-ratio change: after minus before in dB.
    change = {band: db["after", band] - db["before", band] for band in ("VV", "VH")}
    has_data = np.isfinite(change["VV"]) & np.isfinite(change["VH"])

    # 3. Pixels we cannot or should not classify.
    terrain = terrain_mask(dem, pixel_m, direction, settings)
    usable = has_data & ~terrain["any"]

    # 4. Water that was already there before the event (river, lakes). Radar
    #    shadow is equally dark, so this also catches shadow the DEM missed.
    permanent_water = ((db["before", "VV"] < settings.permanent_water_vv_db) &
                       (db["before", "VH"] < settings.permanent_water_vh_db))

    # 5. Area-specific thresholds, one per polarisation.
    centre, threshold, z = {}, {}, {}
    for band in ("VV", "VH"):
        centre[band], threshold[band] = adaptive_threshold(change[band], usable, settings)
        # z = change measured in units of this image's threshold.
        z[band] = (change[band] - centre[band]) / threshold[band]

    # 6. Classification rules.
    #    Water: both polarisations drop. Requiring both avoids calling stripped
    #    vegetation "water" (losing vegetation lowers VH but not VV).
    water = usable & ~permanent_water & (z["VV"] < -1) & (z["VH"] < -1)
    #    Debris: VV rises (rougher surface). A river bed newly filled with
    #    rubble counts, so permanent water is NOT removed here.
    debris = usable & (z["VV"] > 1)

    # 7. Remove isolated specks.
    min_pixels = max(int(round(settings.min_patch_m2 / pixel_m ** 2)), 1)
    water = remove_small_objects(water, max_size=min_pixels - 1)
    debris = remove_small_objects(debris, max_size=min_pixels - 1)

    classes = np.zeros(water.shape, dtype=np.uint8)
    classes[debris] = CLASS_DEBRIS
    classes[water] = CLASS_WATER

    # 8. Confidence, 0 to 1: how far past the threshold the change is.
    #    A change exactly at threshold scores 0.33, three times threshold 1.0.
    confidence = np.zeros(water.shape, dtype=np.float32)
    water_strength = np.minimum(-z["VV"], -z["VH"])
    # Debris is surer when VH rises too.
    debris_strength = z["VV"] * np.where(z["VH"] > 1, 1.0, 0.7)
    confidence[water] = np.clip(water_strength[water] / 3.0, 0, 1)
    confidence[debris & ~water] = np.clip(debris_strength[debris & ~water] / 3.0, 0, 1)

    return {
        "classes": classes, "confidence": confidence,
        "change_vv_db": change["VV"], "change_vh_db": change["VH"],
        "before_vv_db": db["before", "VV"], "after_vv_db": db["after", "VV"],
        "terrain": terrain, "permanent_water": permanent_water & has_data,
        "has_data": has_data,
        "thresholds": {
            band: {"typical_change_db": round(centre[band], 2),
                   "threshold_db": round(threshold[band], 2)} for band in ("VV", "VH")},
    }
