# References and UI Guide

Existing open-source work to learn from, the libraries to use, and how the dashboard should look and behave. Read alongside `IDEA.md` and `RULES_AND_CRITERIA.md`.

**How to use the reference repos:** study them for method and API usage, then write our own code. Do not copy code wholesale. Credit any repo that influenced the design in the README.

## Reference repos (analysis pipeline)

| Repo | What to take from it | Caution |
|---|---|---|
| https://github.com/samw0907/SARFloodAnalysis | Closest match to our pipeline: Copernicus Data Space scenes, log-ratio change detection between pre- and post-event Sentinel-1 GRD, threshold calibration, validation against Copernicus EMS delineations. Look at its detection modes (decrease only vs combined magnitude). | Its overlap scores vary widely between flood events, which shows why we must test on several events and adapt thresholds per area. |
| https://github.com/interTwin-eu/openeo-flood-mapper-local | TU Wien workflow for flood mapping from Sentinel-1 backscatter in openEO syntax. Useful for Copernicus Data Space API calls. | Check which auxiliary inputs it uses before borrowing an approach. |
| https://github.com/kleok/FLOODPY | Python toolbox for flood mapping from Sentinel-1 GRD. Useful for how it selects the pre-flood baseline images. | Uses ERA-5 weather data, which is **not** an allowed input for us. GPL v3 licensed, so do not copy code into this MIT repo. |
| https://github.com/Orion-AI-Lab/KuroSiwo | Dataset, preprocessing configs and pretrained weights. Only needed if a segmentation model is added later as an upgrade. | Cite Bountos et al., 2024 if used. |
| UN-SPIDER recommended practice (Sentinel-1 flood mapping) https://un-spider.org/advisory-support/recommended-practices/recommended-practice-google-earth-engine-flood-mapping/step-by-step | The standard change-detection recipe and typical threshold values. | Its helper layers for permanent water, terrain and population are **not** on our allowed list. Use the pre-event Sentinel-1 image and the Copernicus DEM instead. |

**Do not use:** any pretrained flood model that was trained on data outside our listed training datasets (for example Microsoft's ai4g-flood), and any auxiliary dataset not on the allowed list in `RULES_AND_CRITERIA.md`.

## Libraries (analysis pipeline)

| Library | Use |
|---|---|
| `openeo` or the Sentinel Hub Process API client | Fetch terrain-corrected Sentinel-1 backscatter, Sentinel-2 bands and the Copernicus DEM from Copernicus Data Space |
| `rasterio`, `numpy`, `scipy` / `scikit-image` | Raster maths, speckle filtering, thresholding (Otsu), small-patch removal |
| `geopandas`, `shapely` | Vectorising masks, intersecting with OSM features |
| `requests` against `https://api.ohsome.org/v1` | Pre-event OpenStreetMap snapshot (elements/geometry endpoint with a `time` parameter) |
| `networkx` (optionally `osmnx` helpers) | Road graph and routing for the cut-off analysis |
| `pysheds` (https://github.com/mdbartos/pysheds) | D8 flow direction and flow path on the DEM, for the flood-path bonus |

## Libraries (dashboard)

Preferred stack: **MapLibre + deck.gl inside Next.js**. Leaflet is an acceptable fallback if it saves time.

| Library | Use |
|---|---|
| https://github.com/maplibre/maplibre-gl-js | Base map. Handles large polygon layers smoothly. |
| https://github.com/visgl/deck.gl | Animated data layers: flood polygons fading in, roads changing colour, `TripsLayer` for the flood path flowing down the valley. |
| https://github.com/visgl/react-map-gl | React bindings for MapLibre and deck.gl. |
| https://github.com/maplibre/maplibre-gl-compare | Before/after swipe slider between the two satellite images. |
| https://github.com/Turfjs/turf | Small geometry calculations in the browser (areas, lengths, bounding boxes). |
| https://github.com/keplergl/kepler.gl | Layout inspiration only: layer toggles, legends, side panels. Do not embed it. |
| https://github.com/digidem/leaflet-side-by-side | Swipe slider, only if the fallback Leaflet stack is used. |

## Dashboard design

### Layout

- **Map** fills most of the screen.
- **Left panel:** inputs (draw area, pick flood date, Analyse button) and the pipeline progress.
- **Right panel:** totals, the cut-off settlement list (ranked by building count), and the copilot chat.
- **Top or bottom bar:** which satellite scenes were used and their dates, plus the required attribution lines.

### Map layers (each with a toggle and a legend entry)

1. Before and after satellite imagery, with the swipe slider
2. Flood water extent
3. Debris extent
4. Damaged buildings, roads and bridges, styled by confidence (high, medium, low)
5. Cut-off settlements, with the broken link highlighted
6. Flood path (bonus)

### Interactions and animation

- **Pipeline progress:** while the analysis runs, show each step ticking off ("Finding satellite scenes", "Detecting flood and debris", "Checking roads and buildings", "Finding cut-off settlements") and add its layer to the map as it completes.
- **Cut-off settlements:** pulsing markers. Clicking one zooms to it, highlights the broken road or bridge, and shows the route that used to exist.
- **Click-through numbers:** clicking a total in the side panel, or a figure in the report, zooms to and highlights the features behind it.
- **Flood path:** animated line travelling down the valley from the chosen upstream point.
- **Report:** a "Generate report" button that opens the one-page situation report, with an English/Nepali switch and a print/PDF option.

### Rules for the UI

- Keep the display base map separate from the analysis data. The base map is for viewing only; the analysis must use the pre-event OpenStreetMap snapshot.
- Show the attribution lines from `RULES_AND_CRITERIA.md` on screen at all times.
- Never show photographs of victims.
- Label the system as an educational prototype.
- Show a visible "last satellite pass" date so users know how old the picture is.

### Priority

The dashboard is 10% of the score. Build order for the UI:

1. Plain map with the flood, damage and cut-off layers, totals panel and report button
2. Pipeline progress and click-through numbers
3. Before/after swipe slider
4. Animations (pulsing markers, flood path)

Do not start items 3 and 4 until the mapping, damage overlay, cut-off analysis and copilot all work end to end.
