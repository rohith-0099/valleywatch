"""Find how far a rule can be loosened within the false-alarm budget.

Method: run the whole flood map with a rule set to each of several values.
For each value the pipeline also maps a pair of images from BEFORE the flood
with the identical rules (the acceptance test). A value is acceptable while
that no-flood area stays within the budget share of the flood-pair area.
We keep the loosest acceptable value.

Only our own satellite data is used. No reference map is read here.

    python -m tools.false_alarm_scan --bbox W S E N --date YYYY-MM-DD \
        --setting corridor_reach_hand_m --values 20 40 60 80 120
"""
import argparse
import contextlib
import io
import json
import tempfile
from datetime import date

from valleywatch.config import Settings
from valleywatch.pipeline import run_flood_mapping


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bbox", nargs=4, type=float, required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--setting", required=True)
    parser.add_argument("--values", nargs="+", type=float, required=True)
    parser.add_argument("--fix", nargs="*", default=[], metavar="NAME=VALUE",
                        help="Other settings held fixed during the scan")
    args = parser.parse_args()

    rows = []
    for value in args.values:
        settings = Settings()
        setattr(settings, args.setting, value)
        for item in args.fix:
            name, text = item.split("=")
            current = getattr(settings, name)
            # Convert the text to the type the setting already has.
            setattr(settings, name, text == "True" if isinstance(current, bool)
                    else type(current)(text))
        # Outputs go to a throw-away folder; downloads still come from the cache.
        with tempfile.TemporaryDirectory() as scratch, contextlib.redirect_stdout(io.StringIO()):
            summary = run_flood_mapping(tuple(args.bbox), date.fromisoformat(args.date),
                                        settings, output_dir=scratch, progress=lambda m: None)
        test = summary["acceptance_test"]
        row = {args.setting: value, "flood_pair": test["flood_pair"],
               "no_flood_pair": test["no_flood_pair"],
               "no_flood_percent": test["no_flood_as_percent_of_flood"],
               "within_budget": test["within_budget"],
               "final_map": {k: summary["totals"][k] for k in ("water_km2", "debris_km2")}}
        rows.append(row)
        print(json.dumps(row), flush=True)


if __name__ == "__main__":
    main()
