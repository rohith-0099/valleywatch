"""Step 3: Sentinel-2 optical check of the radar result.

Optical images see things radar cannot: vegetation stripped away by debris,
and muddy water. They also see into gorges where radar is blind. But they
need a clear sky, so this step works only where clear pixels exist both
before and after the event, and says so where they do not.
"""
import numpy as np
from skimage.morphology import remove_small_objects

from .flood_mask import CLASS_DEBRIS, CLASS_WATER

# Where each detected pixel's evidence comes from.
SOURCE_RADAR, SOURCE_BOTH, SOURCE_OPTICAL, SOURCE_RADAR_DISPUTED = 1, 2, 3, 4


def _ratio(a, b):
    total = a + b
    return np.where(total != 0, (a - b) / np.where(total != 0, total, 1), np.nan)


def optical_evidence(before, after, settings):
    """Per-pixel optical change between two cloud-free composites.

    before / after: dicts of reflectance arrays 'B03' (green), 'B04' (red),
    'B08' (near infrared) and 'B11' (short-wave infrared).
    """
    clear = np.ones(before["B04"].shape, dtype=bool)
    for image in (before, after):
        for band in image.values():
            clear &= np.isfinite(band) & (band > 0)

    # NDVI: plants reflect near infrared strongly and absorb red.
    ndvi_before = _ratio(before["B08"], before["B04"])
    ndvi_after = _ratio(after["B08"], after["B04"])
    # MNDWI: water is brighter in green than in short-wave infrared. It works
    # for muddy water better than indices that use near infrared.
    mndwi_before = _ratio(before["B03"], before["B11"])
    mndwi_after = _ratio(after["B03"], after["B11"])

    ndvi_fall = ndvi_before - ndvi_after
    vegetated_before = ndvi_before >= settings.ndvi_vegetated
    return {
        "clear": clear,
        # Green before, clearly less green after: stripped or buried.
        "vegetation_loss": clear & vegetated_before & (ndvi_fall >= settings.ndvi_drop),
        # Green before and still green after: nothing happened here.
        "vegetation_intact": clear & vegetated_before & (ndvi_fall < settings.ndvi_stable),
        # Water now, not water before.
        "new_water": clear & (mndwi_after > settings.water_index_min) &
                     (mndwi_before <= settings.water_index_min),
    }


def fuse_with_optical(result, evidence, pixel_m, settings):
    """Confirm, extend or down-weight the radar result with optical evidence.

    Changes result['classes'] and result['confidence'] in place and adds
    result['source'] (see SOURCE_* codes) and result['optical'] statistics.
    """
    classes, confidence, corridor = result["classes"], result["confidence"], result["corridor"]
    radar = classes > 0
    checked = evidence["clear"] & corridor
    optical_change = checked & (evidence["vegetation_loss"] | evidence["new_water"])

    source = np.zeros(classes.shape, dtype=np.uint8)
    source[radar] = SOURCE_RADAR

    # Confirm: radar and optical agree.
    confirmed = radar & optical_change
    confidence[confirmed] = np.minimum(confidence[confirmed] + settings.optical_confirm_bonus, 1.0)
    source[confirmed] = SOURCE_BOTH

    # Down-weight: radar reports a hit but the vegetation is visibly intact.
    # Bare ground gives optical no way to judge, so it is left alone.
    disputed = radar & checked & evidence["vegetation_intact"]
    confidence[disputed] *= settings.optical_disagree_factor
    source[disputed] = SOURCE_RADAR_DISPUTED

    # Extend: optical change on the valley floor that radar missed, typically
    # inside layover or shadow where radar cannot see at all.
    min_pixels = max(int(round(settings.optical_min_patch_m2 / pixel_m ** 2)), 1)
    extra_water = remove_small_objects(
        checked & evidence["new_water"] & ~radar, max_size=min_pixels - 1)
    extra_debris = remove_small_objects(
        checked & evidence["vegetation_loss"] & ~radar & ~extra_water, max_size=min_pixels - 1)
    classes[extra_water] = CLASS_WATER
    classes[extra_debris] = CLASS_DEBRIS
    added = extra_water | extra_debris
    confidence[added] = settings.optical_only_confidence
    source[added] = SOURCE_OPTICAL

    pixel_km2 = pixel_m ** 2 / 1e6
    corridor_pixels = max(int((corridor & result["has_data"]).sum()), 1)
    result["source"] = source
    result["optical"] = {
        "used": True,
        "corridor_clear_percent": round(100 * float(checked.sum()) / corridor_pixels, 1),
        "radar_confirmed_km2": round(float(confirmed.sum()) * pixel_km2, 3),
        "radar_disputed_km2": round(float(disputed.sum()) * pixel_km2, 3),
        "added_water_km2": round(float(extra_water.sum()) * pixel_km2, 3),
        "added_debris_km2": round(float(extra_debris.sum()) * pixel_km2, 3),
    }
    return result
