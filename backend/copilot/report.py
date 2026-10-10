"""One-page situation report, in English or Nepali.

Every figure on the page is written by this code straight from the run's
outputs. The language model contributes only the short summary paragraph,
and that paragraph is shown only if all its numbers pass the check in
`check.py`. Otherwise a fixed sentence built from the same figures is used.
"""
import html
import json

from .facts import LIMITATIONS
from .llm import answer

# Fixed wording for both languages. (Nepali wording should be reviewed by a
# native speaker before the report is relied on.)
TEXT = {
    "en": {
        "title": "Flood situation report", "flood_date": "Flood date", "area": "Area analysed",
        "generated_from": "Satellite pass used", "summary": "Summary",
        "extent": "Where the flood hit", "new_water": "New water", "debris": "Debris-covered ground",
        "damage": "What was damaged", "buildings_hit": "Buildings hit",
        "buildings_possible": "Buildings possibly affected", "roads_hit": "Roads hit",
        "bridges_hit": "Bridges hit", "of": "of", "mapped": "mapped",
        "cutoff": "Who is cut off", "no_vehicle": "Settlements with no vehicle road",
        "no_route": "Settlements with no route at all", "buildings": "buildings",
        "priority": "Largest cut-off settlements", "settlement": "Settlement",
        "status": "Status", "town_before": "Town was (km)", "broken": "Broken road (OSM id)",
        "status_any": "no route at all", "status_vehicle": "no vehicle road", "none": "None found.",
        "data": "Data used", "radar_before": "Radar image before", "radar_after": "Radar image after",
        "optical": "Optical view clear over", "of_valley": "of the valley",
        "osm": "Map data (OpenStreetMap) as of", "reliability": "How reliable is this",
        "false_alarm": "False-alarm level in our own no-flood test",
        "blind": "Valley floor radar cannot see", "limits": "What this report cannot tell you",
        "prototype": "Educational prototype, not an operational tool. Estimates from satellite "
                     "images; not verified on the ground.",
        "print": "Print / save as PDF", "unverified": "Summary written from fixed wording: the "
                 "language model's text did not pass the number check.",
        "fallback": "On {flood_date} the analysis maps {water} km2 of new water and {debris} km2 "
                    "of debris-covered ground. {buildings} buildings, {roads} km of road and "
                    "{bridges} bridges are estimated as hit. {no_vehicle} settlements have no "
                    "vehicle road and {no_route} have no route at all.",
    },
    "ne": {
        "title": "बाढी स्थिति प्रतिवेदन", "flood_date": "बाढीको मिति", "area": "विश्लेषण गरिएको क्षेत्र",
        "generated_from": "प्रयोग गरिएको भू-उपग्रह तस्बिर", "summary": "सारांश",
        "extent": "बाढीले कहाँ असर गर्‍यो", "new_water": "नयाँ पानी", "debris": "लेदो र गेग्रानले ढाकेको जमिन",
        "damage": "के-के क्षति भयो", "buildings_hit": "प्रभावित भवन",
        "buildings_possible": "सम्भावित प्रभावित भवन", "roads_hit": "क्षतिग्रस्त सडक",
        "bridges_hit": "क्षतिग्रस्त पुल", "of": "मध्ये", "mapped": "नक्सामा",
        "cutoff": "को-को सम्पर्कविहीन छन्", "no_vehicle": "सवारी सडक नभएका बस्ती",
        "no_route": "कुनै पनि बाटो नभएका बस्ती", "buildings": "भवन",
        "priority": "सबैभन्दा ठूला सम्पर्कविहीन बस्ती", "settlement": "बस्ती",
        "status": "अवस्था", "town_before": "पहिले बजारसम्म (कि.मि.)", "broken": "टुटेको सडक (OSM id)",
        "status_any": "कुनै बाटो छैन", "status_vehicle": "सवारी सडक छैन", "none": "कुनै भेटिएन।",
        "data": "प्रयोग गरिएको डाटा", "radar_before": "बाढीअघिको राडार तस्बिर",
        "radar_after": "बाढीपछिको राडार तस्बिर", "optical": "अप्टिकल तस्बिर सफा देखिएको",
        "of_valley": "उपत्यका", "osm": "नक्सा डाटा (OpenStreetMap) को मिति",
        "reliability": "यो कति भरपर्दो छ", "false_alarm": "बाढी नभएको परीक्षणमा गलत सङ्केतको स्तर",
        "blind": "राडारले देख्न नसक्ने उपत्यकाको भाग", "limits": "यो प्रतिवेदनले के भन्न सक्दैन",
        "prototype": "यो शैक्षिक नमुना हो, सञ्चालनका लागि होइन। भू-उपग्रह तस्बिरबाट गरिएको अनुमान; "
                     "स्थलगत रूपमा प्रमाणित छैन।",
        "print": "छाप्नुहोस् / PDF बचत गर्नुहोस्", "unverified": "सारांश निश्चित शब्दावलीबाट लेखिएको हो: "
                 "भाषा मोडेलको पाठ सङ्ख्या जाँचमा उत्तीर्ण भएन।",
        "fallback": "{flood_date} मा विश्लेषणले {water} km2 नयाँ पानी र {debris} km2 लेदो तथा गेग्रानले "
                    "ढाकेको जमिन देखाउँछ। {buildings} भवन, {roads} कि.मि. सडक र {bridges} पुल प्रभावित "
                    "भएको अनुमान छ। {no_vehicle} बस्तीमा सवारी सडक छैन र {no_route} बस्तीमा कुनै पनि बाटो छैन।",
    },
}

