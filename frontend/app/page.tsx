"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import type { GeoJSONSource, Map as MapLibreMap } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// Result layers served by the API, in drawing order (bottom first).
const DATA_LAYERS = ["flood_debris", "road_hits", "lost_routes", "broken_links", "buildings_hit", "bridges", "settlements"] as const;

// Legend entries: label, colour, and the map layer ids each one switches.
const LEGEND = [
  { key: "water", label: "New water", colour: "#2bb6ff", layers: ["water-fill"] },
  { key: "debris", label: "Debris", colour: "#ff8a1f", layers: ["debris-fill"] },
  { key: "buildings", label: "Buildings hit / possibly", colour: "#ff4fd8", layers: ["buildings"] },
  { key: "roads", label: "Road sections hit", colour: "#ffe14d", layers: ["roads"] },
  { key: "bridges", label: "Bridges hit", colour: "#ffffff", layers: ["bridges"] },
  { key: "settlements", label: "Settlements (red = cut off)", colour: "#ff4136", layers: ["settlements", "settlement-pulse"] },
  { key: "links", label: "Broken link and lost route", colour: "#ff4136", layers: ["links", "routes"] },
];

type Summary = Record<string, any>;
type Feature = { properties: Record<string, any>; geometry: any };
type Collection = { type: "FeatureCollection"; features: Feature[] };
const EMPTY: Collection = { type: "FeatureCollection", features: [] };

function boundsOf(collection: Collection): maplibregl.LngLatBounds | null {
  const bounds = new maplibregl.LngLatBounds();
  const visit = (coords: any) => (typeof coords[0] === "number" ? bounds.extend(coords as [number, number]) : coords.forEach(visit));
  collection.features.forEach((f) => f.geometry && visit(f.geometry.coordinates));
  return bounds.isEmpty() ? null : bounds;
}

