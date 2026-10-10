"""Final clean-up of the class map: flood-path filter and confidence."""
import numpy as np
from skimage.morphology import remove_small_objects

from .corridor import flood_path
from .flood_mask import CLASS_DEBRIS, CLASS_WATER
from .optical import SOURCE_BOTH, SOURCE_OPTICAL, SOURCE_RADAR, SOURCE_RADAR_DISPUTED


def confident_seeds(mask, pixel_m, min_area_m2):
    """Keep only patches of `mask` large enough to be trusted as flood evidence."""
    seed_pixels = max(int(round(min_area_m2 / pixel_m ** 2)), 1)
    return remove_small_objects(mask, max_size=seed_pixels - 1)


def keep_flood_path(result, corridor_info, pixel_m, settings):
    """Drop detections that are not on a river reach downstream of confident change.

    Confident change = radar and optical agreeing, the confident heart of a
    radar water patch, or a large optical-only patch (for gorges where radar
    is blind). Radar-only debris is too noisy to start a path.
    """
    seeds = confident_seeds((result["source"] == SOURCE_BOTH) | result["water_core"],
                            pixel_m, settings.seed_min_area_m2)
    seeds |= confident_seeds(result["source"] == SOURCE_OPTICAL, pixel_m,
                             settings.optical_seed_min_area_m2)
    path = flood_path(corridor_info, seeds)
    off_path = (result["classes"] > 0) & ~path
    result["classes"][off_path] = 0
    result["source"][off_path] = 0
    result["flood_path"] = path
    return result


def score_confidence(result, settings):
    """Confidence from how many independent sources agree.

        radar and optical agree            high
        optical only                       medium
        radar-only water, sky not clear    medium (optical could not check)
        radar-only water, optical saw none low
        radar-only debris                  low
        radar disputed by optical          low

    Ground that was already changing before the flood loses a step.
    """
    classes, source = result["classes"], result["source"]
    score = np.zeros(classes.shape, dtype=np.float32)
    radar_only = np.isin(source, (SOURCE_RADAR, SOURCE_RADAR_DISPUTED))
    score[radar_only] = settings.score_radar_only
    unchecked_water = (source == SOURCE_RADAR) & (classes == CLASS_WATER) & ~result["checked"]
    score[unchecked_water] = settings.score_radar_water_unchecked
    score[source == SOURCE_OPTICAL] = settings.score_optical_only
    score[source == SOURCE_BOTH] = settings.score_radar_and_optical
    penalised = (classes > 0) & result["already_changing"]
    score[penalised] = np.maximum(score[penalised] - settings.score_already_changing_penalty, 0.1)
    result["confidence"] = score
    return result


def radar_only_areas(water, debris, water_core, corridor_info, pixel_m, settings):
    """Area (km2) of radar water and debris left after the flood-path filter.

    Used for the acceptance test: the same call on the flood pair and on the
    no-flood pair shows how much of the radar result is real.
    """
    path = flood_path(corridor_info, confident_seeds(water_core, pixel_m, settings.seed_min_area_m2))
    pixel_km2 = pixel_m ** 2 / 1e6
    return {"water_km2": round(float((water & path).sum()) * pixel_km2, 3),
            "debris_km2": round(float((debris & ~water & path).sum()) * pixel_km2, 3),
            "water_km2_before_path_filter": round(float(water.sum()) * pixel_km2, 3),
            "debris_km2_before_path_filter": round(float((debris & ~water).sum()) * pixel_km2, 3)}


def optical_only_areas(evidence, common_clear, corridor, corridor_info, pixel_m, settings):
    """Area (km2) the optical rules alone would map, after the flood-path filter.

    Used for the optical acceptance test. `common_clear` limits the count to
    ground that is clear in every composite compared, so that the flood pair
    and the no-flood pair are judged on exactly the same pixels.
    """
    judged = common_clear & corridor
    min_pixels = max(int(round(settings.optical_min_patch_m2 / pixel_m ** 2)), 1)
    water = remove_small_objects(judged & evidence["new_water"], max_size=min_pixels - 1)
    debris = remove_small_objects(judged & evidence["vegetation_loss"] & ~water,
                                  max_size=min_pixels - 1)
    seeds = confident_seeds(water | debris, pixel_m, settings.optical_seed_min_area_m2)
    path = flood_path(corridor_info, seeds)
    pixel_km2 = pixel_m ** 2 / 1e6
    return {"water_km2": round(float((water & path).sum()) * pixel_km2, 3),
            "debris_km2": round(float((debris & path).sum()) * pixel_km2, 3),
            "water_km2_before_path_filter": round(float(water.sum()) * pixel_km2, 3),
            "debris_km2_before_path_filter": round(float(debris.sum()) * pixel_km2, 3)}
