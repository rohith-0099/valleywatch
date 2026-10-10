# Findings

Notes on what happened with real data: what failed, why, and what we did.
These feed the report and its limitations section.

## Scene availability, Trishuli case (flood date 26 August 2026)

Catalogue search for the corridor found three Sentinel-1 tracks, all from
Sentinel-1D only, each repeating every 12 days:

| Relative orbit | Direction | Before | After | Covers test box |
|---|---|---|---|---|
| 85 | ascending | 16 Aug | 28 Aug | 100% |
| 19 | descending | 24 Aug | 5 Sep | 100% |
| 121 | descending | 19 Aug | 31 Aug | 35% |

- The picker chose orbit 85: its after image is 2 days after the flood.
  The trade-off is a before image 10 days old, so some change may be
  unrelated to the flood (rain, river level).
- Orbit 19 has the 24 August image mentioned in public reports, but its
  after image is 10 days late, when open water has likely drained.
- Limitation: with one satellite per track, the earliest possible radar look
  was 2 days after the event.

## Sentinel-2 cloud cover

Every Sentinel-2 tile over the corridor from 27 August to mid-September is
54% to 97% cloudy at tile level (monsoon). The optical check will often have
nothing to work with, which is why radar is the primary source.

## Copernicus login

- The openEO browser (device-code) login failed three times: the code expires
  after about 10 minutes and the approval never registered. Fix: the pipeline
  now logs in with an OAuth client ID and secret read from `.env`, with the
  browser login kept as a fallback. This also removes any interaction during
  a live demo.

## First real run, small test box (85.30 28.12 85.38 28.20, 8 x 9 km)

- End to end in 2 min 37 s using direct (synchronous) openEO downloads.
- 65% of the box cannot be mapped: 61% is steeper than 30 degrees and 25% is
  in layover (the two overlap). Only the narrow valley floor and gentle
  terraces remain. This is the main limit of radar in a Himalayan gorge.
- Slopes facing the radar are smeared into east-west streaks by the terrain
  correction. The change image there swings by about +/-4 dB with no real
  change. The layover mask removes these areas; without it they would be
  reported as flood and debris.
- Noise level of the change image on usable ground is about 1.4 dB, giving
  an adaptive threshold of 4.2 dB (the fixed fallback would be 3 dB).
- Along the river the dominant signal is a backscatter DROP, not a rise.
  Detected area in this box is small (0.009 km2 water, 0.043 km2 debris).

## Full corridor run (85.10 27.85 85.45 28.32, 35 x 52 km, 18.5 M pixels)

- Runtime about 17 minutes: three openEO batch jobs (4.6 + 4.6 + 2.2 min)
  plus about 1.5 min of local processing. Too slow for a live demo on a large
  box. Re-runs use the cached rasters and take about 1.5 min. Options: ask
  judges for a smaller box, run the two image jobs in parallel, or work at
  20 m.
- Result: 0.705 km2 new water in 145 polygons, 1.739 km2 debris in 903
  polygons. 56% of the box is not mappable (steep, layover or shadow).
- Adaptive thresholds: 3.95 dB (VV) and 4.24 dB (VH).
- The change image shows a continuous line along the whole river from the
  north-east corner to the south-west corner, so the flood signal is real.
- Lower valley (wide floor): detection follows the river well. Water
  polygons trace the channel; the largest patches sit at bends and
  confluences.
- Upper gorge: the signal is visible in the change image but mostly NOT
  detected. The channel is only a few pixels wide and lies inside the steep
  or layover mask. Expect low recall there against EMSR927.
- Debris class is noisy: 892 of 903 debris polygons are low confidence, the
  median patch is 1,400 m2, and many are isolated specks in the town area
  and on hillsides. Likely false positives. Candidate fixes: stronger
  minimum size for debris, require VH to rise as well, or keep only debris
  connected to the river corridor.
- A side river in the south-east also shows change. With a 10-day-old before
  image this may be ordinary monsoon river change, not the flood. The system
  cannot tell these apart.
- Bug found and fixed: "permanent water" was first reported as 31.6 km2
  because dark radar shadow on steep slopes was counted. It is now counted on
  mappable ground only (5.1 km2), which still includes shadowed gentle
  ground, so it is an upper bound.
- No water polygon reaches "high" confidence (97 low, 48 medium). The
  confidence scale needs calibrating against the reference maps later.

## Changes after the first review (10 Oct)

