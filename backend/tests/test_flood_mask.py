"""Synthetic checks of the classification rules (no network needed)."""
import numpy as np

from valleywatch.config import Settings
from valleywatch.flood_mask import CLASS_DEBRIS, CLASS_WATER, detect_flood_and_debris


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
    # Debris: VV rises by 8 dB.
    after["VV"][100:140, 100:140] *= 6.3
    # Permanent river: dark in both images, must not be reported.
    for image in (before, after):
        image["VV"][:, 180:190] = 10 ** (-22 / 10)
        image["VH"][:, 180:190] = 10 ** (-28 / 10)
    # A flooded-looking patch on a steep slope must be masked out.
    after["VV"][150:190, 20:60] *= 0.1
    after["VH"][150:190, 20:60] *= 0.1
    dem = np.zeros(shape)
    dem[140:200, 0:80] = np.arange(60)[:, None] * 10.0 * 1.0  # 45 degree slope

    out = detect_flood_and_debris(before, after, dem, 10.0, "ASCENDING", Settings())
    classes = out["classes"]
    assert (classes[25:55, 25:55] == CLASS_WATER).mean() > 0.95
    assert (classes[105:135, 105:135] == CLASS_DEBRIS).mean() > 0.95
    assert (classes[:, 181:189] != 0).sum() == 0
    assert (classes[155:185, 25:55] != 0).sum() == 0
    # Background stays clean.
    assert (classes[60:100, 60:100] != 0).mean() < 0.01
