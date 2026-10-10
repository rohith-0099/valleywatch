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


def noise_level(change_db, usable):
    """Robust spread (dB) of a change image: 1.4826 x median absolute deviation."""
    values = change_db[usable & np.isfinite(change_db)]
    if values.size < 1000:
        return None
    return 1.4826 * float(np.median(np.abs(values - np.median(values))))


def adaptive_threshold(change_db, usable, settings, noise_db=None):
    """Pick the change threshold (dB) for this particular image.

    A pixel counts as changed when its change is `noise_sigmas` times the
    noise level away from the typical change of unchanged ground.

    noise_db: noise level measured on a pair of images from BEFORE the flood.
    That pair cannot contain the flood, so it gives the true noise even when
    much of the area flooded. Without it the noise is estimated from the
    flood pair itself, which is only sound if most of the image did not flood.
    Returns (centre, threshold).
    """
    values = change_db[usable & np.isfinite(change_db)]
    if values.size < 1000:
        return 0.0, settings.min_change_db
    centre = float(np.median(values))
    sigma = noise_db if noise_db is not None else 1.4826 * float(np.median(np.abs(values - centre)))
    threshold = settings.noise_sigmas * sigma
    threshold = float(min(max(threshold, settings.min_change_db), settings.max_change_db))
    # Re-centre on ground that did not change, so that a large flooded area
    # does not drag the "typical change" towards itself.
    unchanged = values[np.abs(values - centre) < threshold]
    if unchanged.size >= 1000:
        centre = float(np.median(unchanged))
    return centre, threshold


def scaled_change(earlier_db, later_db, usable, settings, noise=None):
    """Log-ratio change (later minus earlier, in dB) and its scaled form z.

    z = 1 means "exactly at this image's threshold", z = 2 twice as strong.
    noise: optional {band: noise level in dB} from a pre-event pair.
    Returns (change, z, thresholds), the first two as dicts per band.
    """
    change, z, thresholds = {}, {}, {}
    for band in BANDS:
        change[band] = later_db[band] - earlier_db[band]
        centre, threshold = adaptive_threshold(change[band], usable, settings,
                                               noise.get(band) if noise else None)
        z[band] = (change[band] - centre) / threshold
        thresholds[band] = {"typical_change_db": round(centre, 2),
                            "threshold_db": round(threshold, 2),
                            "noise_from": "pre-event pair" if noise and noise.get(band)
                                          else "flood pair"}
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


def detect_flood_and_debris(before, after, terrain, corridor, reach, pixel_m, settings,
                            baseline=None):
    """Radar detection of new water and debris.

    before / after / baseline: dicts with linear 'VV' and 'VH' arrays on one
    grid. `baseline` is an optional image taken one pass before `before`; it
    shows how much the area changes when there is no flood.
    terrain: output of terrain.terrain_mask. corridor / reach: the two
    river zones from corridor.river_corridor.

    Returns boolean 'water' and 'debris' masks plus everything later steps
    need. Classes and confidence are assigned after the optical check.
    """
    before_db, after_db = filtered_db(before, settings), filtered_db(after, settings)
    has_data = np.isfinite(before_db["VV"]) & np.isfinite(after_db["VV"]) & \
        np.isfinite(before_db["VH"]) & np.isfinite(after_db["VH"])

    # Ground the radar can judge: not in layover or shadow, and not steep.
    # Inside the river corridor a steeper limit applies (see config).
    slope_ok = np.where(corridor, terrain["slope"] <= settings.corridor_max_slope_deg,
                        terrain["slope"] <= settings.max_slope_deg)
    usable = has_data & ~terrain["blind"] & slope_ok
    # Radar change is considered anywhere in the reach zone. Whether a patch
    # there is kept is decided later (it must connect to the valley floor).
    allowed = usable & reach

    # Noise level: from the pre-event pair when there is one (see
    # `adaptive_threshold`), otherwise from the flood pair itself.
    baseline_db = base_ok = noise = None
    if baseline is not None:
        baseline_db = filtered_db(baseline, settings)
        base_ok = usable & np.isfinite(baseline_db["VV"]) & np.isfinite(baseline_db["VH"])
        noise = {band: noise_level(before_db[band] - baseline_db[band], base_ok)
                 for band in BANDS}

    change, z, thresholds = scaled_change(before_db, after_db, usable, settings, noise)
    dark_before = dark_like_water(before_db, settings)
    water, debris, water_strength, _ = classify_change(
        z, allowed, dark_before, pixel_m, settings)

    result = {
        "water": water, "debris": debris,
        # The confident heart of each water patch (at or past the threshold).
        "water_core": water & (water_strength >= 1.0),
        "change_vv_db": change["VV"], "change_vh_db": change["VH"],
        "before_vv_db": before_db["VV"], "after_vv_db": after_db["VV"],
        "not_mapped": has_data & ~usable,
        # Counted on mappable ground only: on steep ground "dark" is mostly
        # radar shadow, not water.
        "permanent_water": dark_before & usable,
        "has_data": has_data, "thresholds": thresholds,
        "already_changing": np.zeros(water.shape, dtype=bool), "no_flood": None,
    }

    if baseline is not None:
        # The same rules applied to two images from BEFORE the flood. Anything
        # found there is normal change (rain, river level, farming).
        _, base_z, base_thresholds = scaled_change(baseline_db, before_db, base_ok, settings, noise)
        base_water, base_debris, base_strength, _ = classify_change(
            base_z, base_ok & reach, dark_like_water(baseline_db, settings),
            pixel_m, settings)
        low = settings.hysteresis_low_fraction
        already_changing = base_ok & ((np.abs(base_z["VV"]) > low) | (np.abs(base_z["VH"]) > low))
        result["already_changing"] = already_changing
        result["no_flood"] = {"water": base_water, "debris": base_debris,
                              "water_core": base_water & (base_strength >= 1.0),
                              "thresholds": base_thresholds}
        # Kept for the acceptance test, which compares like with like.
        result["debris_before_pruning"] = debris.copy()
        # A VV rise where VV was already swinging before the flood is not
        # evidence of debris. Drop those pixels, then drop the crumbs left.
        min_pixels = max(int(round(settings.min_patch_m2 / pixel_m ** 2)), 1)
        result["debris"] = remove_small_objects(debris & ~already_changing,
                                                max_size=min_pixels - 1)
    return result


def merge_tracks(runs):
    """Combine radar detections from several tracks into one.

    Each track sees the valley from a different side, so each has its own
    blind zones. A pixel is detected if ANY track detects it, and it is
    "not mapped" only if EVERY track is blind there. Pictures for the
    quick-look come from the first (primary) track.
    """
    merged = dict(runs[0])
    primary_water = runs[0]["water"]
    for other in runs[1:]:
        for key in ("water", "debris", "water_core", "already_changing"):
            merged[key] = merged[key] | other[key]
        merged["not_mapped"] = merged["not_mapped"] & other["not_mapped"]
        if "debris_before_pruning" in merged and "debris_before_pruning" in other:
            merged["debris_before_pruning"] = (merged["debris_before_pruning"]
                                               | other["debris_before_pruning"])
        if merged["no_flood"] is not None and other["no_flood"] is not None:
            merged["no_flood"] = {key: merged["no_flood"][key] | other["no_flood"][key]
                                  for key in ("water", "debris", "water_core")}
    merged["debris"] = merged["debris"] & ~merged["water"]
    # Water that only a secondary track saw (used to lower its confidence).
    merged["water_second_track_only"] = merged["water"] & ~primary_water
    merged["thresholds"] = [run["thresholds"] for run in runs]
    return merged
