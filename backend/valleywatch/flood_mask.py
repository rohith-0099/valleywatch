"""Step 2: turn a before/after radar pair into water and debris masks.

Radar brightness ("backscatter") depends on surface roughness:

* calm water is a mirror, reflects the beam away and looks dark, so new
  water shows as a strong DROP in backscatter;
* fresh rubble, boulders and churned mud are rough and scatter strongly, so
  debris shows as a strong RISE in backscatter.
"""
import numpy as np
from scipy import ndimage
from skimage.filters import apply_hysteresis_threshold
from skimage.morphology import remove_small_objects

CLASS_WATER, CLASS_DEBRIS = 1, 2
BANDS = ("VV", "VH")


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


def filtered_db(image, settings):
    """Speckle-filter both polarisations of one image and convert to dB."""
    return {band: to_db(lee_filter(image[band], settings.lee_window,
                                   settings.equivalent_looks)).astype("float32")
            for band in BANDS}


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


def scaled_change(earlier_db, later_db, usable, settings):
    """Log-ratio change (later minus earlier, in dB) and its scaled form z.

    z = 1 means "exactly at this image's threshold", z = 2 twice as strong.
    Returns (change, z, thresholds), the first two as dicts per band.
    """
    change, z, thresholds = {}, {}, {}
    for band in BANDS:
        change[band] = later_db[band] - earlier_db[band]
        centre, threshold = adaptive_threshold(change[band], usable, settings)
        z[band] = (change[band] - centre) / threshold
        thresholds[band] = {"typical_change_db": round(centre, 2),
                            "threshold_db": round(threshold, 2)}
    return change, z, thresholds


def dark_like_water(db, settings):
    """Pixels as dark as calm open water (or radar shadow) in one image."""
    return ((db["VV"] < settings.permanent_water_vv_db) &
            (db["VH"] < settings.permanent_water_vh_db))


def classify_change(z, allowed, dark_before, pixel_m, settings):
    """Apply the water and debris rules to a scaled change image.

    Returns (water, debris, water_strength, debris_strength).
    """
    low = settings.hysteresis_low_fraction
    min_pixels = max(int(round(settings.min_patch_m2 / pixel_m ** 2)), 1)
    large_pixels = max(int(round(settings.debris_large_patch_m2 / pixel_m ** 2)), 1)

    # Water: both polarisations drop. Requiring both avoids calling stripped
    # vegetation "water" (losing vegetation lowers VH but not VV). Ground
    # that was already water-dark before the event is not NEW water.
    water_strength = np.where(allowed & ~dark_before, np.minimum(-z["VV"], -z["VH"]), 0.0)
    water_strength = np.nan_to_num(water_strength)
    # Hysteresis: start from confident pixels (strength >= 1) and grow into
    # touching pixels with a weaker change. Follows thin river channels
    # without admitting isolated weak noise.
    water = apply_hysteresis_threshold(water_strength, low, 1.0)

    # Debris: VV rises (rougher surface). A river bed newly filled with
    # rubble counts, so previously dark ground is allowed here.
    debris_strength = np.nan_to_num(np.where(allowed, z["VV"], 0.0))
    candidate = apply_hysteresis_threshold(debris_strength, low, 1.0)
    # A VV rise alone is common noise (wet soil, crops, buildings). Keep it
    # only for large patches; small ones must show a VH rise as well.
    large = remove_small_objects(candidate, max_size=large_pixels - 1)
    debris = large | (candidate & (z["VH"] > 1))

    water = remove_small_objects(water, max_size=min_pixels - 1)
    debris = remove_small_objects(debris & ~water, max_size=min_pixels - 1)
    return water, debris, water_strength, debris_strength


def detect_flood_and_debris(before, after, terrain, corridor, pixel_m, settings,
                            baseline=None):
    """Classify every pixel as water, debris or neither.

    before / after / baseline: dicts with linear 'VV' and 'VH' arrays on one
    grid. `baseline` is an optional image taken one pass before `before`; it
    shows how much the area changes when there is no flood.
    terrain: output of terrain.terrain_mask. corridor: boolean river corridor.
    """
    before_db, after_db = filtered_db(before, settings), filtered_db(after, settings)
    has_data = np.isfinite(before_db["VV"]) & np.isfinite(after_db["VV"]) & \
        np.isfinite(before_db["VH"]) & np.isfinite(after_db["VH"])

    # Ground the radar can judge: not in layover or shadow, and not steep.
    # Inside the river corridor a steeper limit applies (see config).
    slope_ok = np.where(corridor, terrain["slope"] <= settings.corridor_max_slope_deg,
                        terrain["slope"] <= settings.max_slope_deg)
    usable = has_data & ~terrain["blind"] & slope_ok
    # Detections are only accepted on the valley floor.
    allowed = usable & corridor

    change, z, thresholds = scaled_change(before_db, after_db, usable, settings)
    dark_before = dark_like_water(before_db, settings)
    water, debris, water_strength, debris_strength = classify_change(
        z, allowed, dark_before, pixel_m, settings)

    classes = np.zeros(water.shape, dtype=np.uint8)
    classes[debris] = CLASS_DEBRIS
    classes[water] = CLASS_WATER

    # Confidence, 0 to 1: how far past the threshold the change is.
    # A change exactly at threshold scores 0.33, three times threshold 1.0.
    confidence = np.zeros(water.shape, dtype=np.float32)
    confidence[water] = np.clip(water_strength[water] / 3.0, 0, 1)
    # Debris is surer when VH rises too.
    debris_score = debris_strength * np.where(z["VH"] > 1, 1.0, 0.7)
    confidence[debris] = np.clip(debris_score[debris] / 3.0, 0, 1)

    result = {
        "classes": classes, "confidence": confidence,
        "change_vv_db": change["VV"], "change_vh_db": change["VH"],
        "before_vv_db": before_db["VV"], "after_vv_db": after_db["VV"],
        "not_mapped": has_data & ~usable, "corridor": corridor,
        # Counted on mappable ground only: on steep ground "dark" is mostly
        # radar shadow, not water.
        "permanent_water": dark_before & usable,
        "has_data": has_data, "thresholds": thresholds, "baseline": None,
    }

    if baseline is not None:
        # The same rules applied to two images from BEFORE the flood. Anything
        # found here is normal change (rain, river level, farming), so:
        # 1. its area tells us the false-alarm level to expect, and
        # 2. ground that was already changing gets a lower confidence.
        baseline_db = filtered_db(baseline, settings)
        base_ok = usable & np.isfinite(baseline_db["VV"]) & np.isfinite(baseline_db["VH"])
        _, base_z, base_thresholds = scaled_change(baseline_db, before_db, base_ok, settings)
        base_water, base_debris, _, _ = classify_change(
            base_z, base_ok & corridor, dark_like_water(baseline_db, settings),
            pixel_m, settings)
        already_changing = base_ok & ((np.abs(base_z["VV"]) > 1) | (np.abs(base_z["VH"]) > 1))
        detected = classes > 0
        confidence[detected & already_changing] *= settings.baseline_confidence_factor
        pixel_km2 = pixel_m ** 2 / 1e6
        result["baseline"] = {
            "thresholds": base_thresholds,
            "normal_change_water_km2": round(float(base_water.sum()) * pixel_km2, 3),
            "normal_change_debris_km2": round(float(base_debris.sum()) * pixel_km2, 3),
            "already_changing_percent_of_corridor": round(
                100 * float((already_changing & corridor).sum()) / max(int(allowed.sum()), 1), 2),
            "detections_down_weighted_km2": round(
                float((detected & already_changing).sum()) * pixel_km2, 3),
        }
    return result
