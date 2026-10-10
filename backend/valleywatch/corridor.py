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


# pysheds stores a flow direction as one of these numbers; each maps to a
# (row, column) step: north, north-east, east, ... clockwise.
FLOW_STEPS = {64: (-1, 0), 128: (-1, 1), 1: (0, 1), 2: (1, 1),
              4: (1, 0), 8: (1, -1), 16: (0, -1), 32: (-1, -1)}


def _block_reduce(array, factor, reducer):
    """Reduce `factor` x `factor` blocks to one value (edges padded by repetition)."""
    rows, cols = array.shape
    pad_r, pad_c = (-rows) % factor, (-cols) % factor
    padded = np.pad(array, ((0, pad_r), (0, pad_c)), mode="edge")
    blocks = padded.reshape(padded.shape[0] // factor, factor,
                            padded.shape[1] // factor, factor)
    return reducer(blocks, axis=(1, 3))


def _to_full_grid(coarse_array, factor, shape):
    full = np.repeat(np.repeat(coarse_array, factor, axis=0), factor, axis=1)
    return full[:shape[0], :shape[1]]


def river_corridor(dem, transform, crs, settings):
    """Find the rivers and the valley floor beside them.

    Returns a dict with full-resolution 'hand' (metres above the river) and
    boolean 'corridor' and 'rivers', plus the coarse flow-routing arrays that
    `flood_path` needs.
    """
    pixel_m = abs(transform.a)
    # Work at the DEM's real 30 m resolution: the 10 m grid holds no extra
    # terrain detail and would only make flow routing nine times slower.
    factor = max(int(round(DEM_NATIVE_M / pixel_m)), 1)
    # The DEM has empty wedges along the box edges. They are set far BELOW
    # the terrain so that rivers can drain out of the box through them. (Set
    # high, they act as a dam: the valley behind fills into a fake lake and
    # the whole lake is then mistaken for valley floor.)
    filled = np.where(np.isfinite(dem), dem, np.nanmin(dem) - 1000.0).astype("float64")
    coarse = _block_reduce(filled, factor, np.mean)
    coarse_transform = transform * transform.scale(factor, factor)

    view = ViewFinder(affine=coarse_transform, shape=coarse.shape, crs=crs, nodata=-9999.0)
    raster = Raster(coarse, viewfinder=view)
    grid = Grid.from_raster(raster)
    # Remove small pits and flats (DEM noise) so every cell drains somewhere.
    conditioned = grid.resolve_flats(grid.fill_depressions(grid.fill_pits(raster)))
    flow_direction = grid.flowdir(conditioned)
    upstream_cells = grid.accumulation(flow_direction)
    cell_km2 = (pixel_m * factor) ** 2 / 1e6

    if settings.river_catchment_mode == "adaptive":
        largest_km2 = float(np.asarray(upstream_cells).max()) * cell_km2
        min_catchment_km2 = max(settings.river_fraction_of_largest * largest_km2,
                                settings.river_min_catchment_km2)
    else:
        min_catchment_km2 = settings.river_fixed_catchment_km2
    rivers = upstream_cells * cell_km2 >= min_catchment_km2

    hand = np.asarray(grid.compute_hand(flow_direction, conditioned, rivers), dtype="float32")
    # For every cell, the river cell its water ends up in (as a flat index).
    drains_to = np.asarray(grid.compute_hand(flow_direction, conditioned, rivers,
                                             return_index=True)).astype("int64")
    rivers = np.asarray(rivers)

    hand_full = _to_full_grid(hand, factor, dem.shape)
    corridor = (np.isfinite(hand_full) & (hand_full <= settings.corridor_max_hand_m)
                & np.isfinite(dem))
    return {"hand": hand_full, "corridor": corridor,
            "rivers": _to_full_grid(rivers, factor, dem.shape),
            "river_min_catchment_km2": round(min_catchment_km2, 1),
            "coarse": {"factor": factor, "rivers": rivers, "drains_to": drains_to,
                       "flow_direction": np.asarray(flow_direction)}}


def flood_path(corridor_info, seeds):
    """Ground that drains into a river reach downstream of a confident detection.

    A flood moves downstream without gaps. Starting from the river cells next
    to each confident patch (`seeds`, a full-resolution boolean array), we
    walk downstream to the edge of the box and mark every river cell passed.
    Ground draining into a marked cell is on the flood path. A side valley
    with only weak, isolated detections is never marked and is left out.
    """
    coarse = corridor_info["coarse"]
    factor, rivers = coarse["factor"], coarse["rivers"]
    drains_to, flow_direction = coarse["drains_to"], coarse["flow_direction"]
    rows, cols = rivers.shape
    in_grid = (drains_to >= 0) & (drains_to < rivers.size)

    seed_cells = _block_reduce(seeds, factor, np.max).astype(bool)
    start_cells = np.unique(drains_to[seed_cells & in_grid])

    marked = np.zeros(rivers.size, dtype=bool)
    for start in start_cells:
        row, col = divmod(int(start), cols)
        # Stop at the box edge, at a cell with no outflow, or where an
        # earlier walk already passed.
        while 0 <= row < rows and 0 <= col < cols and not marked[row * cols + col]:
            marked[row * cols + col] = True
            step = FLOW_STEPS.get(int(flow_direction[row, col]))
            if step is None:
                break
            row, col = row + step[0], col + step[1]

    on_path = np.zeros(rivers.shape, dtype=bool)
    on_path[in_grid] = marked[drains_to[in_grid]]
    return _to_full_grid(on_path, factor, seeds.shape)