All numbers in this section are raw output. Nothing has been compared with
EMSR927 yet, so none of this says the result is more ACCURATE, only what
changed.

### River corridor from the DEM

- Detections are now accepted only on ground less than 40 m above the
  nearest river cell (HAND, computed with pysheds from the Copernicus DEM;
  a river cell drains at least 10 km2).
- pysheds needs numpy below 2.4 (it calls `numpy.in1d`, removed in 2.4).
  numpy is pinned in requirements.txt.
- Limitation: the river network is computed inside the box only. A river
  that enters the box from outside starts with zero upstream area, so its
  first stretch inside the box may not be recognised as a river. A small box
  across a big river is affected most.
- Limitation: real damage away from the valley floor (for example a
  landslide on a hillside) is no longer reported.

### Small test box (85.30 28.12 85.38 28.20) before and after the changes

| | First version | Now, radar only | Now, with optical |
|---|---|---|---|
| Water | 0.009 km2 | 0.042 km2 | 0.073 km2 |
| Debris | 0.043 km2 | 0.061 km2 | 0.581 km2 |

- (b) Relaxed slope limit in the corridor (45 instead of 30 degrees) plus
  hysteresis raised radar water from 0.009 to 0.042 km2. Still, 23% of the
  corridor in this box is invisible to radar (layover or shadow).
- (c) Pre-event pair 4 Aug to 16 Aug on the same orbit, same rules: 0.000
  km2 water and 0.026 km2 debris detected with no flood. So normal change
  explains little of the water signal but up to about 40% of the radar
  debris area in this box (0.026 against 0.061 km2). Radar debris remains
  the weakest class. Only 0.005 km2 of detections were down-weighted.
- (a) Sentinel-2 with per-pixel cloud masking: 70% of the corridor has clear
  pixels both before and after. The after composite shows the scoured,
  widened channel plainly along both river branches. Optical confirmed
  0.042 km2 of radar detections, disputed 0.004 km2, and ADDED 0.52 km2 of
  debris and 0.031 km2 of water that radar missed. In this gorge most of the
  mapped debris therefore comes from optical, not radar.
- The tile-level cloud figures (54 to 97%) were misleading: they would have
  ruled out every scene, yet most of the valley floor has clear pixels.
- Caveat: the after composite is the median of clear observations over 24
  days after the flood. Water that drained within days is under-represented;
  the optical evidence mostly shows vegetation loss.
- Caveat: Sentinel-2 values are used as delivered by openEO. We did not
  check whether the reflectance offset of newer processing baselines is
  applied. The indices are ratios and thresholds are on differences, so the
  effect should be small, but it is unverified.

### Speed

- Small box, everything cached: 22 s. Small box, cold: about 1.5 min for the
  three new downloads (two at a time). Boxes above 400 km2 now need the
  `--large` flag and use batch jobs.

## OpenStreetMap (ohsome API)

- ohsome holds data up to 27 July 2026, so the snapshot for the Trishuli
  case is 27 July 2026 (before the event, as the rules require).
- The snapshot endpoint named in the docs, `/elements/geometry`, answers
  `403 Forbidden` from the public server (so does `/elements/centroid`),
  while `/elements/count` and `/elementsFullHistory/geometry` work. We use
  the history endpoint of the same API over a one-day window and keep the
  versions still valid at the snapshot date. Check: 2,395 buildings from
  this route, 2,395 from `/elements/count` for the same box and date.
- Risk for judging day: this depends on the ohsome server. OSM layers are
  cached per box, but a new box needs the server to answer.

## Damage overlay, small test box (not validated)

- 144 of 2,395 buildings hit (90 high, 52 medium, 2 low confidence), 4.55 km
  of 160 km of roads, 7 of 16 bridges.
- 134 of the 144 buildings are hit by debris, which is mostly the optical
  vegetation-loss signal. If that signal over-reaches (for example crops or
  cloud shadow missed by the mask), building counts are too high.
- Bridge rule: a bridge is hit only when the hazard reaches the bank at one
  of its ends, or debris covers half the deck. Water change under the span
  alone does not count.

## Full corridor after the changes: the result got WORSE (10 Oct)

Box 85.10 27.85 85.45 28.32. Cold run of the three new downloads took 10.5
minutes (batch jobs, two at a time).

| | First version | Now, radar only | Now, with optical |
|---|---|---|---|
| Water | 0.705 km2 | 1.645 km2 | 2.973 km2 |
| Debris | 1.739 km2 | 5.336 km2 | 21.787 km2 |

