#!/usr/bin/env python3
"""Merge PADI JSON logbook exports and Oceanic+ UDDF files into one unified JSON.

Usage:  python3 scripts/merge.py
Reads:  data/padi/*.json  (PADI logbook export), data/oceanic/*.uddf
Writes: data/merged_log.json
Also:   data/site_coords.json gives map positions to PADI site names (PADI has no coordinates):
        {"Sandals Negril": {"lat": 18.33, "lon": -78.34}, ...}
        data/site_aliases.json is read if present: {"site_abc...": "Site Name", ...}
        Unknown site ids are auto-added as guesses by coordinate region so you can
        edit the file once and re-run.
"""
import json, re, sys, xml.etree.ElementTree as ET
from datetime import date as _date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UDDF_NS = {'u': 'http://www.streit.cc/uddf/3.2/'}

# ---------------------------------------------------------------- PADI ----
def parse_padi(path: Path):
    data = json.loads(path.read_text(encoding='utf-8'))
    if isinstance(data, dict) and 'data' in data:
        logs = data['data'].get('logbook_logs', [])
    elif isinstance(data, dict) and 'logbook_logs' in data:
        logs = data['logbook_logs']
    elif isinstance(data, list):
        logs = data
    else:
        logs = [data]
    dives = []
    for log in logs:
        dt = log.get('dive_date', '')
        date = dt[:10]
        time_in = None
        dts = (log.get('depth_times') or [{}])[0]
        if dts.get('time_in'):
            time_in = dts['time_in'][:5]
        cond = (log.get('conditions') or [{}])[0]
        equip = (log.get('equipment') or [{}])[0]
        exp = (log.get('experiences') or [{}])[0]
        dives.append({
            'id': f"padi:{log.get('id')}",
            'sources': ['padi'],
            'date': date, 'time': time_in,
            'title': log.get('dive_title'),
            'site': log.get('dive_location'),
            'lat': None, 'lon': None,
            'max_depth_m': dts.get('max_depth'),
            'duration_min': dts.get('bottom_time'),
            'water_temp_c': cond.get('bottom_water_temp'),
            'dive_type': log.get('dive_type'),
            'buddies': exp.get('buddies'),
            'notes': exp.get('notes'),
            'dive_center': exp.get('dive_center'),
            'visibility': cond.get('visibility'),
            # PADI exports carry no gas data here; all PADI dives are assumed to be air.
            'gas': {'o2': 0.21, 'assumed': True},
            'suspect': False,
            'weight': equip.get('weight'),
            'suit': equip.get('suit_type'),
            'profile': None,
            'dive_mode': 'opencircuit',
        })
    return dives

# --------------------------------------------------------------- UDDF ----
def _kelvin_to_c(k):
    return round(float(k) - 273.15, 1) if k else None

def _pa_to_bar(p):
    return round(float(p) / 1e5, 1) if p else None

