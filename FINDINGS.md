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