These totals are not credible. Three problems, all visible in our own
numbers without any reference map:

1. **Radar debris is almost all noise.** The pre-event pair (4 to 16 Aug, no
   flood) gives 4.977 km2 of "debris" under the same rules, against 5.336
   km2 for the flood pair. So about 93% of radar debris is normal change.
   Radar water is better: 0.261 km2 with no flood against 1.645 km2.
2. **The corridor is far too wide at this scale.** It covers 468 km2, a
   quarter of the box, because every side valley draining 10 km2 counts as a
   river. Hysteresis and the relaxed slope limit then let weak change spread
   through all of it. On the small box the corridor was only 2.7 km2, which
   hid the problem.
3. **Optical vegetation loss over-reaches.** It added 16.45 km2 of debris.
   Optical also disputed more radar area (2.43 km2) than it confirmed (1.47
   km2). Likely causes: crop and seasonal change on valley-floor farmland,
   cloud shadow missed by the scene classification, and the wide corridor.

Lesson: the small-box test looked good and was not representative. Every
change must be checked on the full corridor and against the no-flood pair.

## Fixes for the inflated full-corridor result (10 Oct)

### Bug: the DEM edge fill dammed the river

- The DEM has empty wedges along the box edges (the box is in degrees, the
  grid in UTM). We had filled them with the HIGHEST elevation so water would
  "flow around" them. That built a wall across the river's exit. Flow
  routing then filled the valley behind it into a fake lake, and the whole
  lake surface counted as valley floor.
- Symptom: corridor of 449 km2, and a one-pixel shift of the DEM grid changed
  the largest drainage area from 1,819 to 635 km2.
- Fix: empty cells are now set far BELOW the terrain so rivers drain out.
  Corridor on the full box: 45 km2 (2.4% of the box), stable to grid shifts.

### Other changes

- Rivers are chosen adaptively: streams draining at least 2% of the largest
  drainage area inside the box (31 km2 on the full box, the 5 km2 floor on
  the small box). A fixed 100 km2 value is available as a setting.
- Corridor height limit reduced from 40 m to 20 m above the river.
- Flood-path filter: a detection is kept only if its ground drains into a
  river reach downstream of confident change (radar and optical agreeing on
  at least 0.5 ha, a confident radar water patch of 0.5 ha, or an
  optical-only patch of 2 ha). Isolated side-valley patches are dropped.
- Radar debris is dropped where VV was already swinging in the no-flood pair.
- Optical vegetation loss now needs: clear pixel inside the corridor, green
  before, bare after (NDVI at most 0.3), and bright in both infrared bands
  (rejects cloud and terrain shadow, which is dark in every band).
- Confidence now comes from agreement: radar and optical agree = high,
  optical only = medium, radar-only water with no clear optical view =
  medium, everything else radar-only = low.

### Acceptance test, full box (radar only, same rules on both pairs)

| | Flood pair 16 to 28 Aug | No-flood pair 4 to 16 Aug | Ratio |
|---|---|---|---|
| Water | 1.405 km2 | 0.046 km2 | 31 to 1 |
| Debris | 1.018 km2 | 0.111 km2 | 9 to 1 |

Before the fixes the same test gave debris 5.34 against 4.98 km2 (1.07 to
1). So roughly 3% of radar water and 11% of radar debris can be expected to
be normal change.

### Full-box result after the fixes

- Water 2.392 km2, debris 2.951 km2. By source: radar and optical agree
  1.057 km2, optical only 3.092 km2, radar only 1.164 km2, radar disputed
  by optical 0.029 km2.
- By eye against the Sentinel-2 after-image, the result follows the scoured
  channel in both the lower valley and the upper gorge.
- Still untested: the optical-only class (58% of the mapped area) has no
  no-flood test of its own. A pair of optical composites from before the
  flood would give one.
- The east side river in the lower valley is still mapped as water. It has
  confident radar change of its own, so the flood-path filter keeps it. We
  cannot say whether that is this flood or ordinary monsoon flow.
- An earlier attempt at the flood-path filter that allowed only radar seeds
  removed most of the gorge (small box debris fell to 0.048 km2), because
  radar sees too little there to start a path. Large optical patches were
  added as seeds; small box now 0.040 km2 water and 0.220 km2 debris.
- Limitation: detections UPSTREAM of the uppermost confident patch on a
  river are dropped, since the path is only traced downstream.

