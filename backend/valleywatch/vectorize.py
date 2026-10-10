"""Convert the class raster into GeoJSON polygons for the map."""
import geopandas as gpd
import numpy as np
from rasterio import features
from scipy import ndimage
from shapely.geometry import shape

from .flood_mask import CLASS_DEBRIS, CLASS_WATER
from .optical import SOURCE_BOTH, SOURCE_OPTICAL, SOURCE_RADAR_DISPUTED

CLASS_NAMES = {CLASS_WATER: "water", CLASS_DEBRIS: "debris"}


def confidence_level(value):
    if value >= 0.75:
        return "high"
    return "medium" if value >= 0.45 else "low"


def source_label(optical_share, both_share, disputed_share):
    """Name the evidence behind a polygon from its pixel shares."""
    if optical_share > 0.5:
        return "optical"
    if both_share + optical_share >= 0.3:
        return "radar+optical"
    if disputed_share >= 0.5:
        return "radar (optical disagrees)"
    return "radar"


def masks_to_polygons(classes, confidence, change_vv_db, source, transform, crs):
    """One polygon per connected patch, with area, confidence and evidence.

    Returned in WGS84 (EPSG:4326), which is what GeoJSON and web maps expect.
    """
    rows = []
    for class_id, name in CLASS_NAMES.items():
        mask = classes == class_id
        if not mask.any():
            continue
        # 8-connected labels so a patch and its polygon match one to one.
        labels, count = ndimage.label(mask, structure=np.ones((3, 3)))
        index = np.arange(1, count + 1)
        mean_conf = ndimage.mean(confidence, labels, index)
        mean_change = ndimage.mean(np.nan_to_num(change_vv_db), labels, index)
        pixels = ndimage.sum(mask, labels, index)
        share = {code: ndimage.mean(source == code, labels, index)
                 for code in (SOURCE_BOTH, SOURCE_OPTICAL, SOURCE_RADAR_DISPUTED)}
        pixel_area = abs(transform.a * transform.e)
        for geometry, label in features.shapes(labels.astype(np.int32), mask=mask,
                                               transform=transform, connectivity=8):
            i = int(label) - 1
            rows.append({
                "geometry": shape(geometry), "hazard": name,
                "area_m2": round(float(pixels[i]) * pixel_area, 1),
                "confidence": round(float(mean_conf[i]), 2),
                "confidence_level": confidence_level(float(mean_conf[i])),
                "source": source_label(float(share[SOURCE_OPTICAL][i]),
                                       float(share[SOURCE_BOTH][i]),
                                       float(share[SOURCE_RADAR_DISPUTED][i])),
                "mean_change_vv_db": round(float(mean_change[i]), 2),
            })
    columns = ["geometry", "hazard", "area_m2", "confidence",
               "confidence_level", "source", "mean_change_vv_db"]
    frame = gpd.GeoDataFrame(rows, columns=columns, geometry="geometry", crs=crs)
    return frame.to_crs(4326)
