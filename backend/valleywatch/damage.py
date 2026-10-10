"""Step 4: which buildings, roads and bridges did the flood hit?

We lay the pre-event OpenStreetMap features over the water and debris
polygons. Every result carries a confidence level, because a 10 m satellite
pixel cannot prove that a particular house or road is destroyed.

Buildings fall into two tiers:

    hit                 the building overlaps a hazard polygon
                        (high confidence if the polygon is strong,
                        medium if it is weak)
    possibly affected   the building is within 15 m of a polygon but does
                        not touch it (always low confidence)

A polygon is "strong" when its own confidence is medium or high, or when
optical imagery supports it.
"""
import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString

LEVELS = ["low", "medium", "high"]
STRONG_SOURCES = ("radar+optical", "optical")


def _prepare_hazards(hazards, crs):
    hazards = hazards.to_crs(crs).reset_index(drop=True)
    hazards["strong"] = (hazards["confidence_level"].isin(["medium", "high"]) |
                         hazards["source"].isin(STRONG_SOURCES))
    return hazards[["hazard", "strong", "confidence", "geometry"]]


def _level(overlaps, strong):
    """The confidence table from the module description, as a number 0-2."""
    return int(overlaps) + int(strong)


def assess_buildings(buildings, hazards, settings):
    """Mark buildings that overlap a hazard polygon or stand next to one."""
    out = buildings.copy()
    out["status"], out["hit"], out["hazard"], out["confidence_level"] = None, False, None, None
    if buildings.empty or hazards.empty:
        return out
    near = hazards.copy()
    near["geometry"] = hazards.buffer(settings.possibly_affected_m)
    pairs = gpd.sjoin(buildings[["geometry"]], near, predicate="intersects")
    # For each building/polygon pair: does the building touch the polygon
    # itself, or only the 15 m zone around it?
    exact = hazards.geometry.loc[pairs["index_right"]].values
    pairs["overlaps"] = pairs.geometry.intersects(gpd.GeoSeries(exact, index=pairs.index,
                                                                crs=hazards.crs))
    # 0 = possibly affected, 1 = hit by a weak polygon, 2 = hit by a strong one.
    pairs["level"] = pairs["overlaps"].astype(int) * (1 + pairs["strong"].astype(int))
    # Several polygons may touch one building: keep the strongest evidence.
    best = pairs.sort_values("level").groupby(level=0).last()
    out.loc[best.index, "hit"] = best["level"] > 0
    out.loc[best.index, "status"] = best["level"].map(
        lambda v: "hit" if v > 0 else "possibly affected")
    out.loc[best.index, "hazard"] = best["hazard"]
    out.loc[best.index, "confidence_level"] = best["level"].map(lambda v: LEVELS[v])
    return out


def assess_roads(roads, hazards, settings):
    """Return the pieces of (non-bridge) roads that lie inside hazard polygons."""
    columns = ["osm_id", "highway", "name", "hazard", "confidence_level", "length_m", "geometry"]
    if roads.empty or hazards.empty:
        return gpd.GeoDataFrame(columns=columns, geometry="geometry", crs=roads.crs)
    keep = [c for c in ("osm_id", "highway", "name") if c in roads.columns]
    pieces = gpd.overlay(roads[keep + ["geometry"]], hazards, how="intersection",
                         keep_geom_type=True)
    pieces["length_m"] = pieces.length.round(1)
    pieces = pieces[pieces["length_m"] >= settings.min_road_hit_m]
    # A long stretch inside a hazard is firmer evidence than a short clip.
    long_stretch = pieces["length_m"] >= 3 * settings.min_road_hit_m
    pieces["confidence_level"] = [LEVELS[_level(l, s)]
                                  for l, s in zip(long_stretch, pieces["strong"])]
    for column in columns:
        if column not in pieces.columns:
            pieces[column] = None
    return pieces[columns].reset_index(drop=True)


def _approach_segments(line, length_m):
    """The bank beyond each end of a bridge, as two short lines.

    The deck is continued in a straight line past each end for `length_m`.
    These segments lie on land, off the river, where the road meets the bridge.
    """
    coords = list(line.coords)
    segments = []
    for end, inner in ((coords[0], coords[1]), (coords[-1], coords[-2])):
        dx, dy = end[0] - inner[0], end[1] - inner[1]
        norm = (dx ** 2 + dy ** 2) ** 0.5 or 1.0
        far = (end[0] + dx / norm * length_m, end[1] + dy / norm * length_m)
        segments.append(LineString([end[:2], far]))
    return segments


