"""Step 4: which buildings, roads and bridges did the flood hit?

We lay the pre-event OpenStreetMap features over the water and debris
polygons. Every hit gets a confidence level, because a 10 m satellite pixel
cannot prove that a particular house or road is destroyed.

Confidence rule (same for buildings and roads):

    hazard polygon is ...        feature overlaps it     feature only near it
    strong                       high                    medium
    weak                         medium                  low

A polygon is "strong" when its own confidence is medium or high, or when
optical imagery supports it.
"""
import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

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
    """Mark buildings that overlap or lie next to a hazard polygon."""
    if buildings.empty or hazards.empty:
        return buildings.assign(hit=False, hazard=None, confidence_level=None)
    near = hazards.copy()
    near["geometry"] = hazards.buffer(settings.feature_tolerance_m)
    pairs = gpd.sjoin(buildings[["geometry"]], near, predicate="intersects")
    # For each building/polygon pair: does the building touch the polygon
    # itself, or only its tolerance zone?
    exact = hazards.geometry.loc[pairs["index_right"]].values
    pairs["overlaps"] = pairs.geometry.intersects(gpd.GeoSeries(exact, index=pairs.index,
                                                                crs=hazards.crs))
    pairs["level"] = [_level(o, s) for o, s in zip(pairs["overlaps"], pairs["strong"])]
    # Several polygons may touch one building: keep the strongest evidence.
    best = pairs.sort_values("level").groupby(level=0).last()
    out = buildings.copy()
    out["hit"] = out.index.isin(best.index)
    out["hazard"] = best["hazard"].reindex(out.index)
    out["confidence_level"] = best["level"].map(lambda v: LEVELS[v]).reindex(out.index)
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


def assess_bridges(bridges, hazards, settings):
    """Decide which bridges were hit.

    A bridge crosses the river by design, so change in the water underneath
    proves nothing. We call a bridge hit only when the hazard reaches the
    ground at one of its ends (where the deck meets the bank), or when debris
    covers a large part of the deck itself.
    """
    out = bridges.copy()
    if bridges.empty:
        return out.assign(hit=False, hazard=None, confidence_level=None, reason=None)
    everything = hazards.union_all() if not hazards.empty else None
    debris = hazards[hazards["hazard"] == "debris"]
    debris_area = debris.union_all() if not debris.empty else None
    rows = []
    for geometry in out.geometry:
        line = geometry if geometry.geom_type == "LineString" else max(geometry.geoms, key=lambda g: g.length)
        ends = [Point(line.coords[0]), Point(line.coords[-1])]
        ends_hit = sum(everything is not None and
                       end.buffer(settings.bridge_end_radius_m).intersects(everything)
                       for end in ends)
        covered = (line.intersection(debris_area).length / line.length
                   if debris_area is not None and line.length > 0 else 0.0)
        if ends_hit == 2:
            rows.append((True, "high", "hazard reaches both ends"))
        elif ends_hit == 1:
            rows.append((True, "medium", "hazard reaches one end"))
        elif covered >= settings.bridge_debris_cover:
            rows.append((True, "low", "debris signal over the deck only"))
        else:
            rows.append((False, None, "no change at either end"))
    out["hit"] = [r[0] for r in rows]
    out["confidence_level"] = [r[1] for r in rows]
    out["reason"] = [r[2] for r in rows]
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
    totals = {
        "buildings_total": int(len(buildings)),
        "buildings_hit": int(len(hit_buildings)),
        "buildings_hit_by_confidence": by_level(hit_buildings),
        "buildings_hit_by_hazard": hit_buildings["hazard"].value_counts().to_dict(),
        "roads_total_km": round(float(roads.length.sum()) / 1000, 2),
        "roads_hit_km": round(float(road_hits["length_m"].sum()) / 1000, 2),
        "roads_hit_sections": int(len(road_hits)),
        "roads_hit_sections_by_confidence": by_level(road_hits),
        "bridges_total": int(len(bridges)),
        "bridges_hit": int(len(hit_bridges)),
        "bridges_hit_by_confidence": by_level(hit_bridges),
    }
    building_columns = [c for c in ("osm_id", "building", "name", "hit", "hazard",
                                    "confidence_level", "geometry") if c in buildings.columns]
    bridge_columns = [c for c in ("osm_id", "highway", "name", "hit", "hazard",
                                  "confidence_level", "reason", "length_m", "geometry")
                      if c in bridges.columns]
    return {
        "buildings_hit": hit_buildings[building_columns].to_crs(4326),
        "road_hits": road_hits.to_crs(4326),
        "bridges": bridges[bridge_columns].to_crs(4326),
        "totals": totals,
    }