def parse_uddf(path: Path):
    root = ET.parse(path).getroot()
    sites = {s.get('id'): {
        'lat': float(s.find('u:geography/u:latitude', UDDF_NS).text),
        'lon': float(s.find('u:geography/u:longitude', UDDF_NS).text),
    } for s in root.findall('u:divesite/u:site', UDDF_NS)}
    mixes = {m.get('id'): {
        'name': m.findtext('u:name', namespaces=UDDF_NS),
        'o2': float(m.findtext('u:o2', namespaces=UDDF_NS) or 0.21),
    } for m in root.findall('u:gasdefinitions/u:mix', UDDF_NS)}

    dives = []
    for d in root.findall('.//u:dive', UDDF_NS):
        before = d.find('u:informationbeforedive', UDDF_NS)
        after = d.find('u:informationafterdive', UDDF_NS)
        site_ref = before.find('u:link', UDDF_NS).get('ref')
        site = sites.get(site_ref, {})
        # Oceanic+ writes malformed offsets like "+00:03" (= UTC+3) or "-00:05" (= UTC-5).
        # We keep local wall time as-is and drop the offset.
        raw_dt = before.findtext('u:datetime', namespaces=UDDF_NS)
        m = re.match(r'(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})', raw_dt or '')
        date, time = (m.group(1), m.group(2)) if m else (None, None)

        waypoints = d.findall('u:samples/u:waypoint', UDDF_NS)
        profile, mode, gas_o2 = [], None, None
        for wp in waypoints:
            t = wp.findtext('u:divetime', namespaces=UDDF_NS)
            dep = wp.findtext('u:depth', namespaces=UDDF_NS)
            if t is None or dep is None:
                continue
            profile.append([float(t), round(float(dep), 2)])
            dm = wp.find('u:divemode', UDDF_NS)
            if dm is not None:
                mode = dm.get('type')
            sw = wp.find('u:switchmix', UDDF_NS)
            if sw is not None:
                mix = mixes.get(sw.get('ref'), {})
                gas_o2 = mix.get('o2')
        if gas_o2 is None:
            td = d.find('u:tankdata', UDDF_NS)
            if td is not None:
                lk = td.find('u:link', UDDF_NS)
                if lk is not None:
                    gas_o2 = mixes.get(lk.get('ref'), {}).get('o2')

        rating = after.find('u:rating/u:ratingvalue', UDDF_NS)
        tank = d.find('u:tankdata', UDDF_NS)
        dives.append({
            'id': f"uddf:{d.get('id')}",
            'sources': ['oceanic'],
            'date': date, 'time': time,
            'site': site_ref,
            'lat': site.get('lat'), 'lon': site.get('lon'),
            'max_depth_m': round(float(after.findtext('u:greatestdepth', namespaces=UDDF_NS)), 1),
            'duration_min': round(float(after.findtext('u:diveduration', namespaces=UDDF_NS)) / 60.0, 1),
            'water_temp_c': _kelvin_to_c(after.findtext('u:lowesttemperature', namespaces=UDDF_NS)),
            'rating': int(rating.text) if rating is not None else None,
            'dive_mode': mode or 'apnoe',
            'gas': {'o2': gas_o2} if gas_o2 else None,
            # Scuba records under 5 minutes are almost always a watch switched on by accident.
            'suspect': (mode or 'apnoe') != 'apnoe' and float(after.findtext('u:diveduration', namespaces=UDDF_NS)) < 300,
            'pressure_start_bar': _pa_to_bar(tank.findtext('u:tankpressurebegin', namespaces=UDDF_NS)) if tank is not None else None,
            'pressure_end_bar': _pa_to_bar(tank.findtext('u:tankpressureend', namespaces=UDDF_NS)) if tank is not None else None,
            'profile': profile if len(profile) > 2 else None,
        })
    return dives, sites

# ------------------------------------------------- site alias guessing ----
REGIONS = [  # (name, lat_min, lat_max, lon_min, lon_max) -- edit freely / extend
    ('Negril, Jamaica', 18.2, 18.4, -78.4, -78.2),
    ('Dahab, Egypt', 28.4, 28.6, 34.5, 34.6),
    ('Sharm el-Sheikh, Egypt', 27.7, 28.1, 34.2, 34.5),
    ('Cape Sounion, Greece', 37.6, 37.8, 23.8, 24.0),
]

def guess_region(lat, lon):
    for name, la0, la1, lo0, lo1 in REGIONS:
        if la0 <= lat <= la1 and lo0 <= lon <= lo1:
            return name
    return None

# ---------------------------------------------------------------- merge ----
def merge(padi_dives, uddf_dives):
    """Merge PADI + Oceanic records of the same dive.
    PADI has date-only precision; a match = same date + max depth within 3 m.
    Oceanic wins on stats/profile; PADI wins on title/site/buddies/notes."""
    merged, used = [], set()
    for p in padi_dives:
        match = None
        for i, u in enumerate(uddf_dives):
            if i in used or u['date'] != p['date']:
                continue
            if p['max_depth_m'] and u['max_depth_m'] and abs(p['max_depth_m'] - u['max_depth_m']) <= 3.0:
                match = i
                break
        if match is not None:
            u = uddf_dives[match]
            used.add(match)
            rec = dict(u)
            rec['id'] = u['id']
            rec['sources'] = ['padi', 'oceanic']
            for k in ('title', 'site', 'buddies', 'notes', 'dive_center',
                      'dive_type', 'visibility', 'weight', 'suit'):
                if not rec.get(k) and p.get(k):
                    rec[k] = p[k]
            merged.append(rec)
        else:
            merged.append(p)
    merged.extend(u for i, u in enumerate(uddf_dives) if i not in used)
    merged.sort(key=lambda d: (d['date'] or '', d['time'] or ''))
    return merged