## Bridges

- First rule: a bridge was hit if a hazard polygon came within 15 m of either
  end. On a flooded river that is true for nearly every bridge, because the
  ends sit on the banks. It flagged 7 of 16 bridges in the small box, in
  effect "flagged because it crosses the river".
- New rule: only the bank counts. The deck line is extended 10 m past each
  end, onto land, and the bridge is hit only if a hazard polygon covers that
  point (both ends = high, one end = medium). Change under the span is never
  used. A bridge over a changed river with both banks unaffected is reported
  as "exposed", not hit.
- Small box: 3 of 16 hit. Full box: 31 of 217 hit, 4 exposed, 182 clear.
- Limitation: at 10 m pixels a 10 m offset is one pixel. A bridgehead can be
  missed or wrongly included by a one-pixel error.

## Cut-off analysis (not validated)

- Small box: 17 settlements, none cut off, 1 long detour to the hospital.
  No town lies inside the small box, so the test was for a route to a main
  road leaving the box.
- Full box: 182 settlements, 14 cut off (4,037 buildings), 63 with a long
  detour to the town, 6 cut off from every hospital. Runtime 59 s for
  107,135 buildings and 220,000 road edges.
- Only ONE town is mapped inside the full box, so "nearest town" means that
  town for every settlement. Distances of 56 km appear for border villages.
- 29 settlements had no route to the town even before the flood, and 4 are
  further than 500 m from any mapped road. This is incomplete OpenStreetMap
  data (disconnected trails), not flood damage; they are reported
  separately and never counted as cut off.
- All road types count as a connection, including footpaths. A village may
  be "connected" by a trail no vehicle can use.
- Roads outside the box are unknown. A settlement near the edge whose real
  route leaves the box may be wrongly reported.
- One settlement in the list is across the border in China. The box is the
  only input, so the system does not filter by country.

## Optical no-flood acceptance test

Optical rules applied to two composites from before the flood (15 Jun to 21
Jul against 21 Jul to 26 Aug), counted on ground clear in all three
composites (82% of the corridor on the full box, 75% on the small box).

| Full box | Flood pair | No-flood pair | Ratio |
|---|---|---|---|
| Optical debris (vegetation loss) | 2.843 km2 | 0.000 km2 | clean |
| Optical water (new water) | 1.474 km2 | 0.839 km2 | 1.8 to 1 |

- Optical debris passes: the vegetation-loss rule finds nothing when there
  is no flood.
- **Optical water fails.** More than half as much "new water" appears with
  no flood at all. Rivers rise and widen through the monsoon, so "water now,
  not water a month earlier" is true every year. Optical-only water should
  be treated as unreliable until this is fixed (ideas: require the water to
  exceed the no-flood pair locally, as done for radar debris, or demand
  radar agreement for water).
- Small box: 0.000 km2 optical debris and 0.000 km2 optical water on the
  no-flood pair, against 0.208 and 0.020 km2 on the flood pair.

## Validation against EMSR927 (measured once, nothing tuned)

European Union, Copernicus Emergency Management Service data.

Reference: Copernicus EMS rapid mapping grading products, made by photo
interpretation of very high resolution images (0.3 to 1 m) taken on 27 and
28 August. Three of its six areas lie inside our full box. Two areas were
cancelled by EMS for cloud; one lies outside our box. EMS labels the event
"mass movement", not flood water.

Run validated: full box, commit of 10 Oct, default settings. Matching
distances: buildings 15 m, roads 15 m, bridges 30 m.

| Area (reference product) | Ref km2 | Ours km2 | IoU | Precision | Recall |
|---|---|---|---|---|---|
| Syapru Besi (upper gorge) | 1.111 | 0.181 | 0.163 | 0.998 | 0.163 |
| Timure (upper gorge, border) | 1.294 | 0.275 | 0.211 | 0.997 | 0.212 |
| Bidur, first product | 5.886 | 3.368 | 0.437 | 0.835 | 0.478 |
| Bidur, monitoring update | 7.011 | 3.397 | 0.473 | 0.984 | 0.477 |

| Area | Buildings recall | Buildings precision | Roads recall | Roads precision | Bridges recall | Bridges precision |
|---|---|---|---|---|---|---|
| Syapru Besi | 64/355 (0.18) | 35/47 (0.74) | 2.2/6.2 km (0.35) | 0.83 | 2/5 | 2/2 |
| Timure | 67/405 (0.17) | 53/90 (0.59) | 1.6/9.5 km (0.17) | 0.62 | 0/1 | 0/3 |
| Bidur, monitoring update | 1333/2725 (0.49) | 1008/1205 (0.84) | 21.0/41.2 km (0.51) | 0.81 | 14/24 | 16/22 |

