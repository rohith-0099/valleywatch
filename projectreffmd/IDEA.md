# Our Project: ValleyWatch

*(Working name. If the repo has a different name, use that everywhere instead.)*

**One line:** give ValleyWatch an area and a flood date, and it maps the flood from satellite data, lists what was damaged, shows which settlements are cut off, and writes a situation report in English and Nepali.

Read `PROBLEM_STATEMENT.md` for what the organisers ask, `RULES_AND_CRITERIA.md` for hard constraints, and `DIFFERENTIATORS.md` for where this build must be better than a generic one.

## What the user does

1. Opens the web dashboard, draws a box over a valley and picks the flood date.
2. Clicks **Analyse**. The map then shows:
   - flooded area and debris-covered area as separate layers,
   - damaged buildings, roads and bridges, each with a confidence level,
   - cut-off settlements, with the broken road link highlighted.
3. A side panel shows totals (area flooded, buildings hit, bridges down, settlements cut off).
4. Clicks **Generate report** for a one-page situation report in English or Nepali.
5. Asks the copilot questions such as "which villages cannot reach a hospital?" and gets answers drawn from the computed data.

## Pipeline

### Step 1: Scene picker

- Input: bounding box (or polygon) and flood date.
- Query the Copernicus Data Space catalogue for Sentinel-1 GRD scenes covering the area before and after the date.
- Choose a before/after pair on the **same relative orbit** and same pass direction, as close to the event as possible.
- Also look for Sentinel-2 scenes before and after, and record cloud cover over the area.
- Output: the chosen scene IDs, dates, orbit number, and a note of why they were chosen (shown to the user and used in the report).

### Step 2: Flood and debris mask (Sentinel-1)

- Get terrain-corrected backscatter (VV and VH) for both dates through the Copernicus Data Space processing APIs (openEO or the Sentinel Hub Process API), using the Copernicus DEM.
- Apply a speckle filter.
- Compute the change between before and after (log-ratio in dB).
- Classify:
  - strong **decrease** in backscatter: new open water,
  - strong **increase** in backscatter: likely debris or rough deposited material.
- Thresholds: start from published practice (the UN-SPIDER recommended practice uses a ratio threshold of about 1.25 on VH for water) and make them configurable. Prefer a data-driven threshold (for example Otsu or a percentile on the change image) so it adapts to each area.
- Masks:
  - remove steep slopes and radar shadow/layover areas using the Copernicus DEM,
  - remove water that was already present in the before image (permanent water),
  - remove patches smaller than a minimum size.
- Output: polygons for water and debris, each with a confidence value.

### Step 3: Sentinel-2 check (when clear)

- If cloud-free before and after images exist, compute change in a vegetation index (NDVI drop) and a water index.
- Use this to confirm, extend or down-weight the radar result, and record which source supported each polygon.
- If no clear image exists, say so in the output and carry on with radar only.

### Step 4: Damage overlay

- Fetch pre-event OpenStreetMap buildings, roads and bridges from the ohsome API for the area, using a snapshot date before the event.
- Intersect them with the flood and debris polygons.
- Bridges and river crossings need care: a road crossing a river is not damaged just because it crosses water. Only change relative to the before image counts.
- Output per feature: hit or not, which hazard (water or debris), and a confidence level (high, medium, low).

### Step 5: Cut-off settlement analysis

- Build a road graph from the pre-event OpenStreetMap roads.
- Identify settlements (OSM place nodes such as village and hamlet), towns, and hospitals or health facilities.
- Remove road segments and bridges marked as hit.
- For each settlement, test whether a route still exists to the nearest town and to the nearest hospital.
- Output per settlement: connected or cut off, the broken link responsible, route length before and after, and a building count as a rough size indicator.

### Step 6: Situation-report copilot (the chosen AI component)

- The language model has no direct knowledge of the event. It can only call functions that return computed results (totals, lists of damaged features, cut-off settlements, scene metadata).
- It writes a one-page situation report and answers questions, in English and Nepali.
- Every figure in its output must be traceable to a function result. If the data does not contain an answer, it says so.
- Include a check that compares numbers in the generated text against the source data before showing it.

### Step 7: Validation

- Case study: run the pipeline on the August 2026 Trishuli flood and compare against the EMSR927 reference maps (overlap metrics such as IoU, precision, recall).
- Run on several other past flood events to show it generalises.
- Validation code reads reference maps; the main pipeline must never import it.

### Step 8: Bonus, flood-path tracing

- Given a point upstream, follow the steepest-descent flow path on the Copernicus DEM down the valley and list the settlements along it.

## Suggested stack

- **Backend:** Python, FastAPI, with rasterio, numpy, geopandas, shapely, networkx (or osmnx), and the Copernicus Data Space clients.
- **Frontend:** Next.js with Leaflet (or MapLibre) for the map dashboard.
- **Copilot:** any LLM API with function calling.
- **Outputs:** GeoJSON layers for the map, plus a printable one-page report (HTML to PDF).

## Build order

1. Scene picker and flood/debris mask (Steps 1 and 2), tested on the Trishuli case
2. Damage overlay (Step 4)
3. Cut-off analysis (Step 5)
4. Dashboard
5. Copilot and situation report (Step 6)
6. Sentinel-2 check (Step 3)
7. Validation against EMSR927 and other events (Step 7)
8. Flood-path bonus (Step 8)
9. Report (max. 6 pages), 3-minute video, README

Each step should work end to end before the next begins, so there is always a running system.

## Things to verify early

- Which Sentinel-1 scenes actually exist around 26 August 2026 for the corridor, and on which orbits. One public report mentions an acquisition on 24 August 2026; confirm in the catalogue.
- That the chosen Copernicus Data Space API returns terrain-corrected backscatter fast enough for a live demo on a judge-chosen area. If not, add caching and a progress indicator.
- Free-tier processing quotas on Copernicus Data Space, so the demo does not run out on judging day.
