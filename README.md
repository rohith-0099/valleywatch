# ValleyWatch

Give ValleyWatch an area and a flood date, and it maps the flood from free
satellite data. Built for the Multimodal AI Hackathon 2026 (KamandPrompt,
IIT Mandi), Track B: Mapping Flood Damage from Space.

**This is an educational prototype, not an operational tool.**

## Status

| Step | State |
|---|---|
| 1. Scene picker (Sentinel-1 same-orbit pair, pre-event baseline pass) | working |
| 2. Flood and debris mask from Sentinel-1 | working |
| 3. Sentinel-2 check (per-pixel cloud mask) | working |
| 4. Damage overlay (OpenStreetMap buildings, roads, bridges) | working |
| 5. Cut-off settlement analysis | working |
| 6. Copilot and situation report (English, Nepali) | working |
| 7. Validation against EMSR927 | working (scores in FINDINGS.md) |
| 8. Flood-path tracing | not started |
| Dashboard (map, layers, totals, cut-off list, live progress) | working |
| Dashboard report buttons and copilot chat | working |
| Dashboard swipe slider, flood path | not started |

## Prerequisites

- Python 3.12
- Node.js 20 or newer (dashboard)
- A free Copernicus Data Space account: https://dataspace.copernicus.eu

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
cp .env.example .env    # then fill it in
```

Secrets live in `.env` in the repo root (never committed):

- `CDSE_CLIENT_ID`, `CDSE_CLIENT_SECRET`: a Copernicus Data Space OAuth
  client. Create one at https://shapps.dataspace.copernicus.eu/dashboard/
  under User Settings > OAuth clients. Without these the first run asks for
  a browser login instead.
- `GROQ_API_KEY`: for the copilot (Step 6).

## Run

The only inputs are a bounding box (west south east north, in degrees) and a
flood date.

```bash
cd backend
../.venv/bin/python -m valleywatch.pipeline --bbox WEST SOUTH EAST NORTH --date YYYY-MM-DD
```

Add `--thorough` to also use a second radar track that looks from the
opposite side (fills radar blind zones, three more downloads).

Boxes up to 400 km2 are fetched by direct download and finish in about six
minutes. Larger boxes need `--large` and use slow batch jobs (about 25
minutes for 1,800 km2 the first time). Downloads are cached in `data/`, so a
repeated run takes about a minute and costs no quota.

Outputs go to `outputs/<date>_<bbox>/`:

| File | Content |
|---|---|
| `flood_debris.geojson` | water and debris polygons with confidence and evidence source |
| `buildings_hit.geojson`, `road_hits.geojson`, `bridges.geojson` | damage overlay |
| `settlements.geojson` | every settlement with its connection status, ranked |
| `broken_links.geojson`, `lost_routes.geojson` | the road link responsible and the route that used to exist |
| `summary.json` | scenes used and why, thresholds, acceptance test, all totals |
| `quicklook.png`, `classes.tif` | picture and raster of the result |

## Dashboard

Two terminals:

```bash
cd backend && ../.venv/bin/uvicorn api:app --port 8000
cd frontend && npm install && npm run dev      # http://localhost:3000
```

Draw a box (up to 400 km2), pick the flood date, press Analyse. When it
finishes, the right panel offers the one-page situation report (English or
Nepali, printable) and the copilot chat. Finished runs
can be reopened from the "Earlier runs" list. The base map is for display
only; the analysis uses the pre-event OpenStreetMap snapshot.

## Validation (reference maps, checking only)

```bash
cd backend
../.venv/bin/python -m validation.emsr927 --run ../outputs/<run folder>
```

This downloads the Copernicus EMS products for EMSR927 and writes overlap
scores next to the run. The pipeline never imports this module.
Attribution: European Union, Copernicus Emergency Management Service data.

## False-alarm budget

Rules are loosened only while the same rules, run on images from before the
flood, map at most 5% of the flood-pair area:

```bash
cd backend
../.venv/bin/python -m tools.false_alarm_scan --bbox W S E N --date YYYY-MM-DD \
    --setting corridor_reach_hand_m --values 20 60 120
```

## Tests

```bash
cd backend && ../.venv/bin/python -m pytest
```

## How it works

1. **Scene picker** (`scene_picker.py`): searches the Copernicus catalogue
   and picks a before and an after Sentinel-1 image on the same relative
   orbit, so both view the terrain from the same angle. It also takes the
   pass before that as a no-flood baseline.
2. **Fetch** (`fetch.py`): openEO returns VV and VH backscatter,
   orthorectified with the Copernicus DEM, the DEM itself, and cloud-free
   Sentinel-2 composites (clouds removed per pixel with the scene
   classification band). Requests run in parallel.
3. **Terrain** (`terrain.py`, `corridor.py`): steep slopes, radar shadow and
   layover are excluded. The river zones are derived from the DEM with flow
   routing: a core within 20 m of height above the river, and a reach zone
   up to 120 m into which a detection may grow from the core. A second
   radar track looking from the opposite side fills blind zones.
4. **Radar detection** (`flood_mask.py`): Lee speckle filter, change in dB, a
   threshold that adapts to each area, hysteresis. Both bands drop = new
   water; VV rises = debris. Water already present before is removed.
5. **Optical check** (`optical.py`): vegetation loss from Sentinel-2, where
   both dates are clear and the pixel is not in shadow, can add debris that
   radar missed. Optical water only confirms radar water.
6. **Flood path and confidence** (`refine.py`): only detections draining into
   a river reach downstream of confident change are kept. Confidence is high
   where radar and optical agree, medium for optical only, low for radar only.
7. **Acceptance test**: the radar rules are also run on two images from
   before the flood. The area found there is the false-alarm level, and is
   written to `summary.json` next to the flood result.
8. **Damage** (`osm.py`, `damage.py`): pre-event OpenStreetMap features are
   overlaid on the polygons. A bridge is judged only by the bank at each end
   of its deck, never by change in the river under the span.
9. **Cut-off analysis** (`cutoff.py`): a road graph with hit sections and hit
   bridges removed; each settlement is tested for a route to the nearest
   town and hospital, and the broken link is identified.

10. **Copilot and report** (`backend/copilot/`): the language model (Groq)
    can only call functions that read the run's output files. Every number
    in its text is checked against those results before display. The
    one-page report's figures are written by code; the model writes only
    the summary paragraph.

### OpenStreetMap snapshot method

OpenStreetMap comes from the ohsome API as it stood before the event (for
the Trishuli case: 27 July 2026, the newest data ohsome holds). The snapshot
endpoint `/elements/geometry` currently answers `403 Forbidden` on the public
server, so the code falls back to `/elementsFullHistory/geometry` of the same
API over a one-day window ending at the snapshot date and keeps the feature
versions still valid at that date. This is the same snapshot by another
route: building counts match `/elements/count` exactly. The live
OpenStreetMap is never used.

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

- pysheds (flow routing and height above nearest drainage)
- UN-SPIDER recommended practice for Sentinel-1 flood mapping (change detection recipe)
- samw0907/SARFloodAnalysis (log-ratio change detection on Copernicus Data Space)
- interTwin-eu/openeo-flood-mapper-local (openEO usage)

## AI assistance disclosure

AI coding assistants were used, as the hackathon rules allow. Claude Code
(Anthropic) wrote the first version of the code in `backend/` and
`frontend/`, this README and the notes in FINDINGS.md under the team's
direction. The team reviewed the code, chose the
method and parameters, and ran the tests on real data.
