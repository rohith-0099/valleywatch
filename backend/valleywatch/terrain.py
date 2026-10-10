"""Terrain masks from the Copernicus DEM.

In mountains a side-looking radar has blind spots:

* shadow   - slopes facing away from the satellite get no signal and look
             black, exactly like calm water;
* layover  - slopes facing the satellite are so steep that summit and foot
             fall into the same pixel, so the brightness there is meaningless.

Neither zone can be mapped, so we exclude them instead of guessing. We also
exclude steep ground, because flood water cannot pond on it.
"""
import numpy as np
from scipy import ndimage

# Sentinel-1 always looks to the right of its flight direction. Its heading
# is about 348 deg when ascending and 192 deg when descending, so the radar
# beam travels towards these compass bearings.
LOOK_AZIMUTH_DEG = {"ASCENDING": 78.0, "DESCENDING": 282.0}


def slope_and_range_slope(dem, pixel_m, direction):
    """Return (slope, slope along the radar look direction), both in degrees.

    The second value is positive where the ground rises away from the radar,
    i.e. where the slope faces the satellite.
    """
    # Rows run north to south, so the row gradient is negated to get d/dNorth.
    d_row, d_col = np.gradient(dem, pixel_m)
    d_north, d_east = -d_row, d_col
    slope = np.degrees(np.arctan(np.hypot(d_east, d_north)))
    azimuth = np.radians(LOOK_AZIMUTH_DEG[direction.upper()])
    along_look = d_east * np.sin(azimuth) + d_north * np.cos(azimuth)
    return slope, np.degrees(np.arctan(along_look))


def terrain_mask(dem, pixel_m, direction, settings):
    """Boolean arrays for pixels that must not be classified.

    Returns a dict with 'slope' (degrees) and the boolean masks 'steep',
    'layover', 'shadow', 'blind' (layover or shadow or no DEM) and 'any'.
    """
    slope, range_slope = slope_and_range_slope(dem, pixel_m, direction)
    theta = settings.incidence_angle_deg
    margin = settings.geometry_margin_deg
    steep = slope > settings.max_slope_deg
    # Layover: the slope facing the radar is steeper than the incidence angle.
    layover = range_slope > (theta - margin)
    # Shadow: the slope facing away is steeper than the beam's grazing angle.
    shadow = -range_slope > (90.0 - theta - margin)
    # Grow the blind zones a little: the DEM is 30 m, the radar pixel 10 m.
    grow = ndimage.generate_binary_structure(2, 2)
    layover = ndimage.binary_dilation(layover, grow, iterations=2)
    shadow = ndimage.binary_dilation(shadow, grow, iterations=2)
    invalid = ~np.isfinite(dem)
    blind = layover | shadow | invalid
    return {"slope": slope, "steep": steep, "layover": layover, "shadow": shadow,
            "blind": blind, "any": steep | blind}
