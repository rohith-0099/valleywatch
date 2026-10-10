"""River corridor from the Copernicus DEM.

Flood water and debris move along the valley floor. We find the valley floor
with a standard terrain measure called HAND (Height Above Nearest Drainage):

1. route water downhill over the DEM, cell by cell;
2. cells that collect water from a large area are the river network;
3. HAND of a cell = its height above the river cell it drains into.

Ground with a small HAND is the corridor. Only the DEM is used; no river or
surface-water dataset is involved.
"""
import numpy as np
from pysheds.grid import Grid
from pysheds.view import Raster, ViewFinder

DEM_NATIVE_M = 30.0  # true resolution of the Copernicus DEM


def _block_mean(array, factor):
    """Average `factor` x `factor` blocks (edges are padded by repetition)."""
    rows, cols = array.shape
    pad_r, pad_c = (-rows) % factor, (-cols) % factor
    padded = np.pad(array, ((0, pad_r), (0, pad_c)), mode="edge")
    blocks = padded.reshape(padded.shape[0] // factor, factor,
                            padded.shape[1] // factor, factor)
    return blocks.mean(axis=(1, 3))


def river_corridor(dem, transform, crs, settings):
    """Return {'hand': metres above the river, 'corridor': bool, 'rivers': bool}."""
    pixel_m = abs(transform.a)
    # Work at the DEM's real 30 m resolution: the 10 m grid holds no extra
    # terrain detail and would only make flow routing nine times slower.
    factor = max(int(round(DEM_NATIVE_M / pixel_m)), 1)
    # Missing cells become high ground so that water flows around them.
    filled = np.where(np.isfinite(dem), dem, np.nanmax(dem)).astype("float64")
    coarse = _block_mean(filled, factor)
    coarse_transform = transform * transform.scale(factor, factor)

    view = ViewFinder(affine=coarse_transform, shape=coarse.shape, crs=crs, nodata=-9999.0)
    raster = Raster(coarse, viewfinder=view)
    grid = Grid.from_raster(raster)
    # Remove small pits and flats (DEM noise) so every cell drains somewhere.
    conditioned = grid.resolve_flats(grid.fill_depressions(grid.fill_pits(raster)))
    flow_direction = grid.flowdir(conditioned)
    upstream_cells = grid.accumulation(flow_direction)
    cell_km2 = (pixel_m * factor) ** 2 / 1e6
    rivers = upstream_cells * cell_km2 >= settings.river_min_catchment_km2
    hand = np.asarray(grid.compute_hand(flow_direction, conditioned, rivers), dtype="float32")
    rivers = np.asarray(rivers)

    def to_full_grid(coarse_array):
        full = np.repeat(np.repeat(coarse_array, factor, axis=0), factor, axis=1)
        return full[:dem.shape[0], :dem.shape[1]]

    hand = to_full_grid(hand)
    corridor = np.isfinite(hand) & (hand <= settings.corridor_max_hand_m) & np.isfinite(dem)
    return {"hand": hand, "corridor": corridor, "rivers": to_full_grid(rivers)}
