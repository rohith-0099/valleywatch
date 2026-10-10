"""Synthetic checks of the classification rules (no network needed)."""
import numpy as np

from valleywatch.config import Settings
from valleywatch.flood_mask import CLASS_DEBRIS, CLASS_WATER, detect_flood_and_debris
from valleywatch.terrain import terrain_mask


def _scene(shape, rng, level_db):
    speckle = rng.gamma(4.4, 1 / 4.4, shape)
    return 10 ** (level_db / 10) * speckle


def test_water_debris_and_masks():
    rng = np.random.default_rng(0)
    shape = (200, 200)
    before = {"VV": _scene(shape, rng, -9), "VH": _scene(shape, rng, -15)}
    after = {"VV": _scene(shape, rng, -9), "VH": _scene(shape, rng, -15)}
    # New water: both bands drop by 10 dB.
    after["VV"][20:60, 20:60] *= 0.1
    after["VH"][20:60, 20:60] *= 0.1
    # Debris: VV rises by 8 dB over a large patch.
    after["VV"][100:140, 100:140] *= 6.3
    # Permanent river: dark in both images, must not be reported.
    for image in (before, after):
        image["VV"][:, 180:190] = 10 ** (-22 / 10)
        image["VH"][:, 180:190] = 10 ** (-28 / 10)
    # A flooded-looking patch on a very steep slope must be masked out.
    after["VV"][150:190, 20:60] *= 0.1
    after["VH"][150:190, 20:60] *= 0.1
    dem = np.zeros(shape)
    dem[140:200, 0:80] = np.arange(60)[:, None] * 10.0 * 1.5  # 56 degree slope
    # A strong change outside the river corridor must be ignored.
    after["VV"][20:60, 100:140] *= 0.1
    after["VH"][20:60, 100:140] *= 0.1
    corridor = np.ones(shape, dtype=bool)
    corridor[0:80, 90:150] = False

    settings = Settings()
    terrain = terrain_mask(dem, 10.0, "ASCENDING", settings)
    out = detect_flood_and_debris(before, after, terrain, corridor, 10.0, settings)
    classes = out["classes"]
    assert (classes[25:55, 25:55] == CLASS_WATER).mean() > 0.95
    assert (classes[105:135, 105:135] == CLASS_DEBRIS).mean() > 0.95
    assert (classes[:, 181:189] != 0).sum() == 0
    assert (classes[155:185, 25:55] != 0).sum() == 0
    assert (classes[20:60, 100:140] != 0).sum() == 0
    # Background stays clean.
    assert (classes[60:100, 20:80] != 0).mean() < 0.01


def test_baseline_lowers_confidence_where_already_changing():
    rng = np.random.default_rng(1)
    shape = (120, 120)
    make = lambda: {"VV": _scene(shape, rng, -9), "VH": _scene(shape, rng, -15)}
    baseline, before, after = make(), make(), make()
    # Two equal water patches appear after the flood ...
    for rows in (slice(10, 40), slice(70, 100)):
        after["VV"][rows, 10:40] *= 0.1
        after["VH"][rows, 10:40] *= 0.1
    # ... but the second patch was already changing before the flood.
    baseline["VV"][70:100, 10:40] *= 8
    baseline["VH"][70:100, 10:40] *= 8
    settings = Settings()
    terrain = terrain_mask(np.zeros(shape), 10.0, "ASCENDING", settings)
    out = detect_flood_and_debris(before, after, terrain, np.ones(shape, bool), 10.0,
                                  settings, baseline=baseline)
    steady = out["confidence"][15:35, 15:35].mean()
    unsteady = out["confidence"][75:95, 15:35].mean()
    assert unsteady < 0.7 * steady
    assert out["baseline"]["detections_down_weighted_km2"] > 0
