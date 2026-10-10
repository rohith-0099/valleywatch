"""Figure for the report: our map against the EMSR927 reference, area by area.

This reads Copernicus EMS products, so it lives in the validation package and
is never imported by the pipeline.

    python -m validation.figures --run ../outputs/<run folder> --out ../docs/figures

Attribution: European Union, Copernicus Emergency Management Service data.
"""
import argparse
import json
from pathlib import Path

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from shapely.geometry import box

from .emsr927 import ATTRIBUTION, _layer, _read_run_layer, download_reference

# Colour-blind-safe trio, checked with the palette validator.
AGREE, OURS_ONLY, MISSED = "#2a78d6", "#eb6834", "#1baf7a"
INK, MUTED = "#0b0b0b", "#52514e"


def overlay_figure(run, activation, reference_folder, out_path, products=("AOI01", "AOI03_GRA_MONIT01")):
    run = Path(run)
    summary = json.loads((run / "summary.json").read_text())
    crs = summary["grid"]["crs"]
    run_box = gpd.GeoSeries([box(*summary["inputs"]["bbox_west_south_east_north"])],
                            crs=4326).to_crs(crs).iloc[0]
    ours = _read_run_layer(run, "flood_debris", crs).union_all()

    chosen = [p for p in download_reference(activation, reference_folder)
              if any(tag in p["product"] for tag in products)]
    fig, axes = plt.subplots(1, len(chosen), figsize=(7.2, 3.9), constrained_layout=True)
    for axis, product in zip(axes, chosen):
        area = _layer(product["folder"], "areaOfInterestA", crs).union_all().intersection(run_box)
        reference = _layer(product["folder"], "observedEventA", crs).union_all().intersection(area)
        mine = ours.intersection(area)
        parts = {"agree": mine.intersection(reference), "ours": mine.difference(reference),
                 "missed": reference.difference(mine)}
        gpd.GeoSeries([area], crs=crs).boundary.plot(ax=axis, color=MUTED, linewidth=0.6)
        for key, colour in (("missed", MISSED), ("agree", AGREE), ("ours", OURS_ONLY)):
            if not parts[key].is_empty:
                gpd.GeoSeries([parts[key]], crs=crs).plot(ax=axis, color=colour, linewidth=0)
        km2 = {key: part.area / 1e6 for key, part in parts.items()}
        recall = km2["agree"] / max(reference.area / 1e6, 1e-9)
        precision = km2["agree"] / max(mine.area / 1e6, 1e-9)
        axis.set_title(f"{product['aoi']}\nrecall {recall:.2f} · precision {precision:.2f}",
                       fontsize=9, color=INK)
        axis.set_axis_off()
        axis.set_aspect("equal")
        axis.legend(handles=[
            Patch(color=AGREE, label=f"both maps  {km2['agree']:.2f} km²"),
            Patch(color=MISSED, label=f"reference only (missed)  {km2['missed']:.2f} km²"),
            Patch(color=OURS_ONLY, label=f"ours only  {km2['ours']:.2f} km²"),
        ], loc="lower center", bbox_to_anchor=(0.5, -0.22), fontsize=7.5, frameon=False)
    fig.suptitle("ValleyWatch against the EMSR927 reference (thorough mode)", fontsize=10, color=INK)
    fig.text(0.5, 0.005, ATTRIBUTION + ". Contains modified Copernicus Sentinel data 2026.",
             ha="center", fontsize=6.5, color=MUTED)
    fig.savefig(out_path, dpi=200)
    plt.close(fig)
    return out_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    parser.add_argument("--activation", default="EMSR927")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    reference = Path(args.run).resolve().parents[1] / "data" / args.activation.lower()
    print(overlay_figure(args.run, args.activation, reference, out / "emsr927_overlay.png"))


if __name__ == "__main__":
    main()