Reading the scores:

- **Precision is high, recall is low.** What we map is almost always inside
  the reference area (0.98 to 1.00 against the most complete products), but
  we find only half of it in the wide lower valley and a sixth to a fifth in
  the gorge.
- The gorge is the weak point, as predicted from the radar blind zones. The
  reference deposit there is about 1.1 to 1.3 km2 per area; our corridor
  (ground within 20 m above the river) and strict optical rules capture
  only the core of it.
- Bidur precision is 0.835 against the first product and 0.984 against the
  later update. The update maps more area, so part of our "false" area in
  the first comparison was real damage the first product had not yet mapped.
  A reference map is not complete truth either.
- Building precision in Timure is only 0.59 and bridges there score 0 of 3.
  Part of Timure's reference area is across the border; OSM coverage there
  differs. Not investigated further.
- Building recall is limited twice: by our low extent recall, and because
  the reference counts buildings that are not in OpenStreetMap at all.
- These scores were measured after the design was fixed. Earlier, looser
  settings (40 m corridor, loose optical rule) mapped far more area in the
  gorge and would probably score higher recall here, but they also failed
  our own no-flood tests. We did not go back and loosen them to raise the
  score.

## Cut-off analysis with buffer and two levels (full box)

- Routing network: box plus 15 km. 15 towns and 450 health facilities in
  that area (1 town and 17 before). 780,000 road edges; 1,631 broken.
- No vehicle road: 46 of 182 settlements (12,083 buildings). 45 cut off
  from a town, 28 from every hospital.
- No route at all, even on foot: 8 settlements (2,264 buildings).
- 66 settlements had no vehicle road even before the flood, and 30 had no
  mapped route of any kind. These are reported separately.
- Bridges with the 25 m bank rule: 31 of 217 hit (17 high, 14 medium), 4
  exposed.

## Copernicus service failures seen on 10 Oct

All hit within one afternoon; each one would have broken a live demo.

- `429 Too Many Requests` when several requests ran at once (direct
  downloads and batch job starts). Two optional second-track images were
  silently skipped in one full-box run because of it.
- `500 Internal ... ModuleNotFoundError: No module named 'shapely.lib'`: a
  fault on the Copernicus side, gone on the next try.
- A 180 MB batch result download dropped at 162 MB (`IncompleteRead`).
- Fix: every server request now retries up to six times with a growing wait
  on 429, 5xx and dropped connections. Partial files are written under a
  `.part` name, so a broken download is never taken for a cached file.
- Still a risk on judging day: none of this is under our control.

## Recall work under the false-alarm budget (10 Oct, evening)

Rule agreed with the team: a change is allowed only if it has a physical
reason AND the identical rules, run on images from before the flood, map no
more than 5% of the flood-pair area. No setting is chosen from an EMSR927
score. The tool is `backend/tools/false_alarm_scan.py`.

The acceptance test was rebuilt first: it now runs the WHOLE chain (radar,
optical, growth, flood-path filter) on both pairs, instead of radar and
optical separately. This is stricter and found a problem the separate tests
had hidden.

### What changed and why

1. **Growth from the valley floor replaces the hard 20 m height cap.** A
   debris flood spreads over fans and terraces above the river bed. A
   patch may now extend up to 60 m above the river, but only as one
   connected area of change that starts in the 20 m core.
2. **Second radar track from the opposite side** (orbit 19, descending, 24
   Aug to 5 Sep), with its own layover and shadow mask. Detections from the
   two tracks are united. On the small box the part of the corridor no
   radar can see fell from 23% to 7%.
3. **Optical-only water switched off.** With the full chain on the full box
   and one track, optical-only water was 0.43 km2 on the flood pair and 0.37
   km2 on the no-flood pair: no better than chance. Rivers widen through
   every monsoon. An intermediate rule (keep optical water only where it
   touches other evidence) did not help (0.37 km2 remained). Optical water
   now only confirms radar water.
4. **"Possibly affected" tier for buildings** within 15 m of a polygon but
   not touching it, listed separately from "hit".

### Scans on the full box (one radar track, optical-only water still on)

