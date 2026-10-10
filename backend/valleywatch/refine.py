"""Turn radar and optical evidence into the final map, and test it.

`fused_map` is the one place where the final class map is built. It is run
twice with identical rules: on the flood pair, and on a pair of images from
before the flood. The second run should find almost nothing; whatever it
does find is our false-alarm level (see `acceptance_test`).
"""
import numpy as np
from scipy import ndimage
from skimage.morphology import remove_small_objects

from .corridor import flood_path
from .flood_mask import CLASS_DEBRIS, CLASS_WATER
from .optical import (SOURCE_BOTH, SOURCE_OPTICAL, SOURCE_RADAR, SOURCE_RADAR_DISPUTED,
                      combine_radar_and_optical)


def confident_seeds(mask, pixel_m, min_area_m2):
    """Keep only patches of `mask` large enough to be trusted as flood evidence."""
    seed_pixels = max(int(round(min_area_m2 / pixel_m ** 2)), 1)
    return remove_small_objects(mask, max_size=seed_pixels - 1)


def grown_from_core(detected, corridor):
    """Keep detection patches that reach the valley floor.

    A patch may spread up the valley side (the reach zone), but only as one
    connected area of change that starts in the core corridor. Change that
    sits on the valley side with no link to the floor is dropped.
    """
    labels, _ = ndimage.label(detected, structure=np.ones((3, 3)))
    rooted = np.unique(labels[detected & corridor])
    return np.isin(labels, rooted[rooted > 0])


def fused_map(water, debris, water_core, evidence, zones, pixel_m, settings):
    """Final class map from radar masks and (optional) optical evidence.

    Steps: combine the sources; keep patches grown from the valley floor;
    keep only ground draining into a river reach downstream of confident
    change. Returns {'classes', 'source', 'checked', 'flood_path'}.
    """
    out = combine_radar_and_optical(water, debris, evidence, zones["reach"], pixel_m, settings)
    classes, source = out["classes"], out["source"]

    keep = grown_from_core(classes > 0, zones["corridor"])
    # Confident change: radar and optical agreeing, the confident heart of a
    # radar water patch, or a large optical-only patch (for gorges where
    # radar is blind). Radar-only debris is too noisy to start a path.
    seeds = confident_seeds(((source == SOURCE_BOTH) | water_core) & keep,
                            pixel_m, settings.seed_min_area_m2)
    seeds |= confident_seeds((source == SOURCE_OPTICAL) & keep, pixel_m,
                             settings.optical_seed_min_area_m2)
    path = flood_path(zones, seeds)
    keep &= path
    classes[~keep] = 0
    source[~keep] = 0
    out["flood_path"] = path
    return out


def score_confidence(classes, source, checked, already_changing, settings):
    """Confidence from how many independent sources agree.

        radar and optical agree            high
        optical only                       medium
        radar-only water, sky not clear    medium (optical could not check)
        radar-only water, optical saw none low
        radar-only debris                  low
        radar disputed by optical          low

    Ground that was already changing before the flood loses a step.
    """
    score = np.zeros(classes.shape, dtype=np.float32)
    radar_only = np.isin(source, (SOURCE_RADAR, SOURCE_RADAR_DISPUTED))
    score[radar_only] = settings.score_radar_only
    unchecked_water = (source == SOURCE_RADAR) & (classes == CLASS_WATER) & ~checked
    score[unchecked_water] = settings.score_radar_water_unchecked
    score[source == SOURCE_OPTICAL] = settings.score_optical_only
    score[source == SOURCE_BOTH] = settings.score_radar_and_optical
    penalised = (classes > 0) & already_changing
    score[penalised] = np.maximum(score[penalised] - settings.score_already_changing_penalty, 0.1)
    return score


def _areas(fused, pixel_m):
    """Mapped area by class, and by class and evidence source."""
    classes, source = fused["classes"], fused["source"]
    pixel_km2 = pixel_m ** 2 / 1e6
    out = {"water_km2": round(float((classes == CLASS_WATER).sum()) * pixel_km2, 3),
           "debris_km2": round(float((classes == CLASS_DEBRIS).sum()) * pixel_km2, 3)}
    names = {SOURCE_RADAR: "radar", SOURCE_RADAR_DISPUTED: "radar", SOURCE_BOTH: "both",
             SOURCE_OPTICAL: "optical"}
    detail = {}
    for class_id, label in ((CLASS_WATER, "water"), (CLASS_DEBRIS, "debris")):
        for code, name in names.items():
            key = f"{label}_{name}_km2"
            detail[key] = detail.get(key, 0.0) + float(
                ((classes == class_id) & (source == code)).sum()) * pixel_km2
    out["by_source"] = {k: round(v, 3) for k, v in detail.items()}
    return out


def acceptance_test(radar, evidence, quiet_evidence, zones, pixel_m, settings):
    """Run the identical rules on the flood pair and on a no-flood pair.

    radar: merged radar result (holds the no-flood radar masks, if a
    baseline image was available). evidence / quiet_evidence: optical
    evidence for the flood pair and for two composites from before the
    flood. Optical is compared only on ground clear in all three composites
    so both pairs are judged on the same pixels.
    """
    quiet_radar = radar["no_flood"]
    if quiet_radar is None and quiet_evidence is None:
        return {"not_run": "no pre-event radar pass and no earlier optical composite"}

    empty = np.zeros(zones["reach"].shape, dtype=bool)
    if evidence is not None and quiet_evidence is not None:
        common = evidence["clear"] & quiet_evidence["clear"]
        flood_ev = dict(evidence, clear=common)
        quiet_ev = dict(quiet_evidence, clear=common)
    else:
        flood_ev = quiet_ev = None

    # The flood side uses debris BEFORE baseline pruning: the no-flood side
    # has no still-earlier image to prune with, and the two must match.
    flood_debris = radar.get("debris_before_pruning", radar["debris"])
    if quiet_radar is None:  # optical-only comparison
        flood = fused_map(empty, empty, empty, flood_ev, zones, pixel_m, settings)
        quiet = fused_map(empty, empty, empty, quiet_ev, zones, pixel_m, settings)
        compared = "optical only (no pre-event radar pass)"
    else:
        flood = fused_map(radar["water"], flood_debris, radar["water_core"], flood_ev,
                          zones, pixel_m, settings)
        quiet = fused_map(quiet_radar["water"], quiet_radar["debris"],
                          quiet_radar["water_core"], quiet_ev, zones, pixel_m, settings)
        compared = ("radar and optical" if flood_ev is not None
                    else "radar only (no earlier optical composite)")

    flood_areas, quiet_areas = _areas(flood, pixel_m), _areas(quiet, pixel_m)
    flood_total = flood_areas["water_km2"] + flood_areas["debris_km2"]
    quiet_total = quiet_areas["water_km2"] + quiet_areas["debris_km2"]

    def share(part, whole):
        return round(100 * part / whole, 1) if whole else None

    total_share = share(quiet_total, flood_total)
    return {
        "compared": compared,
        "flood_pair": flood_areas, "no_flood_pair": quiet_areas,
        "no_flood_as_percent_of_flood": {
            "water": share(quiet_areas["water_km2"], flood_areas["water_km2"]),
            "debris": share(quiet_areas["debris_km2"], flood_areas["debris_km2"]),
            "total": total_share},
        "budget_percent": 100 * settings.false_alarm_budget,
        "within_budget": (total_share is not None
                          and total_share <= 100 * settings.false_alarm_budget),
    }
