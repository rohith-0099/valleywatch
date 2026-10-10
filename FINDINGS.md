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