def assess_bridges(bridges, hazards, settings):
    """Decide which bridges were hit.

    A bridge crosses the river by design, so change in the river under the
    span proves nothing and is never used. We look only at the banks: a 25 m
    stretch beyond each end of the deck. A bank is "covered" when water or
    debris covers most of that stretch, meaning the flood rose above the bank
    at the bridgehead. A stretch rather than a single point is used so that
    a one-pixel error cannot decide the result.

        both banks covered    hit, high confidence
        one bank covered      hit, medium confidence
        neither               not hit ("exposed" if the river below
                              changed, "clear" otherwise)
    """
    out = bridges.copy()
    if bridges.empty:
        return out.assign(hit=False, status=None, hazard=None, confidence_level=None, reason=None)
    everything = hazards.union_all() if not hazards.empty else None
    rows = []
    for geometry in out.geometry:
        line = geometry if geometry.geom_type == "LineString" else max(geometry.geoms, key=lambda g: g.length)
        banks_covered = 0
        if everything is not None:
            for bank in _approach_segments(line, settings.bridge_approach_m):
                share = bank.intersection(everything).length / bank.length
                banks_covered += share >= settings.bridge_bank_cover
        river_changed = everything is not None and line.intersects(everything)
        if banks_covered == 2:
            rows.append((True, "hit", "high", "hazard covers the bank at both ends"))
        elif banks_covered == 1:
            rows.append((True, "hit", "medium", "hazard covers the bank at one end"))
        elif river_changed:
            rows.append((False, "exposed", None,
                         "river changed under the span, banks not covered"))
        else:
            rows.append((False, "clear", None, "no change at the bridge"))
    out["hit"] = [r[0] for r in rows]
    out["status"] = [r[1] for r in rows]
    out["confidence_level"] = [r[2] for r in rows]
    out["reason"] = [r[3] for r in rows]
    # Name the hazard nearest to each hit bridge.
    out["hazard"] = None
    if out["hit"].any():
        nearest = gpd.sjoin_nearest(out[out["hit"]][["geometry"]], hazards[["hazard", "geometry"]])
        out.loc[out["hit"], "hazard"] = nearest.groupby(level=0)["hazard"].first()
    out["length_m"] = out.length.round(1)
    return out


def assess_damage(hazards, layers, crs, settings):
    """Overlay all OSM layers on the hazard polygons.

    hazards: polygons from Step 2/3 (any CRS). layers: output of
    osm.fetch_osm_layers. crs: a metric CRS (the UTM zone of the area).
    Returns GeoDataFrames in WGS84 and a totals dict.
    """
    hazards = _prepare_hazards(hazards, crs)
    buildings = layers["buildings"].to_crs(crs)
    roads = layers["roads"].to_crs(crs)
    is_bridge = (roads["bridge"].notna() & (roads["bridge"] != "no")
                 if "bridge" in roads.columns else pd.Series(False, index=roads.index))

    buildings = assess_buildings(buildings, hazards, settings)
    road_hits = assess_roads(roads[~is_bridge], hazards, settings)
    bridges = assess_bridges(roads[is_bridge], hazards, settings)

    def by_level(frame):
        counts = frame["confidence_level"].value_counts()
        return {level: int(counts.get(level, 0)) for level in reversed(LEVELS)}

    hit_buildings, hit_bridges = buildings[buildings["hit"]], bridges[bridges["hit"]]
    possible_buildings = buildings[buildings["status"] == "possibly affected"]
    totals = {
        "buildings_total": int(len(buildings)),
        "buildings_hit": int(len(hit_buildings)),
        "buildings_hit_by_confidence": by_level(hit_buildings),
        "buildings_hit_by_hazard": hit_buildings["hazard"].value_counts().to_dict(),
        "buildings_possibly_affected": int(len(possible_buildings)),
        "roads_total_km": round(float(roads.length.sum()) / 1000, 2),
        "roads_hit_km": round(float(road_hits["length_m"].sum()) / 1000, 2),
        "roads_hit_sections": int(len(road_hits)),
        "roads_hit_sections_by_confidence": by_level(road_hits),
        "bridges_total": int(len(bridges)),
        "bridges_hit": int(len(hit_bridges)),
        "bridges_hit_by_confidence": by_level(hit_bridges),
        # Bridges over a changed river whose banks show no change: not hit.
        "bridges_exposed_not_hit": int((bridges["status"] == "exposed").sum()),
    }
    building_columns = [c for c in ("osm_id", "building", "name", "status", "hit", "hazard",
                                    "confidence_level", "geometry") if c in buildings.columns]
    bridge_columns = [c for c in ("osm_id", "highway", "name", "hit", "status", "hazard",
                                  "confidence_level", "reason", "length_m", "geometry")
                      if c in bridges.columns]
    return {
        # Both tiers are written; the "status" column tells them apart.
        "buildings_hit": pd.concat([hit_buildings, possible_buildings])[building_columns].to_crs(4326),
        "road_hits": road_hits.to_crs(4326),
        "bridges": bridges[bridge_columns].to_crs(4326),
        "totals": totals,
    }