def build_trips(dives, gap_days=7):
    """Group dives into trips: a new trip starts after a gap of more than gap_days.
    Adds d['trip'] (an id like '2023-10') and returns [{id, label, start, end, n}]."""
    trips, last = [], None
    for d in sorted(dives, key=lambda x: x['date'] or ''):
        day = _date.fromisoformat(d['date'])
        if last is None or (day - last).days > gap_days:
            trips.append({'id': day.strftime('%Y-%m'), 'label': day.strftime('%b %Y'),
                          'start': d['date'], 'end': d['date'], 'n': 0})
        t = trips[-1]
        t['end'] = d['date']; t['n'] += 1
        d['trip'] = t['id']
        last = day
    seen = {}
    for t in trips:           # two trips in the same month get a suffix
        seen[t['id']] = seen.get(t['id'], 0) + 1
        if seen[t['id']] > 1:
            t['id'] += f"-{seen[t['id']]}"
            for d in dives:
                if t['start'] <= d['date'] <= t['end']:
                    d['trip'] = t['id']
    return trips

def main():
    padi_dives, uddf_dives, all_sites = [], [], {}
    for f in sorted((ROOT / 'data/padi').glob('*.json')):
        padi_dives += parse_padi(f)
    for f in sorted((ROOT / 'data/oceanic').glob('*.uddf')):
        d, s = parse_uddf(f)
        uddf_dives += d
        all_sites.update(s)

    alias_path = ROOT / 'data/site_aliases.json'
    aliases = json.loads(alias_path.read_text()) if alias_path.exists() else {}
    changed = False
    for sid, geo in all_sites.items():
        if sid not in aliases:
            region = guess_region(geo['lat'], geo['lon'])
            aliases[sid] = region or f"{geo['lat']:.3f}, {geo['lon']:.3f}"
            changed = True
    if changed:
        alias_path.write_text(json.dumps(aliases, indent=2, ensure_ascii=False) + '\n')

    for d in uddf_dives:
        d['site'] = aliases.get(d['site'], d['site'])

    merged = merge(padi_dives, uddf_dives)

    # Map positions for PADI dives, which only have a site name.
    coords_path = ROOT / 'data/site_coords.json'
    coords = json.loads(coords_path.read_text()) if coords_path.exists() else {}
    unplaced = set()
    for d in merged:
        if d['lat'] is None and d.get('site'):
            c = coords.get(d['site'])
            if c and c.get('lat') is not None:
                d['lat'], d['lon'] = c['lat'], c['lon']
            else:
                unplaced.add(d['site'])

    for d in merged:                      # area name (from REGIONS) so clusters on the map can be labelled
        d['area'] = guess_region(d['lat'], d['lon']) if d['lat'] is not None else None
    trips = build_trips(merged)
    out = ROOT / 'data/merged_log.json'
    out.write_text(json.dumps({'trips': trips, 'dives': merged}, indent=1, ensure_ascii=False))
    scuba = sum(1 for d in merged if d.get('dive_mode') == 'opencircuit')
    print(f"OK: {len(merged)} dives ({scuba} scuba, {len(merged)-scuba} snorkel/other) "
          f"-> {out.relative_to(ROOT)}")
    flagged = [d for d in merged if d.get('suspect')]
    if flagged:
        print(f"Flagged (left out of totals): {len(flagged)}")
    if unplaced:
        print("No map position for: " + ', '.join(sorted(unplaced)) + "  (add to data/site_coords.json)")
    multi = [d for d in merged if len(d['sources']) > 1]
    if multi:
        print(f"Merged duplicates: {len(multi)}")

if __name__ == '__main__':
    main()
