# ValleyWatch

Give ValleyWatch an area and a flood date, and it maps the flood from free
satellite data. Built for the Multimodal AI Hackathon 2026 (KamandPrompt,
IIT Mandi), Track B: Mapping Flood Damage from Space.

**This is an educational prototype, not an operational tool.**

## Status

| Step | State |
|---|---|
| 1. Scene picker (Sentinel-1 same-orbit pair, Sentinel-2 listing) | working |
| 2. Flood and debris mask from Sentinel-1 | working, under test |
| 3. Sentinel-2 check | not started |
| 4. Damage overlay (OpenStreetMap) | not started |
| 5. Cut-off settlement analysis | not started |
| 6. Copilot and situation report (English, Nepali) | not started |
| 7. Validation against EMSR927 | not started |
| 8. Flood-path tracing | not started |

## Prerequisites

- Python 3.12
- A free Copernicus Data Space account: https://dataspace.copernicus.eu

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
```

Secrets go in a `.env` file in the repo root (never committed). The copilot
will need `GROQ_API_KEY`. The flood-mapping steps need no key: the first run
prints a link for a browser login to Copernicus Data Space, and the token is
then stored by the openEO client.

## Run the flood map

The only inputs are a bounding box (west south east north, in degrees) and a
flood date.

```bash
cd backend
../.venv/bin/python -m valleywatch.pipeline --bbox WEST SOUTH EAST NORTH --date YYYY-MM-DD
```

Outputs go to `outputs/<date>_<bbox>/`:

- `flood_debris.geojson`: water and debris polygons with a confidence value
- `summary.json`: scene IDs and dates used, why they were chosen, thresholds, totals
- `quicklook.png`: before, after, change and result side by side
- `classes.tif`: the class raster (1 = water, 2 = debris)

Downloaded rasters are cached in `data/` so a repeated run costs no quota.

## Tests

```bash
cd backend && ../.venv/bin/python -m pytest
```

## How the flood map works

1. **Scene picker** (`scene_picker.py`): searches the Copernicus catalogue and
   picks a before and an after Sentinel-1 image on the same relative orbit, so
   both view the terrain from the same angle.
2. **Fetch** (`s1_fetch.py`): openEO returns VV and VH backscatter,
   orthorectified with the Copernicus DEM, plus the DEM itself.
3. **Classify** (`flood_mask.py`): Lee speckle filter, change in dB, a
   threshold that adapts to each area, then: both bands drop = new water,
   VV rises = debris.
4. **Masks** (`terrain.py`): steep slopes, radar shadow and layover are
   excluded using the DEM. Water already present before the event is removed.
5. **Outputs** (`vectorize.py`, `quicklook.py`).

## Repository layout

- `backend/valleywatch/`: the pipeline. Uses only the allowed inputs.
- `backend/validation/`: code that reads reference maps (EMSR927) to check
  results. The pipeline never imports this package.
- `FINDINGS.md`: what failed on real data and how it was handled.
- `projectreffmd/`: problem statement, rules and design notes.

## Data rules

Inputs are limited to Sentinel-1, Sentinel-2, the Copernicus DEM and
pre-event OpenStreetMap. No other surface-water, population or elevation
layer is used. Copernicus EMS maps are used only to check results.

## Attribution

- Contains modified Copernicus Sentinel data 2026.
- Produced using Copernicus WorldDEM-30 © DLR e.V. 2010–2014 and © Airbus Defence and Space GmbH 2014–2018 provided under COPERNICUS by the European Union and ESA; all rights reserved.
- © OpenStreetMap contributors.

## Method references

Studied for method only; no code was copied.

- UN-SPIDER recommended practice for Sentinel-1 flood mapping (change detection recipe)
- samw0907/SARFloodAnalysis (log-ratio change detection on Copernicus Data Space)
- interTwin-eu/openeo-flood-mapper-local (openEO usage)

## AI assistance disclosure

AI coding assistants were used, as the hackathon rules allow. Claude Code
(Anthropic) wrote the first version of the code in `backend/` and this
README under the team's direction. The team reviewed the code, chose the
method and parameters, and ran the tests on real data.
