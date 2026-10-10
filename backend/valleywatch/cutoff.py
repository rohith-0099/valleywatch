"""Step 5: which settlements lost their road connection?

1. Build a graph from the pre-event OpenStreetMap roads: every road vertex is
   a node, every piece of road between two vertices is an edge with a length.
2. Remove the edges the flood hit (road sections inside hazard polygons, and
   bridges judged hit).
3. For every settlement inside the box, look for a route to the nearest town
   and to the nearest hospital, before and after.

Two levels are reported, because they mean different things to a rescuer:

* "vehicle": only roads a vehicle can use. Losing this means no ambulance
  or truck can drive in.
* "any": footpaths and trails count too. Losing this means there is no
  mapped way in or out at all.

The nearest town or hospital is often outside the box. So the network is the
full road map inside the box plus the MAIN roads, towns and hospitals of a
wider area around it. The flood is only mapped inside the box, so roads in
the surrounding buffer are ASSUMED INTACT. A settlement whose only way out
of the box is a minor road is reported as "no route before the flood"
rather than as cut off, because we cannot follow that road further.
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
# Ways a vehicle cannot use. Tracks stay in: jeeps and tractors drive them.
FOOT_ONLY = ("path", "footway", "steps", "bridleway", "pedestrian", "cycleway", "corridor")
LEVELS = ("vehicle", "any")
DESTINATIONS = ("town", "hospital")
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
    edges = gpd.GeoDataFrame(records, columns=["a", "b", "osm_id", "highway", "geometry"],
                             geometry="geometry", crs=roads.crs)
    return graph, edges


def vehicle_only(graph):
    """The same network without footpaths and trails."""
    keep = [(a, b) for a, b, highway in graph.edges(data="highway") if highway not in FOOT_ONLY]
    return graph.edge_subgraph(keep).copy()


def find_broken_edges(edges, road_hits, bridges):
    """Edges the flood made impassable: {(a, b): reason}."""
    broken = {}
    if len(road_hits) and len(edges):
        # A 2 m margin absorbs rounding when the hit sections were cut out.
        zones = gpd.GeoDataFrame(geometry=road_hits.buffer(2.0), crs=road_hits.crs)
        for _, edge in gpd.sjoin(edges, zones, predicate="intersects").iterrows():
            broken[(edge["a"], edge["b"])] = "road section inside hazard"
    hit_bridge_ids = set(bridges.loc[bridges["hit"].astype(bool), "osm_id"]) if len(bridges) else set()
    for _, edge in edges[edges["osm_id"].isin(hit_bridge_ids)].iterrows():
        broken[(edge["a"], edge["b"])] = "bridge hit"
    return broken


def _snap(points, graph, max_distance):
    """Nearest graph node for each point (missing when no road is close)."""
    if not len(points) or graph.number_of_nodes() == 0:
        return pd.Series([None] * len(points), index=points.index, dtype=object)
    nodes = list(graph.nodes)
    node_points = gpd.GeoDataFrame({"node": nodes},
                                   geometry=[Point(n) for n in nodes], crs=points.crs)
    joined = gpd.sjoin_nearest(points[["geometry"]], node_points, max_distance=max_distance)
    joined = joined[~joined.index.duplicated()]
    return joined["node"].reindex(points.index)


def _area_exits(graph, edges, area_polygon, margin_m=150.0):
    """Nodes where a main road leaves the fetched area."""
    main = edges[edges["highway"].isin(MAIN_ROADS)]
    near_edge = main[main.distance(area_polygon.exterior) <= margin_m]
    return list({node for node in pd.concat([near_edge["a"], near_edge["b"]]) if node in graph})


def _routes_to_nearest(graph, destinations):
    """Shortest distance and route from every node to its nearest destination.

    One search from a helper node joined to all destinations at zero cost
    gives the nearest destination of every node at once.
    Returns (predecessors, distance); both empty without destinations.
    """
    destinations = [n for n in destinations if n in graph]
    if not destinations:
        return {}, {}
    work = graph.copy()
    for node in destinations:
        work.add_edge(HUB, node, length=0.0)
    return nx.dijkstra_predecessor_and_distance(work, HUB, weight="length")


def _path_from(node, predecessors):
    """Nodes from `node` to its destination, following the search tree."""
    path = [node]
    while predecessors.get(path[-1]):
        step = predecessors[path[-1]][0]
        if step == HUB:
            break
        path.append(step)
    return path


def _is_missing(node):
    return node is None or (isinstance(node, float) and pd.isna(node))


def settlements_from_buildings(buildings, settings):
    """Stand-in settlements where the map has no settlement points.

    Buildings closer together than `cluster_distance_m` are grouped; each
    group of enough buildings becomes one settlement at the group's centre.
    These are marked as derived and have no name.
    """
    centres = buildings.geometry.centroid
    # Circles of half the distance touch exactly when two buildings are
    # within the full distance of each other; merged circles are the groups.
    merged = centres.buffer(settings.cluster_distance_m / 2).union_all()
    groups = list(merged.geoms) if merged.geom_type == "MultiPolygon" else [merged]
    areas = gpd.GeoDataFrame(geometry=groups, crs=buildings.crs)
    members = gpd.sjoin(gpd.GeoDataFrame(geometry=centres, crs=buildings.crs), areas,
                        predicate="within")
    rows = []
    for group, part in members.groupby("index_right"):
        if len(part) >= settings.cluster_min_buildings:
            rows.append({"osm_id": f"derived/{len(rows) + 1}", "name": None,
                         "place": "derived from buildings", "derived": True,
                         "geometry": part.geometry.union_all().centroid})
    return gpd.GeoDataFrame(rows, columns=["osm_id", "name", "place", "derived", "geometry"],
                            geometry="geometry", crs=buildings.crs)


def analyse_cutoff(layers, routing_layers, road_hits, bridges, bbox, crs, settings):
    """Run the cut-off analysis.

    layers: pre-event OSM layers of the box (all roads, places, buildings).
    routing_layers: main roads, towns and health for the box plus its buffer.
    road_hits / bridges: output of Step 4 (inside the box only).
    Returns GeoDataFrames in WGS84 ('settlements', 'broken_links',
    'lost_routes') and a totals dict.
    """
    # Every road inside the box, plus the main roads around it.
    roads = pd.concat([layers["roads"], routing_layers["roads"]], ignore_index=True).to_crs(crs)
    box_places = layers["places"].to_crs(crs)
    wide_places = routing_layers["places"].to_crs(crs)
    health = routing_layers["health"].to_crs(crs).copy()
    health["geometry"] = health.geometry.centroid  # hospitals mapped as outlines
    buildings = layers["buildings"].to_crs(crs)
    road_hits, bridges = road_hits.to_crs(crs), bridges.to_crs(crs)
    box_polygon = gpd.GeoSeries([box(*bbox)], crs=4326).to_crs(crs).iloc[0]
    fetched_area = roads.total_bounds if len(roads) else box_polygon.bounds
    fetched_polygon = box(*fetched_area)

    graph_any, edges = build_road_graph(roads)
    broken = find_broken_edges(edges, road_hits, bridges)
    graphs = {"any": graph_any, "vehicle": vehicle_only(graph_any)}

    def of_kind(places, kinds):
        if "place" not in places.columns:
            return places.iloc[0:0]
        return places[places["place"].isin(kinds)]

    # Settlements are judged only inside the box, where the flood was mapped.
    settlements = of_kind(box_places, SETTLEMENT_PLACES)
    settlements = settlements[settlements.within(box_polygon)].copy()
    settlements["derived"] = False
    settlement_source = "OpenStreetMap place points"
    if settlements.empty and len(buildings):
        # No settlement points mapped here: fall back to building clusters.
        settlements = settlements_from_buildings(buildings, settings)
        settlements = settlements[settlements.within(box_polygon)].copy()
        settlement_source = "derived by clustering OpenStreetMap buildings (no place points mapped)"
    towns = of_kind(wide_places, TOWN_PLACES)

    # Size of each settlement: buildings closest to it, within a radius.
    settlements["buildings"] = 0
    if len(settlements) and len(buildings):
        centres = buildings.copy()
        centres["geometry"] = buildings.geometry.centroid
        nearest = gpd.sjoin_nearest(centres[["geometry"]], settlements[["geometry"]],
                                    max_distance=settings.settlement_radius_m)
        nearest = nearest[~nearest.index.duplicated()]
        counts = nearest.groupby("index_right").size()
        settlements["buildings"] = counts.reindex(settlements.index).fillna(0).astype(int)

    # One search per level, destination and state of the network.
    searches, snapped, town_target = {}, {}, "nearest town"
    for level, graph in graphs.items():
        damaged = graph.copy()
        damaged.remove_edges_from(broken.keys())
        town_nodes = list(_snap(towns, graph, settings.max_snap_distance_m).dropna())
        if not town_nodes:
            # No town even in the wider area: aim for a main road leaving it.
            town_nodes = _area_exits(graph, edges, fetched_polygon)
            town_target = "main road leaving the mapped area (no town found)"
        hospital_nodes = list(_snap(health, graph, settings.max_snap_distance_m).dropna())
        for name, nodes in (("town", town_nodes), ("hospital", hospital_nodes)):
            searches[level, name] = (_routes_to_nearest(graph, nodes),
                                     _routes_to_nearest(damaged, nodes))
        snapped[level] = _snap(settlements, graph, settings.max_snap_distance_m)

    rows, link_rows, route_rows = [], [], []
    for index, place in settlements.iterrows():
        row = {"osm_id": place.get("osm_id"), "name": place.get("name"),
               "name_en": place.get("name:en"), "place": place.get("place"),
               "derived": bool(place.get("derived", False)),
               "buildings": int(place["buildings"]), "geometry": place.geometry}
        for level in LEVELS:
            node = snapped[level].get(index)
            for name in DESTINATIONS:
                (pred_before, dist_before), (_, dist_after) = searches[level, name]
                key = f"{level}_{name}"
                before = None if _is_missing(node) else dist_before.get(node)
                after = dist_after.get(node) if before is not None else None
                if not dist_before:
                    status = "no destination mapped"
                elif _is_missing(node):
                    status = "not on this network"
                elif before is None:
                    status = "no route before the flood"
                elif after is None:
                    status = "cut off"
                elif (after >= settings.detour_factor * before and
                      after - before >= settings.detour_min_extra_km * 1000):
                    status = "connected, long detour"
                else:
                    status = "connected"
                row[f"{key}_status"] = status
                row[f"{key}_km_before"] = round(before / 1000, 2) if before is not None else None
                row[f"{key}_km_after"] = round(after / 1000, 2) if after is not None else None

                if status == "cut off":
                    # Walk the old route outward from the settlement. The first
                    # broken edge on it is the link whose loss isolates the place.
                    path = _path_from(node, pred_before)
                    if len(path) > 1:
                        route_rows.append({"settlement": row["osm_id"], "level": level,
                                           "to": name, "geometry": LineString(path)})
                    for a, b in zip(path[:-1], path[1:]):
                        reason = broken.get((a, b)) or broken.get((b, a))
                        if reason:
                            data = graph_any.edges[a, b]
                            row[f"{key}_broken_link"] = data["osm_id"]
                            link_rows.append({"settlement": row["osm_id"], "level": level,
                                              "to": name, "osm_id": data["osm_id"],
                                              "highway": data["highway"], "reason": reason,
                                              "geometry": LineString([a, b])})
                            break
            row[f"cut_off_{level}"] = "cut off" in (row[f"{level}_town_status"],
                                                    row[f"{level}_hospital_status"])
        rows.append(row)

    columns = ["osm_id", "name", "name_en", "place", "derived", "buildings", "cut_off_any",
               "cut_off_vehicle"]
    for level in LEVELS:
        for name in DESTINATIONS:
            columns += [f"{level}_{name}_{suffix}"
                        for suffix in ("status", "km_before", "km_after", "broken_link")]
    result = gpd.GeoDataFrame(rows, columns=columns + ["geometry"], geometry="geometry", crs=crs)
    # Worst first: no route at all, then no vehicle road, then by size.
    result = result.sort_values(["cut_off_any", "cut_off_vehicle", "buildings"],
                                ascending=False).reset_index(drop=True)
    links = gpd.GeoDataFrame(link_rows, columns=["settlement", "level", "to", "osm_id", "highway",
                                                 "reason", "geometry"], geometry="geometry", crs=crs)
    routes = gpd.GeoDataFrame(route_rows, columns=["settlement", "level", "to", "geometry"],
                              geometry="geometry", crs=crs)

    def count(column, status):
        return int((result[column] == status).sum()) if len(result) else 0

    def flagged(column):
        return result[result[column].astype(bool)] if len(result) else result

    totals = {
        "settlements_in_box": int(len(result)),
        "settlement_source": settlement_source,
        "no_vehicle_road": {
            "settlements": int(len(flagged("cut_off_vehicle"))),
            "buildings": int(flagged("cut_off_vehicle")["buildings"].sum()),
            "cut_off_from_town": count("vehicle_town_status", "cut off"),
            "cut_off_from_hospital": count("vehicle_hospital_status", "cut off"),
            "long_detour_to_town": count("vehicle_town_status", "connected, long detour"),
            "long_detour_to_hospital": count("vehicle_hospital_status", "connected, long detour"),
            "had_no_vehicle_road_before": count("vehicle_town_status", "no route before the flood")
                                          + count("vehicle_town_status", "not on this network"),
        },
        "no_route_at_all": {
            "settlements": int(len(flagged("cut_off_any"))),
            "buildings": int(flagged("cut_off_any")["buildings"].sum()),
            "cut_off_from_town": count("any_town_status", "cut off"),
            "cut_off_from_hospital": count("any_hospital_status", "cut off"),
            "long_detour_to_town": count("any_town_status", "connected, long detour"),
            "long_detour_to_hospital": count("any_hospital_status", "connected, long detour"),
            "had_no_route_before": count("any_town_status", "no route before the flood")
                                   + count("any_town_status", "not on this network"),
        },
        "town_destination": town_target,
        "towns_in_routing_area": int(len(towns)),
        "hospitals_in_routing_area": int(len(health)),
        "routing_buffer_km": settings.routing_buffer_km,
        "roads_outside_box": "assumed intact (the flood is only mapped inside the box)",
        "road_edges_total": graph_any.number_of_edges(),
        "road_edges_broken": len(broken),
    }
    return {"settlements": result.to_crs(4326), "broken_links": links.to_crs(4326),
            "lost_routes": routes.to_crs(4326), "totals": totals}
