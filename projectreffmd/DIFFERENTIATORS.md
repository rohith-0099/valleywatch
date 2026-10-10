# What Makes This Build Different

Most teams in this track will build the same pipeline, because the problem statement is fixed. The judging is live on an area the judges pick, so the winning build is the one that is correct and reliable where generic builds fail. This file lists those places. Treat each as a requirement, not a nice-to-have.

## 1. Accuracy in mountain terrain (30% mapping quality)

| Generic build | This build |
|---|---|
| Compares any before and after radar images | Only compares images from the same relative orbit and pass direction |
| Flags every dark pixel as water | Masks steep slopes and radar shadow/layover using the Copernicus DEM, since shadow looks like water |
| Detects water only | Detects water (backscatter drop) **and** debris (backscatter rise). The case-study event was a debris flood. |
| Uses one fixed threshold everywhere | Uses a data-driven threshold per area, with a configurable fallback |
| Counts the existing river as flood | Removes water already present in the before image |
| Radar only | Adds a Sentinel-2 check when a cloud-free image exists, and says so when it does not |

## 2. Damage and cut-off analysis done properly (20%)

- **Bridges:** a road crossing a river is not automatically damaged. Only change since the before image counts.
- **Confidence levels:** every damaged feature is marked high, medium or low confidence, not just yes or no.
- **Real routing:** settlements are tested for a route to both the nearest town and the nearest hospital, on the pre-event road graph with hit segments removed.
- **The broken link is shown:** for each cut-off settlement, highlight the segment or bridge responsible.
- **Detours:** for settlements still connected, report when the route became much longer.
- **Priority ranking:** order cut-off settlements by building count, so rescuers see the largest first.

## 3. A copilot that cannot invent numbers (25%)

- The model answers only through function calls into the computed data.
- Each figure in a report links back to the features on the map.
- A check compares numbers in the generated text with the source data before display.
- When the data has no answer, it says "no data" instead of guessing.
- English and Nepali output from the same underlying facts.

## 4. Proof that it generalises

- Overlap scores against EMSR927 for the Trishuli case study, reported per area.
- The same pipeline run on several other past floods, with results shown.
- Nothing hardcoded to one valley: area and date are the only inputs.

## 5. Strict rule compliance

- Only the allowed input datasets are used (see `RULES_AND_CRITERIA.md`). No surface-water layers, population grids or other helper datasets.
- Validation code that reads reference maps is isolated from the pipeline.
- The required attribution lines appear in the README, report and dashboard.

## 6. Honesty about limits (15%)

The report and dashboard state plainly what the system cannot do, for example:

- Sentinel revisit times mean it cannot give minutes-ahead warning.
- Radar struggles in narrow, steep valleys and under dense vegetation, and cannot see inside shadow or layover zones.
- OpenStreetMap coverage is incomplete in remote areas, so missing buildings and tracks are undercounted.
- A road marked "hit" is an estimate from 10 m imagery, not a field-verified closure.
- Building counts are a rough proxy for population.

Record real failure cases found during testing and how they were fixed. These go in the report and are the best material for the Q&A.

## 7. Usability for rescue teams (10%)

- One screen: map, totals and the cut-off list together.
- A one-page report that prints cleanly.
- The chosen satellite scenes and their dates are shown, so users know how fresh the picture is.
- Optional, if time allows: suggest flat open ground near cut-off settlements from the DEM as possible helicopter access, labelled clearly as a rough hint.

## If time runs short, keep these three

1. Terrain masking
2. Water and debris detection on same-orbit pairs
3. Testing on other floods