export default function Dashboard() {
  const mapNode = useRef<HTMLDivElement>(null);
  const map = useRef<MapLibreMap | null>(null);
  const layers = useRef<Record<string, Collection>>({});
  const mapReady = useRef(false); // true once the map sources exist

  const [bbox, setBbox] = useState(["", "", "", ""]);
  const [floodDate, setFloodDate] = useState("");
  const [drawing, setDrawing] = useState(false);
  const [thorough, setThorough] = useState(false);
  const [runs, setRuns] = useState<{ run_id: string }[]>([]);
  const [messages, setMessages] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [summary, setSummary] = useState<Summary | null>(null);
  const [settlements, setSettlements] = useState<Feature[]>([]);
  const [picked, setPicked] = useState<string | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [language, setLanguage] = useState<"en" | "ne">("en");
  const [question, setQuestion] = useState("");
  const [asking, setAsking] = useState(false);
  const [chat, setChat] = useState<{ question: string; text: string; verified: boolean; rejected: string[] }[]>([]);
  const [visible, setVisible] = useState<Record<string, boolean>>(Object.fromEntries(LEGEND.map((l) => [l.key, true])));

  const refreshRuns = useCallback(() => {
    fetch(`${API}/api/runs`).then((r) => r.json()).then(setRuns).catch(() => setError("Cannot reach the analysis server."));
  }, []);

  // ---- Map set-up (once) ---------------------------------------------------
  useEffect(() => {
    if (!mapNode.current || map.current) return;
    const m = new maplibregl.Map({
      container: mapNode.current,
      // Display-only base map. The analysis never reads it: it uses the
      // pre-event OpenStreetMap snapshot fetched by the backend.
      style: {
        version: 8,
        sources: { base: { type: "raster", tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"], tileSize: 256, attribution: "Base map (display only) © OpenStreetMap contributors" } },
        layers: [{ id: "base", type: "raster", source: "base", paint: { "raster-saturation": -0.85, "raster-brightness-max": 0.55, "raster-contrast": 0.15 } }],
      },
      center: [85.3, 28.1],
      zoom: 8,
    });
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    m.addControl(new maplibregl.ScaleControl(), "bottom-right");
    map.current = m;

    m.on("load", () => {
      for (const name of [...DATA_LAYERS, "aoi", "highlight"]) m.addSource(name, { type: "geojson", data: EMPTY as any });
      const confidenceOpacity: any = ["match", ["get", "confidence_level"], "high", 0.8, "medium", 0.6, 0.35];
      m.addLayer({ id: "aoi", type: "line", source: "aoi", paint: { "line-color": "#ffd23f", "line-width": 1.5, "line-dasharray": [3, 2] } });
      m.addLayer({ id: "water-fill", type: "fill", source: "flood_debris", filter: ["==", ["get", "hazard"], "water"], paint: { "fill-color": "#2bb6ff", "fill-opacity": confidenceOpacity } });
      m.addLayer({ id: "debris-fill", type: "fill", source: "flood_debris", filter: ["==", ["get", "hazard"], "debris"], paint: { "fill-color": "#ff8a1f", "fill-opacity": confidenceOpacity } });
      m.addLayer({ id: "roads", type: "line", source: "road_hits", paint: { "line-color": "#ffe14d", "line-width": ["match", ["get", "confidence_level"], "high", 4, "medium", 3, 2] } });
      m.addLayer({ id: "routes", type: "line", source: "lost_routes", paint: { "line-color": "#ff4136", "line-width": 1.5, "line-dasharray": [2, 2], "line-opacity": 0.55 } });
      m.addLayer({ id: "links", type: "line", source: "broken_links", paint: { "line-color": "#ff4136", "line-width": 6 } });
      m.addLayer({ id: "buildings", type: "fill", source: "buildings_hit", paint: { "fill-color": "#ff4fd8", "fill-opacity": ["match", ["get", "status"], "hit", 0.9, 0.35], "fill-outline-color": "#ff4fd8" } });
      m.addLayer({ id: "bridges", type: "line", source: "bridges", filter: ["==", ["get", "hit"], true], paint: { "line-color": "#ffffff", "line-width": 5 } });
      m.addLayer({ id: "settlement-pulse", type: "circle", source: "settlements", filter: ["any", ["==", ["get", "cut_off_any"], true], ["==", ["get", "cut_off_vehicle"], true]], paint: { "circle-radius": 14, "circle-color": "#ff4136", "circle-opacity": 0.25 } });
      m.addLayer({ id: "settlements", type: "circle", source: "settlements", paint: { "circle-radius": ["interpolate", ["linear"], ["get", "buildings"], 0, 4, 1000, 10], "circle-stroke-width": 1.5, "circle-stroke-color": "#0d1315", "circle-color": ["case", ["==", ["get", "cut_off_any"], true], "#ff4136", ["==", ["get", "cut_off_vehicle"], true], "#ffd23f", "#5fd38d"] } });
      m.addLayer({ id: "highlight", type: "line", source: "highlight", paint: { "line-color": "#ffffff", "line-width": 3 } });

      mapReady.current = true;

      // Click a feature to see what the system says about it.
      const describe: Record<string, (p: any) => string> = {
        "water-fill": (p) => `<b>New water</b><br>${Math.round(p.area_m2).toLocaleString()} m²<br>Confidence: ${p.confidence_level}<br>Evidence: ${p.source}`,
        "debris-fill": (p) => `<b>Debris</b><br>${Math.round(p.area_m2).toLocaleString()} m²<br>Confidence: ${p.confidence_level}<br>Evidence: ${p.source}`,
        buildings: (p) => `<b>Building: ${p.status}</b><br>Hazard: ${p.hazard}<br>Confidence: ${p.confidence_level}`,
        roads: (p) => `<b>Road section hit</b><br>${p.highway}${p.name ? " · " + p.name : ""}<br>${p.length_m} m in ${p.hazard}<br>Confidence: ${p.confidence_level}`,
        bridges: (p) => `<b>Bridge hit</b><br>${p.reason}<br>Confidence: ${p.confidence_level}`,
        settlements: (p) => `<b>${p.name ?? "Unnamed settlement"}</b><br>${p.buildings} buildings<br>Vehicle road to town: ${p.vehicle_town_status}<br>Any route to town: ${p.any_town_status}<br>Vehicle road to hospital: ${p.vehicle_hospital_status}`,
      };
      for (const id of Object.keys(describe)) {
        m.on("click", id, (e: maplibregl.MapLayerMouseEvent) => {
          const f = e.features?.[0];
          if (f) new maplibregl.Popup({ closeButton: false }).setLngLat(e.lngLat).setHTML(describe[id](f.properties)).addTo(m);
        });
        m.on("mouseenter", id, () => (m.getCanvas().style.cursor = "pointer"));
        m.on("mouseleave", id, () => (m.getCanvas().style.cursor = ""));
      }
    });

    // Pulse the halo around cut-off settlements.
    let frame = 0;
    const pulse = () => {
      const t = (Date.now() % 1600) / 1600;
      if (m.getLayer("settlement-pulse")) {
        m.setPaintProperty("settlement-pulse", "circle-radius", 8 + 14 * t);
        m.setPaintProperty("settlement-pulse", "circle-opacity", 0.45 * (1 - t));
      }
      frame = requestAnimationFrame(pulse);
    };
    frame = requestAnimationFrame(pulse);
    refreshRuns();
    return () => { cancelAnimationFrame(frame); m.remove(); map.current = null; mapReady.current = false; };
  }, [refreshRuns]);

  // ---- Draw the area by dragging a rectangle --------------------------------
  useEffect(() => {
    const m = map.current;
    if (!m || !drawing) return;
    m.dragPan.disable();
    m.getCanvas().style.cursor = "crosshair";
    let start: maplibregl.LngLat | null = null;
    const corners = (a: maplibregl.LngLat, b: maplibregl.LngLat) => [Math.min(a.lng, b.lng), Math.min(a.lat, b.lat), Math.max(a.lng, b.lng), Math.max(a.lat, b.lat)];
    const down = (e: maplibregl.MapMouseEvent) => { start = e.lngLat; };
    const move = (e: maplibregl.MapMouseEvent) => { if (start) showBox(corners(start, e.lngLat)); };
    const up = (e: maplibregl.MapMouseEvent) => {
      if (!start) return;
      const box = corners(start, e.lngLat);
      setBbox(box.map((v) => v.toFixed(3)));
      setDrawing(false);
    };
    m.on("mousedown", down); m.on("mousemove", move); m.on("mouseup", up);
    return () => {
      m.off("mousedown", down); m.off("mousemove", move); m.off("mouseup", up);
      m.dragPan.enable();
      m.getCanvas().style.cursor = "";
    };
  }, [drawing]);

  function showBox(box: number[]) {
    const [w, s, e, n] = box;
    (map.current?.getSource("aoi") as GeoJSONSource | undefined)?.setData({
      type: "Feature", properties: {}, geometry: { type: "Polygon", coordinates: [[[w, s], [e, s], [e, n], [w, n], [w, s]]] },
    });
  }

  useEffect(() => {
    const box = bbox.map(Number);
    if (bbox.every((v) => v !== "") && box.every(Number.isFinite)) showBox(box);
  }, [bbox]);

  // ---- Load a finished run onto the map --------------------------------------
  const loadRun = useCallback(async (runId: string) => {
    const m = map.current;
    if (!m) return;
    setError(""); setPicked(null);
    // The base map may still be loading; wait until our sources exist.
    while (!mapReady.current) await new Promise((r) => setTimeout(r, 200));
    const s: Summary = await fetch(`${API}/api/runs/${runId}/summary`).then((r) => r.json());
    setSummary(s); setRunId(runId); setChat([]);
    setBbox(s.inputs.bbox_west_south_east_north.map((v: number) => v.toFixed(3)));
    setFloodDate(s.inputs.flood_date);
    for (const name of DATA_LAYERS) {
      const data: Collection = await fetch(`${API}/api/runs/${runId}/layers/${name}`).then((r) => r.json());
      layers.current[name] = data;
      (m.getSource(name) as GeoJSONSource).setData(data as any);
      if (name === "settlements") setSettlements(data.features);
    }
    (m.getSource("highlight") as GeoJSONSource).setData(EMPTY as any);
    const [w, so, e, n] = s.inputs.bbox_west_south_east_north;
    m.fitBounds([[w, so], [e, n]], { padding: 40, duration: 900 });
  }, []);

  // ---- Start an analysis and follow its progress -----------------------------
  async function analyse() {
    setError(""); setMessages([]); setBusy(true);
    try {
      const response = await fetch(`${API}/api/analyse`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ bbox: bbox.map(Number), flood_date: floodDate, thorough }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail ?? "The analysis could not start.");
      for (;;) {
        await new Promise((r) => setTimeout(r, 1500));
        const job = await fetch(`${API}/api/jobs/${body.run_id}`).then((r) => r.json());
        setMessages(job.messages);
        if (job.status === "failed") throw new Error(job.messages.at(-1));
        if (job.status === "done") { await loadRun(body.run_id); refreshRuns(); break; }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  // ---- Click-through: a number or a settlement zooms to what is behind it ----
  function zoomTo(layer: string, filter?: (f: Feature) => boolean) {
    const data = layers.current[layer];
    if (!data || !map.current) return;
    const subset = { ...data, features: filter ? data.features.filter(filter) : data.features };
    const bounds = boundsOf(subset);
    if (bounds) map.current.fitBounds(bounds, { padding: 80, maxZoom: 15, duration: 800 });
  }

  function pickSettlement(f: Feature) {
    const id = f.properties.osm_id;
    setPicked(id);
    const mine = (x: Feature) => x.properties.settlement === id;
    const links = (layers.current.broken_links ?? EMPTY).features.filter(mine);
    const routes = (layers.current.lost_routes ?? EMPTY).features.filter(mine);
    (map.current?.getSource("highlight") as GeoJSONSource).setData({ type: "FeatureCollection", features: [...routes, ...links] } as any);
    const bounds = boundsOf({ type: "FeatureCollection", features: [f, ...links, ...routes] });
    if (bounds) map.current?.fitBounds(bounds, { padding: 90, maxZoom: 15, duration: 800 });
  }

  // ---- Copilot: answers come only from this run's computed data --------------
  async function ask(text: string) {
    if (!runId || !text.trim() || asking) return;
    setAsking(true); setQuestion("");
    try {
      const response = await fetch(`${API}/api/runs/${runId}/ask`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: text, language }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail ?? "The copilot is not available.");
      setChat((c) => [...c, { question: text, text: body.text, verified: body.verified, rejected: body.unsupported_numbers }]);
    } catch (e) {
      setChat((c) => [...c, { question: text, text: e instanceof Error ? e.message : String(e), verified: false, rejected: [] }]);
    } finally {
      setAsking(false);
    }
  }

  function toggle(key: string) {
    const next = { ...visible, [key]: !visible[key] };
    setVisible(next);
    LEGEND.find((l) => l.key === key)!.layers.forEach((id) => map.current?.setLayoutProperty(id, "visibility", next[key] ? "visible" : "none"));
  }

  const ready = bbox.every((v) => v !== "" && Number.isFinite(Number(v))) && floodDate !== "";
  const cutOff = settlements.filter((f) => f.properties.cut_off_any || f.properties.cut_off_vehicle);
  const s1 = summary?.sentinel1, damage = summary?.damage, cut = summary?.cutoff, test = summary?.acceptance_test;

  return (
    <div className="shell">
      <aside className="panel left">
        <div className="brand">Valley<span>Watch</span></div>
        <p className="tagline">Flood, damage and cut-off settlements from free satellite data.</p>
        <div className="proto">Educational prototype · not for operations</div>

        <h2>1 · Area and date</h2>
        <button className={drawing ? "active" : ""} onClick={() => setDrawing(!drawing)}>{drawing ? "Drag a box on the map…" : "Draw area on map"}</button>
        <p className="hint">Or type the corners in degrees. Live runs are limited to 400 km².</p>
        <div className="grid2">
          {["West", "South", "East", "North"].map((name, i) => (
            <div key={name}><label>{name}</label><input value={bbox[i]} onChange={(e) => setBbox(bbox.map((v, j) => (j === i ? e.target.value : v)))} /></div>
          ))}
        </div>
        <div className="field"><label>Flood date</label><input type="date" value={floodDate} onChange={(e) => setFloodDate(e.target.value)} /></div>
        <label className="check"><input type="checkbox" checked={thorough} onChange={(e) => setThorough(e.target.checked)} />Thorough: add a second radar track from the opposite side (slower)</label>
        <button className="primary" disabled={!ready || busy} onClick={analyse}>{busy ? "Analysing…" : "Analyse"}</button>
        {error && <p className="error">{error}</p>}

        {messages.length > 0 && (<>
          <h2>Progress</h2>
          <ul className="steps">{messages.slice(-14).map((text, i, all) => <li key={text + i} className={busy && i === all.length - 1 ? "live" : ""}>{text}</li>)}</ul>
        </>)}

        <h2>Earlier runs</h2>
        <select value="" onChange={(e) => e.target.value && loadRun(e.target.value).catch((err) => setError(`Could not open the run: ${err.message ?? err}`))}>
          <option value="">Open a finished run…</option>
          {runs.map((r) => <option key={r.run_id} value={r.run_id}>{r.run_id}</option>)}
        </select>

        {s1 && (<>
          <h2>Satellite scenes used</h2>
          <dl className="kv">
            <dt>Radar before</dt><dd>{s1.before.date}</dd>
            <dt>Radar after</dt><dd>{s1.after.date}</dd>
            <dt>Track</dt><dd>orbit {s1.relative_orbit} {s1.direction.toLowerCase()}</dd>
            {s1.second_track && summary.radar_orbits_used?.length > 1 && (<><dt>2nd track</dt><dd>orbit {s1.second_track.relative_orbit}, {s1.second_track.before.date} → {s1.second_track.after.date}</dd></>)}
            <dt>Optical</dt><dd>{summary.sentinel2.check.used ? `${summary.sentinel2.check.reach_zone_clear_percent}% of valley clear` : "no clear view"}</dd>
            <dt>Map data</dt><dd>OSM as of {summary.openstreetmap?.snapshot_date}</dd>
          </dl>
          <p className="hint">{s1.reason}</p>
        </>)}
      </aside>

      <main className="mapwrap">
        <div ref={mapNode} className="map" />
        {s1 && <div className="pass">Last satellite pass used: {s1.after.date} · flood date {summary.inputs.flood_date}</div>}
        <div className="legend">
          <h3>Layers</h3>
          {LEGEND.map((l) => (
            <label key={l.key}><input type="checkbox" checked={visible[l.key]} onChange={() => toggle(l.key)} /><span className="swatch" style={{ background: l.colour }} />{l.label}</label>
          ))}
          <p className="hint" style={{ margin: "6px 0 0" }}>Stronger colour = higher confidence.</p>
        </div>
      </main>

      <aside className="panel right">
        {!summary && <p className="hint" style={{ marginTop: 40 }}>Choose an area and a flood date, then press Analyse. Or open an earlier run. Results appear here.</p>}
        {summary && (<>
          <h2 style={{ marginTop: 0 }}>Totals · click to zoom</h2>
          <button className="stat water" onClick={() => zoomTo("flood_debris", (f) => f.properties.hazard === "water")}>New water<b>{summary.totals.water_km2} km²</b></button>
          <button className="stat debris" onClick={() => zoomTo("flood_debris", (f) => f.properties.hazard === "debris")}>Debris-covered<b>{summary.totals.debris_km2} km²</b></button>
          {damage && (<>
            <button className="stat" onClick={() => zoomTo("buildings_hit", (f) => f.properties.status === "hit")}>Buildings hit<b>{damage.buildings_hit.toLocaleString()}</b><small>plus {damage.buildings_possibly_affected?.toLocaleString() ?? 0} possibly affected · {damage.buildings_total.toLocaleString()} mapped</small></button>
            <button className="stat" onClick={() => zoomTo("road_hits")}>Roads hit<b>{damage.roads_hit_km} km</b><small>{damage.roads_hit_sections} sections</small></button>
            <button className="stat" onClick={() => zoomTo("bridges", (f) => f.properties.hit)}>Bridges hit<b>{damage.bridges_hit}</b><small>of {damage.bridges_total} mapped · judged by the banks, not the river below</small></button>
          </>)}
          {cut && (<>
            <button className="stat warn" onClick={() => zoomTo("settlements", (f) => f.properties.cut_off_vehicle)}>No vehicle road<b>{cut.no_vehicle_road.settlements}</b><small>settlements · {cut.no_vehicle_road.buildings.toLocaleString()} buildings</small></button>
            <button className="stat cut" onClick={() => zoomTo("settlements", (f) => f.properties.cut_off_any)}>No route at all<b>{cut.no_route_at_all.settlements}</b><small>settlements · {cut.no_route_at_all.buildings.toLocaleString()} buildings</small></button>
          </>)}

          <h2>Situation report</h2>
          <div className="grid2">
            <button onClick={() => window.open(`${API}/api/runs/${runId}/report?lang=en`, "_blank")}>English</button>
            <button onClick={() => window.open(`${API}/api/runs/${runId}/report?lang=ne`, "_blank")}>नेपाली</button>
          </div>
          <p className="hint">One page, printable. Every figure comes from this analysis.</p>

          <h2>Cut-off settlements · largest first</h2>
          {cutOff.length === 0 && <p className="hint">None found in this area.</p>}
          {cutOff.map((f) => {
            const p = f.properties;
            return (
              <button key={p.osm_id} className={`settle ${p.cut_off_any ? "all" : ""} ${picked === p.osm_id ? "picked" : ""}`} onClick={() => pickSettlement(f)}>
                <div className="name">{p.name ?? "Unnamed settlement"}{p.name_en ? ` · ${p.name_en}` : ""}</div>
                <div className="meta">
                  <span className={`tag ${p.cut_off_any ? "all" : "vehicle"}`}>{p.cut_off_any ? "no route at all" : "no vehicle road"}</span>
                  {p.buildings} buildings · town was {p.vehicle_town_km_before ?? p.any_town_km_before ?? "?"} km
                </div>
              </button>
            );
          })}
          {cut && <p className="hint">{cut.town_destination}. Roads outside the box: {cut.roads_outside_box}. {cut.no_vehicle_road.had_no_vehicle_road_before} settlements had no mapped vehicle road even before the flood.</p>}

          <h2>Ask the copilot</h2>
          <p className="hint">It can only read this analysis. Each number in an answer is checked against the data before it is shown.</p>
          {chat.map((turn, i) => (
            <div key={i} className="turn">
              <div className="q">{turn.question}</div>
              <div className="a">{turn.text}</div>
              <span className={`tag ${turn.verified ? "ok" : "all"}`}>{turn.verified ? "numbers checked" : turn.rejected.length ? `not verified: ${turn.rejected.join(", ")}` : "no answer"}</span>
            </div>
          ))}
          <div className="suggest">
            {(language === "en"
              ? ["Which villages cannot reach a hospital?", "Which bridges were hit?", "How reliable is this map?"]
              : ["कुन गाउँहरू अस्पताल पुग्न सक्दैनन्?", "कुन-कुन पुलमा क्षति पुगेको छ?", "यो नक्सा कति भरपर्दो छ?"]
            ).map((text) => <button key={text} disabled={asking} onClick={() => ask(text)}>{text}</button>)}
          </div>
          <div className="askrow">
            <select value={language} onChange={(e) => setLanguage(e.target.value as "en" | "ne")}><option value="en">EN</option><option value="ne">ने</option></select>
            <input value={question} placeholder={language === "en" ? "Ask about this flood…" : "यस बाढीबारे सोध्नुहोस्…"} onChange={(e) => setQuestion(e.target.value)} onKeyDown={(e) => e.key === "Enter" && ask(question)} />
            <button className="primary" disabled={asking || !question.trim()} onClick={() => ask(question)}>{asking ? "…" : "Ask"}</button>
          </div>

          {test?.flood_pair && (<>
            <h2>Self-check · no-flood test</h2>
            <dl className="kv">
              <dt>Flood pair</dt><dd>{test.flood_pair.water_km2} water · {test.flood_pair.debris_km2} debris km²</dd>
              <dt>No-flood pair</dt><dd>{test.no_flood_pair.water_km2} water · {test.no_flood_pair.debris_km2} debris km²</dd>
              <dt>False alarms</dt><dd>{test.no_flood_as_percent_of_flood.total ?? "–"}% (budget {test.budget_percent}%)</dd>
            </dl>
            <p className="hint">The same rules are run on two images from before the flood. What they find there is the error to expect.</p>
          </>)}

          <h2>What this cannot do</h2>
          <p className="hint">Satellites pass every few days, so this is no early warning. Radar is blind on steep valley walls. A “hit” is an estimate from 10 m pixels, not a field report. OpenStreetMap is incomplete in remote areas. Building counts are a rough guide to people.</p>
        </>)}
      </aside>

      <footer className="footer">
        <strong>Educational prototype, not an operational tool.</strong>
        {(summary?.attribution ?? ["Contains modified Copernicus Sentinel data 2026.", "Produced using Copernicus WorldDEM-30 © DLR e.V. 2010–2014 and © Airbus Defence and Space GmbH 2014–2018 provided under COPERNICUS by the European Union and ESA; all rights reserved.", "© OpenStreetMap contributors."]).map((line: string) => <span key={line}>{line}</span>)}
      </footer>
    </div>
  );
}