Reach height, no-flood area as a share of flood-pair area:

| Reach above river | Flood pair km2 | No-flood pair km2 | Share |
|---|---|---|---|
| 20 m | 5.59 | 0.63 | 11.3% |
| 30 m | 6.95 | 0.71 | 10.2% |
| 40 m | 7.51 | 0.83 | 11.1% |
| 60 m | 7.92 | 0.85 | 10.7% |

The reach height hardly moves the false-alarm share: the flood area and the
false area grow together. The excess was the optical water (above).

With optical-only water off, at 60 m reach, minimum size of a VV-only
debris patch:

| Min patch | Flood pair km2 | No-flood pair km2 | Share | In budget |
|---|---|---|---|---|
| 3,000 m2 | 7.43 | 0.36 | 4.9% | yes |
| 10,000 m2 | 7.03 | 0.16 | 2.3% | yes |
| VH rise always required | 6.42 | 0.07 | 1.0% | yes |

On the small box the mapped area stops growing by itself near 120 m of
reach (0.30, 0.71, 0.74, 0.74 km2 at 20, 60, 120, 200 m) with 0.000 km2 on
the no-flood pair at every value.

### Final scans with both radar tracks (full box, optical-only water off)

| Reach | Min VV-only debris patch | Flood pair km2 | No-flood pair km2 | Share | In budget |
|---|---|---|---|---|---|
| 60 m | 3,000 m2 | 9.20 | 0.71 | 7.7% | no |
| 60 m | 10,000 m2 | 8.44 | 0.33 | 3.9% | yes |
| 120 m | 3,000 m2 | 9.40 | 0.71 | 7.6% | no |
| 120 m | 10,000 m2 | 8.62 | 0.33 | 3.8% | yes |

- The second track adds real area but also its own noise, so the 3,000 m2
  debris rule that passed with one track (4.9%) fails with two (7.7%).
- **Chosen defaults: reach 120 m, VV-only debris patch at least 10,000 m2.**
  This is the loosest combination tested that stays within the 5% budget.
- Honest detail: the budget is met on the TOTAL (3.8%). Water alone is at
  7.6% (0.252 of 3.321 km2), debris at 1.4%. The second track's after image
  is from 5 September, ten days after the flood, so part of its water
  change is ordinary river change.
- Small box with the same defaults: 0.696 km2 mapped, 0.000 km2 on the
  no-flood pair.

### EMSR927 before and after the recall work

European Union, Copernicus Emergency Management Service data. Validation was
run once before this work and once after it. Nothing was adjusted between
the second run and this table.

Event extent:

| Area | Recall before | Recall after | Precision before | Precision after | IoU before | IoU after |
|---|---|---|---|---|---|---|
| Syapru Besi (gorge) | 0.163 | 0.381 | 0.998 | 0.992 | 0.163 | 0.379 |
| Timure (gorge, border) | 0.212 | 0.333 | 0.997 | 0.993 | 0.211 | 0.332 |
| Bidur, monitoring update | 0.477 | 0.639 | 0.984 | 0.949 | 0.473 | 0.617 |
| Bidur, first product | 0.478 | 0.641 | 0.835 | 0.804 | 0.437 | 0.554 |

Damage, against "destroyed" and "damaged" in the reference:

| Area | Buildings recall before / after / after incl. "possibly affected" | Buildings precision before / after | Roads recall before / after | Bridges found before / after |
|---|---|---|---|---|
| Syapru Besi | 0.18 / 0.56 / 0.67 | 0.74 / 0.90 | 0.35 / 0.58 | 2 of 5 / 4 of 5 |
| Timure | 0.17 / 0.52 / 0.63 | 0.59 / 0.86 | 0.17 / 0.33 | 0 of 1 / 0 of 1 |
| Bidur (update) | 0.49 / 0.62 / 0.70 | 0.84 / 0.84 | 0.51 / 0.72 | 14 of 24 / 16 of 24 |

- Recall rose everywhere, most in the gorge, and precision stayed above
  0.94 against the most complete reference products.
- The system is still conservative: it finds about a third of the reference
  area in the gorge and two thirds in the lower valley. The remaining gap
  in the gorge is mostly the outer part of the deposit, where no source
  shows a clear change at 10 m.
- Timure bridges: still 0 of 1 found and 0 of 3 of ours confirmed. Not
  investigated.
- The "possibly affected" tier adds 8 to 11 points of building recall for
  3 to 4 points of precision.