SUMMARY_REQUEST = (
    "Write the summary paragraph of a one-page flood situation report for rescue "
    "coordinators: at most 90 words, one paragraph, no headings or lists. Cover where the "
    "flood hit, what was damaged, who is cut off (name the largest cut-off settlements) and "
    "one sentence on how reliable the result is. Call get_overview, "
    "list_cut_off_settlements and get_reliability first.")


def summary_paragraph(facts, language):
    """The model's summary if it passes the number check, else fixed wording."""
    overview = facts.get_overview()
    fallback = TEXT[language]["fallback"].format(
        flood_date=overview["flood_date"], water=overview["new_water_km2"],
        debris=overview["debris_covered_km2"], buildings=overview["buildings_hit"],
        roads=overview["roads_hit_km"], bridges=overview["bridges_hit"],
        no_vehicle=overview["settlements_without_vehicle_road"],
        no_route=overview["settlements_with_no_route_at_all"])
    try:
        result = answer(facts, SUMMARY_REQUEST, language)
    except Exception as error:  # noqa: BLE001 - the report must still be produced
        return {"text": fallback, "from_model": False, "note": f"Language model not available: {error}"}
    if result["verified"] and result["text"]:
        return {"text": result["text"], "from_model": True, "note": ""}
    return {"text": fallback, "from_model": False, "note": TEXT[language]["unverified"],
            "rejected_numbers": result["unsupported_numbers"]}


