"""Step 5: which settlements lost their road connection?

1. Build a graph from the pre-event OpenStreetMap roads: every road vertex is
   a node, every piece of road between two vertices is an edge with a length.
2. Remove the edges the flood hit (road sections inside hazard polygons, and
   bridges judged hit).
3. For every settlement, look for a route to the nearest town and to the
   nearest hospital, before and after. A settlement that had a route and has
   none now is cut off.

"Town" needs care on a small map: the nearest town is often outside the
chosen box. In that case we test for a route to a main road that leaves the
box instead, and say so in the output.
"""
import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
from shapely.geometry import LineString, Point, box

SETTLEMENT_PLACES = ("village", "hamlet", "isolated_dwelling")
TOWN_PLACES = ("town", "city")
MAIN_ROADS = ("motorway", "trunk", "primary", "secondary", "tertiary")
NOT_ROADS = ("proposed", "construction", "abandoned", "razed")
HUB = "all destinations"  # helper node linked to every destination


def _node(coord):
    """Node key: coordinates rounded to 10 cm, so shared OSM nodes match."""
    return (round(coord[0], 1), round(coord[1], 1))


def build_road_graph(roads):
    """Graph of the road network. Returns (graph, GeoDataFrame of edges)."""
    graph, records = nx.Graph(), []
    for osm_id, highway, geometry in zip(roads["osm_id"], roads["highway"], roads.geometry):
        if highway in NOT_ROADS:
            continue
        lines = [geometry] if geometry.geom_type == "LineString" else list(geometry.geoms)
        for line in lines:
            coords = list(line.coords)
            for start, end in zip(coords[:-1], coords[1:]):
                a, b = _node(start), _node(end)
                if a == b:
                    continue
                length = float(np.hypot(a[0] - b[0], a[1] - b[1]))
                graph.add_edge(a, b, length=length, osm_id=osm_id, highway=highway)
                records.append({"a": a, "b": b, "osm_id": osm_id, "highway": highway,
                                "geometry": LineString([a, b])})
    edges = gpd.GeoDataFrame(records, geometry="geometry", crs=roads.crs)
    return graph, edges


def find_broken_edges(edges, road_hits, bridges):
    """Edges the flood made impassable, as a set of (a, b) node pairs."""
    broken = {}
    if len(road_hits):
        # A 2 m margin absorbs rounding when the hit sections were cut out.
        zones = gpd.GeoDataFrame(geometry=road_hits.buffer(2.0), crs=road_hits.crs)
        for _, edge in gpd.sjoin(edges, zones, predicate="intersects").iterrows():
            broken[(edge["a"], edge["b"])] = "road section inside hazard"
    hit_bridge_ids = set(bridges.loc[bridges["hit"], "osm_id"])
    for _, edge in edges[edges["osm_id"].isin(hit_bridge_ids)].iterrows():
        broken[(edge["a"], edge["b"])] = "bridge hit"
    return broken


def _snap(points, graph, max_distance):
    """Nearest graph node for each point (None when no road is close)."""
    nodes = list(graph.nodes)
    node_points = gpd.GeoDataFrame({"node": nodes},
                                   geometry=[Point(n) for n in nodes], crs=points.crs)
    joined = gpd.sjoin_nearest(points[["geometry"]], node_points, max_distance=max_distance,
                               distance_col="snap_m")
    joined = joined[~joined.index.duplicated()]
    return joined["node"].reindex(points.index)


def _box_exits(graph, edges, bbox_polygon, margin_m=150.0):
    """Nodes where a main road leaves the box (within `margin_m` of its edge)."""
    main = edges[edges["highway"].isin(MAIN_ROADS)]
    near_edge = main[main.distance(bbox_polygon.exterior) <= margin_m]
    return list({node for node in pd.concat([near_edge["a"], near_edge["b"]]) if node in graph})


def _routes_to_nearest(graph, destinations):
    """Shortest distance and route from every node to its nearest destination.

    One search from a helper node joined to all destinations at zero cost
    gives the nearest destination of every node at once.
    """
    if not destinations:
        return {}, {}
    work = graph.copy()
    work.add_node(HUB)
    for node in destinations:
        work.add_edge(HUB, node, length=0.0)
    predecessors, distance = nx.dijkstra_predecessor_and_distance(work, HUB, weight="length")
    return predecessors, distance


def _path_from(node, predecessors):
    """Nodes from `node` to its destination, following the search tree."""
    path = [node]
    while predecessors.get(path[-1]):
        step = predecessors[path[-1]][0]
        if step == HUB:
            break
        path.append(step)
    return path


