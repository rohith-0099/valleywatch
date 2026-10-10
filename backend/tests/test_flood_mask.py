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
    classes = np.zeros(shape, dtype=np.uint8)
    classes[out["debris"]] = CLASS_DEBRIS
    classes[out["water"]] = CLASS_WATER
    assert (classes[25:55, 25:55] == CLASS_WATER).mean() > 0.95
    assert (classes[105:135, 105:135] == CLASS_DEBRIS).mean() > 0.95
    assert (classes[:, 181:189] != 0).sum() == 0
    assert (classes[155:185, 25:55] != 0).sum() == 0
    assert (classes[20:60, 100:140] != 0).sum() == 0
    # Background stays clean.
    assert (classes[60:100, 20:80] != 0).mean() < 0.01


def test_debris_already_changing_before_flood_is_dropped():
    rng = np.random.default_rng(1)
    shape = (120, 120)
    make = lambda: {"VV": _scene(shape, rng, -9), "VH": _scene(shape, rng, -15)}
    baseline, before, after = make(), make(), make()
    # Two equal debris patches appear after the flood ...
    for rows in (slice(10, 40), slice(70, 100)):
        after["VV"][rows, 10:40] *= 6.3
    # ... but the second patch was already changing before the flood.
    baseline["VV"][70:100, 10:40] *= 0.1
    settings = Settings()
    terrain = terrain_mask(np.zeros(shape), 10.0, "ASCENDING", settings)
    out = detect_flood_and_debris(before, after, terrain, np.ones(shape, bool), 10.0,
                                  settings, baseline=baseline)
    assert out["debris"][15:35, 15:35].mean() > 0.95
    assert out["debris"][75:95, 15:35].mean() < 0.05
    assert out["no_flood"]["debris"][75:95, 15:35].mean() > 0.95


def test_flood_path_keeps_downstream_and_drops_side_valley():
    from rasterio.transform import from_origin
    from valleywatch.corridor import flood_path, river_corridor
    # A main valley running north to south, with one side valley from the east.
    rows, cols = 300, 300
    y, x = np.mgrid[0:rows, 0:cols].astype(float)
    main = np.abs(x - 100) * 3.0 + (rows - y) * 1.0
    side = np.abs(y - 150) * 3.0 + (x - 100) * 1.0 + (rows - 150) * 1.0
    dem = np.where(x > 100, np.minimum(main, side), main)
    settings = Settings()
    settings.river_catchment_mode, settings.river_fixed_catchment_km2 = "fixed", 0.3
    info = river_corridor(dem, from_origin(0, rows * 10, 10, 10), "EPSG:32645", settings)
    seeds = np.zeros(dem.shape, dtype=bool)
    seeds[100:106, 97:103] = True          # confident change in the main valley
    path = flood_path(info, seeds)
    assert path[250, 100]                  # downstream on the main river: kept
    assert not path[40, 100]               # upstream of the seed: dropped
    assert not path[150, 220]              # side valley without a seed: dropped