def build_report(facts, language="en", refresh=False):
    """Return the report as a complete HTML page."""
    language = language if language in TEXT else "en"
    t = TEXT[language]
    # The summary costs a model call, so it is kept next to the run.
    cache = facts.folder / f"report_summary_{language}.json"
    if cache.exists() and not refresh:
        summary = json.loads(cache.read_text())
    else:
        summary = summary_paragraph(facts, language)
        cache.write_text(json.dumps(summary, ensure_ascii=False, indent=2))

    o, scenes, reliability = facts.get_overview(), facts.get_satellite_scenes(), facts.get_reliability()
    worst = facts.list_cut_off_settlements("any", 6)["settlements"]
    listed = {s["name"] for s in worst}
    for s in facts.list_cut_off_settlements("vehicle", 8)["settlements"]:
        if len(worst) < 8 and s["name"] not in listed:
            worst.append(dict(s, vehicle_only=True))

    def n(value, source):
        """A figure, tagged with where it comes from (shown on hover)."""
        shown = f"{value:,}" if isinstance(value, (int, float)) else html.escape(str(value))
        return f'<b class="n" title="source: {html.escape(source)}">{shown}</b>'

    rows = "".join(
        f"<tr><td>{html.escape(str(s['name'] or '—'))}"
        f"{' · ' + html.escape(s['name_english']) if s.get('name_english') else ''}</td>"
        f"<td>{n(s['buildings'], 'settlements.buildings')}</td>"
        f"<td>{t['status_vehicle'] if s.get('vehicle_only') else t['status_any']}</td>"
        f"<td>{n(s['km_to_town_before_flood'], 'settlements.km_before') if s['km_to_town_before_flood'] is not None else '—'}</td>"
        f"<td>{html.escape(str(s['broken_road_osm_id'] or '—'))}</td></tr>" for s in worst)
    table = (f"<table><tr><th>{t['settlement']}</th><th>{t['buildings']}</th><th>{t['status']}</th>"
             f"<th>{t['town_before']}</th><th>{t['broken']}</th></tr>{rows}</table>"
             if worst else f"<p>{t['none']}</p>")
    box = ", ".join(str(v) for v in o["area_box_west_south_east_north"])
    false_alarm = reliability["false_alarm_percent_of_mapped_area"]
    other = "ne" if language == "en" else "en"
    attribution = " ".join(html.escape(line) for line in facts.summary["attribution"])

    return f"""<!doctype html>
<html lang="{language}"><head><meta charset="utf-8">
<title>{t['title']} · {o['flood_date']}</title>
<style>
  @page {{ size: A4; margin: 14mm; }}
  body {{ font-family: "Noto Sans", "Noto Sans Devanagari", system-ui, sans-serif; color: #111;
         max-width: 182mm; margin: 12px auto; font-size: 10.5pt; line-height: 1.35; }}
  h1 {{ font-size: 19pt; margin: 0; }} h2 {{ font-size: 11.5pt; margin: 11px 0 4px; border-bottom: 1.5px solid #111; }}
  .meta {{ color: #444; margin: 2px 0 6px; }}
  .grid {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 0 14px; }}
  .fig {{ display: flex; justify-content: space-between; border-bottom: 1px dotted #999; padding: 2px 0; }}
  .n {{ font-variant-numeric: tabular-nums; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 9.5pt; }}
  th, td {{ text-align: left; padding: 2px 6px 2px 0; border-bottom: 1px solid #ccc; }}
  ul {{ margin: 2px 0 0 16px; padding: 0; font-size: 9.5pt; }}
  .warn {{ border: 1.5px solid #111; padding: 4px 8px; margin-top: 8px; font-weight: 600; }}
  .note, .foot {{ color: #555; font-size: 8.5pt; }}
  .bar {{ display: flex; gap: 8px; margin-bottom: 10px; }}
  .bar a, .bar button {{ font: inherit; padding: 4px 10px; border: 1px solid #111; background: #fff; color: #111; text-decoration: none; cursor: pointer; }}
  @media print {{ .bar {{ display: none; }} body {{ margin: 0; }} }}
</style></head><body>
<div class="bar"><a href="?lang={other}">{'नेपाली' if other == 'ne' else 'English'}</a>
<button onclick="window.print()">{t['print']}</button></div>
<h1>{t['title']}</h1>
<div class="meta">{t['flood_date']}: {n(o['flood_date'], 'inputs.flood_date')} · {t['area']}: {box} ·
{t['generated_from']}: {n(scenes['radar_image_after_flood'], 'sentinel1.after.date')}</div>
<div class="warn">{t['prototype']}</div>

<h2>{t['summary']}</h2>
<p>{html.escape(summary['text'])}</p>
{f'<p class="note">{html.escape(summary["note"])}</p>' if summary.get('note') else ''}

<div class="grid">
<div><h2>{t['extent']}</h2>
<div class="fig"><span>{t['new_water']}</span><span>{n(o['new_water_km2'], 'totals.water_km2')} km²</span></div>
<div class="fig"><span>{t['debris']}</span><span>{n(o['debris_covered_km2'], 'totals.debris_km2')} km²</span></div></div>
<div><h2>{t['damage']}</h2>
<div class="fig"><span>{t['buildings_hit']}</span><span>{n(o['buildings_hit'], 'damage.buildings_hit')}</span></div>
<div class="fig"><span>{t['buildings_possible']}</span><span>{n(o['buildings_possibly_affected'], 'damage.buildings_possibly_affected')}</span></div>
<div class="fig"><span>{t['roads_hit']}</span><span>{n(o['roads_hit_km'], 'damage.roads_hit_km')} km</span></div>
<div class="fig"><span>{t['bridges_hit']}</span><span>{n(o['bridges_hit'], 'damage.bridges_hit')} {t['of']} {n(o['bridges_mapped'], 'damage.bridges_total')}</span></div></div>
<div><h2>{t['cutoff']}</h2>
<div class="fig"><span>{t['no_vehicle']}</span><span>{n(o['settlements_without_vehicle_road'], 'cutoff.no_vehicle_road.settlements')}</span></div>
<div class="fig"><span>… {t['buildings']}</span><span>{n(o['buildings_in_settlements_without_vehicle_road'], 'cutoff.no_vehicle_road.buildings')}</span></div>
<div class="fig"><span>{t['no_route']}</span><span>{n(o['settlements_with_no_route_at_all'], 'cutoff.no_route_at_all.settlements')}</span></div>
<div class="fig"><span>… {t['buildings']}</span><span>{n(o['buildings_in_settlements_with_no_route_at_all'], 'cutoff.no_route_at_all.buildings')}</span></div></div>
</div>

<h2>{t['priority']}</h2>
{table}

<div class="grid" style="grid-template-columns: 1fr 1fr;">
<div><h2>{t['data']}</h2>
<div class="fig"><span>{t['radar_before']}</span><span>{n(scenes['radar_image_before_flood'], 'sentinel1.before.date')}</span></div>
<div class="fig"><span>{t['radar_after']}</span><span>{n(scenes['radar_image_after_flood'], 'sentinel1.after.date')}</span></div>
<div class="fig"><span>{t['optical']}</span><span>{n(scenes['percent_of_valley_with_clear_optical_view'], 'sentinel2.check') if scenes['percent_of_valley_with_clear_optical_view'] is not None else '—'}% {t['of_valley']}</span></div>
<div class="fig"><span>{t['osm']}</span><span>{n(scenes['openstreetmap_snapshot_date'], 'openstreetmap.snapshot_date')}</span></div></div>
<div><h2>{t['reliability']}</h2>
<div class="fig"><span>{t['false_alarm']}</span><span>{n(false_alarm, 'acceptance_test') if false_alarm is not None else '—'}%</span></div>
<div class="fig"><span>{t['blind']}</span><span>{n(reliability['percent_of_valley_floor_radar_cannot_see'], 'totals.corridor_not_mapped_by_radar_percent')}%</span></div></div>
</div>

<h2>{t['limits']}</h2>
<ul>{''.join(f'<li>{html.escape(line)}</li>' for line in LIMITATIONS[language])}</ul>
<p class="foot">{attribution}</p>
</body></html>"""