def analyse_cutoff(layers, road_hits, bridges, bbox, crs, settings):
    """Run the cut-off analysis.

    layers: pre-event OSM layers. road_hits / bridges: output of Step 4.
    bbox: (W, S, E, N) in degrees. crs: metric CRS of the area.
    Returns GeoDataFrames in WGS84 ('settlements', 'broken_links',
    'lost_routes') and a totals dict.
    """
    roads = layers["roads"].to_crs(crs)
    places = layers["places"].to_crs(crs)
    buildings = layers["buildings"].to_crs(crs)
    health = layers["health"].to_crs(crs).copy()
    health["geometry"] = health.geometry.centroid  # hospitals mapped as outlines
    road_hits, bridges = road_hits.to_crs(crs), bridges.to_crs(crs)
    bbox_polygon = gpd.GeoSeries([box(*bbox)], crs=4326).to_crs(crs).iloc[0]

    graph, edges = build_road_graph(roads)
    broken = find_broken_edges(edges, road_hits, bridges)
    damaged = graph.copy()
    damaged.remove_edges_from(broken.keys())

    place_kind = places["place"] if "place" in places.columns else pd.Series(dtype=str)
    settlements = places[place_kind.isin(SETTLEMENT_PLACES)].copy()
    towns = places[place_kind.isin(TOWN_PLACES)]

    # Destinations. With no town inside the box, use main roads leaving it.
    town_nodes = [n for n in _snap(towns, graph, settings.max_snap_distance_m).dropna()] \
        if len(towns) else []
    town_target = "nearest town"
    if not town_nodes:
        town_nodes = _box_exits(graph, edges, bbox_polygon)
        town_target = "main road leaving the area (no town inside the area)"
    hospital_nodes = [n for n in _snap(health, graph, settings.max_snap_distance_m).dropna()] \
        if len(health) else []

    searches = {}
    for name, nodes in (("town", town_nodes), ("hospital", hospital_nodes)):
        searches[name] = {"before": _routes_to_nearest(graph, nodes),
                          "after": _routes_to_nearest(damaged, nodes)}

    # Size of each settlement: buildings closest to it, within a radius.
    settlements["buildings"] = 0
    if len(settlements) and len(buildings):
        centres = buildings.copy()
        centres["geometry"] = buildings.geometry.centroid
        nearest = gpd.sjoin_nearest(centres[["geometry"]], settlements[["geometry"]],
                                    max_distance=settings.settlement_radius_m)
        counts = nearest.groupby("index_right").size()
        settlements["buildings"] = counts.reindex(settlements.index).fillna(0).astype(int)

    settlements["node"] = _snap(settlements, graph, settings.max_snap_distance_m) \
        if len(settlements) else None
    rows, link_rows, route_rows = [], [], []
    for index, place in settlements.iterrows():
        node = place["node"]
        row = {"osm_id": place.get("osm_id"), "name": place.get("name"),
               "name_en": place.get("name:en"), "place": place.get("place"),
               "buildings": int(place["buildings"]), "geometry": place.geometry}
        for name in ("town", "hospital"):
            (pred_before, dist_before), (_, dist_after) = (
                searches[name]["before"], searches[name]["after"])
            has_destination = bool(dist_before)
            before = dist_before.get(node) if node is not None and not pd.isna(node) else None
            after = dist_after.get(node) if before is not None else None
            if not has_destination:
                status = "no destination mapped in the area"
            elif node is None or (isinstance(node, float) and pd.isna(node)):
                status = "not on the mapped road network"
            elif before is None:
                status = "no route before the flood"
            elif after is None:
                status = "cut off"
            elif (after >= settings.detour_factor * before and
                  after - before >= settings.detour_min_extra_km * 1000):
                status = "connected, long detour"
            else:
                status = "connected"
            row[f"{name}_status"] = status
            row[f"{name}_km_before"] = round(before / 1000, 2) if before is not None else None
            row[f"{name}_km_after"] = round(after / 1000, 2) if after is not None else None

            if status == "cut off":
                # Walk the old route outward from the settlement. The first
                # broken edge on it is the link whose loss isolates the place.
                path = _path_from(node, pred_before)
                route_rows.append({"settlement": row["osm_id"], "to": name,
                                   "geometry": LineString(path) if len(path) > 1 else None})
                for a, b in zip(path[:-1], path[1:]):
                    reason = broken.get((a, b)) or broken.get((b, a))
                    if reason:
                        data = graph.edges[a, b]
                        row[f"{name}_broken_link"] = data["osm_id"]
                        link_rows.append({"settlement": row["osm_id"], "to": name,
                                          "osm_id": data["osm_id"], "highway": data["highway"],
                                          "reason": reason, "geometry": LineString([a, b])})
                        break
        row["cut_off"] = "cut off" in (row["town_status"], row["hospital_status"])
        rows.append(row)

    columns = ["osm_id", "name", "name_en", "place", "buildings", "cut_off",
               "town_status", "town_km_before", "town_km_after", "town_broken_link",
               "hospital_status", "hospital_km_before", "hospital_km_after",
               "hospital_broken_link", "geometry"]
    result = gpd.GeoDataFrame(rows, columns=columns, geometry="geometry", crs=crs)
    # Largest cut-off settlements first, so rescuers see them at the top.
    result = result.sort_values(["cut_off", "buildings"], ascending=[False, False]).reset_index(drop=True)
    links = gpd.GeoDataFrame(link_rows, columns=["settlement", "to", "osm_id", "highway",
                                                 "reason", "geometry"], geometry="geometry", crs=crs)
    routes = gpd.GeoDataFrame([r for r in route_rows if r["geometry"] is not None],
                              columns=["settlement", "to", "geometry"], geometry="geometry", crs=crs)

    def count(column, status):
        return int((result[column] == status).sum())

    totals = {
        "settlements": int(len(result)),
        "settlements_cut_off": int(result["cut_off"].sum()),
        "buildings_in_cut_off_settlements": int(result.loc[result["cut_off"], "buildings"].sum()),
        "town_destination": town_target,
        "town_destinations_found": len(town_nodes),
        "hospitals_found": len(hospital_nodes),
        "cut_off_from_town": count("town_status", "cut off"),
        "cut_off_from_hospital": count("hospital_status", "cut off"),
        "long_detour_to_town": count("town_status", "connected, long detour"),
        "long_detour_to_hospital": count("hospital_status", "connected, long detour"),
        "not_on_road_network": count("town_status", "not on the mapped road network"),
        "no_route_before_flood_to_town": count("town_status", "no route before the flood"),
        "road_edges_total": graph.number_of_edges(),
        "road_edges_broken": len(broken),
    }
    return {"settlements": result.to_crs(4326), "broken_links": links.to_crs(4326),
            "lost_routes": routes.to_crs(4326), "totals": totals}
