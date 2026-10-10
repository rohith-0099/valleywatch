"""Chart for the report: the no-flood test, event by event.

Reads only our own run summaries (no reference maps).

    python -m tools.report_figures --outputs ../outputs --out ../docs/figures
"""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Two colours checked with the palette validator; text stays in ink colours.
FIRST, FINAL = "#eb6834", "#2a78d6"
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#dddcd6"

# Run folder, label, and the share measured the FIRST time the whole-chain
# test was run on that event (from FINDINGS.md), where it differs from now.
EVENTS = [
    ("2026-08-26_85.100_27.850_85.450_28.320_thorough", "Trishuli 2026\n(case study)", 10.7),
    ("2018-08-16_76.350_9.300_76.500_9.450", "Kerala 2018\n(lowland)", 17.3),
    ("2023-10-04_88.600_27.550_88.700_27.700", "Sikkim 2023", None),
    ("2021-06-15_85.500_27.780_85.600_27.920", "Melamchi 2021", None),
    ("2021-02-07_79.580_30.440_79.740_30.560", "Chamoli 2021", None),
]


def no_flood_chart(outputs, out_path):
    labels, first, final = [], [], []
    for folder, label, first_share in EVENTS:
        summary = json.loads((Path(outputs) / folder / "summary.json").read_text())
        labels.append(label)
        final.append(summary["acceptance_test"]["no_flood_as_percent_of_flood"]["total"] or 0.0)
        first.append(first_share)

    fig, axis = plt.subplots(figsize=(7.2, 3.0), constrained_layout=True)
    width = 0.36
    for i, (a, b) in enumerate(zip(first, final)):
        if a is not None:  # only events where a fix changed the result
            axis.bar(i - width / 2 - 0.01, a, width, color=FIRST)
            axis.text(i - width / 2 - 0.01, a + 0.4, f"{a:.1f}%", ha="center", fontsize=8, color=INK)
        x = i + width / 2 + 0.01 if a is not None else i
        axis.bar(x, b, width, color=FINAL)
        axis.text(x, b + 0.4, f"{b:.1f}%", ha="center", fontsize=8, color=INK)
    axis.axhline(5, color=MUTED, linewidth=1, linestyle=(0, (4, 3)))
    axis.text(len(labels) - 0.5, 5.4, "budget 5%", ha="right", fontsize=8, color=MUTED)
    axis.bar(0, 0, color=FIRST, label="first full test")
    axis.bar(0, 0, color=FINAL, label="final rules")
    axis.set_xticks(range(len(labels)), labels, fontsize=8, color=INK)
    axis.set_ylabel("area mapped with NO flood,\nas % of flood-pair area", fontsize=8, color=MUTED)
    axis.set_ylim(0, 20)
    axis.tick_params(axis="y", labelsize=8, colors=MUTED, length=0)
    axis.tick_params(axis="x", length=0)
    axis.yaxis.grid(True, color=GRID, linewidth=0.6)
    axis.set_axisbelow(True)
    for side in ("top", "right", "left"):
        axis.spines[side].set_visible(False)
    axis.spines["bottom"].set_color(GRID)
    axis.legend(frameon=False, fontsize=8, loc="upper right")
    axis.set_title("Self-check: the same rules run on images from before the flood",
                   fontsize=10, color=INK, loc="left")
    fig.savefig(out_path, dpi=200)
    plt.close(fig)
    return out_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outputs", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    print(no_flood_chart(args.outputs, out / "no_flood_test.png"))


if __name__ == "__main__":
    main()
