"""Step 3: Sentinel-2 optical check of the radar result.

Optical images see things radar cannot: vegetation stripped away by debris,
and muddy water. They also see into gorges where radar is blind. But they
need a clear sky, so this step works only where clear pixels exist both
before and after the event, and says so where they do not.
"""
import numpy as np
from scipy import ndimage
from skimage.morphology import remove_small_objects

from .flood_mask import CLASS_DEBRIS, CLASS_WATER

# Where each detected pixel's evidence comes from.
SOURCE_RADAR, SOURCE_BOTH, SOURCE_OPTICAL, SOURCE_RADAR_DISPUTED = 1, 2, 3, 4


def _ratio(a, b):
    total = a + b
    return np.where(total != 0, (a - b) / np.where(total != 0, total, 1), np.nan)


def optical_evidence(before, after, settings):
    """Per-pixel optical change between two cloud-free composites.

    before / after: dicts of arrays 'B03' (green), 'B04' (red), 'B08' (near
    infrared) and 'B11' (short-wave infrared).
    """
    scale = settings.s2_reflectance_scale
    before = {name: band / scale for name, band in before.items()}
    after = {name: band / scale for name, band in after.items()}
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
    # Shadow test. A cloud or mountain shadow darkens every band and lowers
    # NDVI just like lost vegetation. Fresh sediment is bright in the two
    # infrared bands, so we require the after pixel to be bright there.
    bright_after = ((after["B08"] >= settings.shadow_max_reflectance) &
                    (after["B11"] >= settings.shadow_max_reflectance))
    new_water = (clear & (mndwi_after > settings.water_index_min) &
                 (mndwi_before <= settings.water_index_min) &
                 (after["B03"] >= settings.water_green_min))
    return {
        "clear": clear,
        # Green before; afterwards bare (not merely less green) and not in
        # shadow: stripped or buried by the flood.
        "vegetation_loss": (clear & vegetated_before & bright_after &
                            (ndvi_fall >= settings.ndvi_drop) &
                            (ndvi_after <= settings.ndvi_bare_max)),
        # Green before and still green after: nothing happened here.
        "vegetation_intact": clear & vegetated_before & (ndvi_fall < settings.ndvi_stable),
        # Bright water now, not water before.
        "new_water": new_water,
    }


def combine_radar_and_optical(water, debris, evidence, reach, pixel_m, settings):
    """Build the class map from radar, and from optical where it is clear.

    water / debris: radar masks. evidence: output of optical_evidence, or
    None for a radar-only map. reach: zone in which detections may lie.
    Returns {'classes', 'source' (see SOURCE_* codes), 'checked' (pixels
    optical could judge)}.
    """
    classes = np.zeros(reach.shape, dtype=np.uint8)
    classes[debris] = CLASS_DEBRIS
    classes[water] = CLASS_WATER
    radar = classes > 0
    source = np.where(radar, SOURCE_RADAR, 0).astype(np.uint8)
    if evidence is None:
        return {"classes": classes, "source": source,
                "checked": np.zeros(reach.shape, dtype=bool)}

    checked = evidence["clear"] & reach
    optical_change = checked & (evidence["vegetation_loss"] | evidence["new_water"])

    # Agreement: radar and optical both see change here.
    source[radar & optical_change] = SOURCE_BOTH
    # Dispute: radar reports a hit but the vegetation is visibly intact.
    # Bare ground gives optical no way to judge, so it is not a dispute.
    source[radar & checked & evidence["vegetation_intact"]] = SOURCE_RADAR_DISPUTED

    # Optical only: change that radar missed, typically inside layover or
    # shadow where radar cannot see at all.
    min_pixels = max(int(round(settings.optical_min_patch_m2 / pixel_m ** 2)), 1)
    extra_debris = remove_small_objects(
        checked & evidence["vegetation_loss"] & ~radar, max_size=min_pixels - 1)

    # Optical-only water is off by default (see `optical_water_alone` in the
    # settings for the evidence). When switched on, a patch must at least
    # touch radar change or optical debris: a flood leaves debris or radar
    # change beside its new water, seasonal river widening does not.
    extra_water = np.zeros(reach.shape, dtype=bool)
    if settings.optical_water_alone:
        candidate_water = remove_small_objects(
            checked & evidence["new_water"] & ~radar & ~extra_debris, max_size=min_pixels - 1)
        support = ndimage.binary_dilation(radar | extra_debris, np.ones((3, 3)), iterations=2)
        labels, _ = ndimage.label(candidate_water, structure=np.ones((3, 3)))
        supported = np.unique(labels[support & candidate_water])
        extra_water = np.isin(labels, supported[supported > 0])

    classes[extra_debris] = CLASS_DEBRIS
    classes[extra_water] = CLASS_WATER
    source[extra_water | extra_debris] = SOURCE_OPTICAL
    return {"classes": classes, "source": source, "checked": checked}
