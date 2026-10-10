"""Quick-look PNG so a person can check the result by eye."""
import matplotlib
matplotlib.use("Agg")  # draw to file, no display needed
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import ListedColormap
from matplotlib.patches import Patch

from .flood_mask import CLASS_DEBRIS, CLASS_WATER

WATER_COLOUR, DEBRIS_COLOUR, MASK_COLOUR = "#00b7ff", "#ff7a00", "#555555"


def save_quicklook(result, extent, path, title):
    """Four panels: before, after, change, and the final classification."""
    fig, axes = plt.subplots(1, 4, figsize=(26, 10), constrained_layout=True)
    grey = dict(cmap="gray", vmin=-22, vmax=-2, extent=extent, interpolation="nearest")

    axes[0].imshow(result["before_vv_db"], **grey)
    axes[0].set_title("Before: VV backscatter (dB)")
    axes[1].imshow(result["after_vv_db"], **grey)
    axes[1].set_title("After: VV backscatter (dB)")

    change = axes[2].imshow(result["change_vv_db"], cmap="RdBu", vmin=-8, vmax=8,
                            extent=extent, interpolation="nearest")
    axes[2].set_title("Change after - before, VV (dB)\nblue = brighter, red = darker")
    fig.colorbar(change, ax=axes[2], shrink=0.5)

    axes[3].imshow(result["after_vv_db"], **grey)
    blocked = np.where(result["terrain"]["any"], 1.0, np.nan)
    axes[3].imshow(blocked, cmap=ListedColormap([MASK_COLOUR]), alpha=0.55,
                   extent=extent, interpolation="nearest")
    for class_id, colour in ((CLASS_DEBRIS, DEBRIS_COLOUR), (CLASS_WATER, WATER_COLOUR)):
        layer = np.where(result["classes"] == class_id, 1.0, np.nan)
        axes[3].imshow(layer, cmap=ListedColormap([colour]), extent=extent,
                       interpolation="nearest")
    axes[3].set_title("Result on the after image")
    axes[3].legend(handles=[
        Patch(color=WATER_COLOUR, label="New water (backscatter drop)"),
        Patch(color=DEBRIS_COLOUR, label="Debris (backscatter rise)"),
        Patch(color=MASK_COLOUR, alpha=0.55, label="Not mapped: steep / shadow / layover"),
    ], loc="lower left", fontsize=9)

    for axis in axes:
        axis.set_xlabel("UTM easting (m)")
        axis.ticklabel_format(style="plain")
    axes[0].set_ylabel("UTM northing (m)")
    fig.suptitle(title + "\nContains modified Copernicus Sentinel data. "
                 "Educational prototype, not an operational product.", fontsize=12)
    fig.savefig(path, dpi=130)
    plt.close(fig)
    return path
