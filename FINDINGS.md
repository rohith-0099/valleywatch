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
