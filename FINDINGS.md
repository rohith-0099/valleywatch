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
