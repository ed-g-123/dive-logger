"""Oceanic+ UDDF 3.2.1 export -> canonical dives.

Quirks handled here:
  * Temperatures are in Kelvin.
  * Site names are ids, so the dive carries `_site_ref` and the build step names it from
    data/site_aliases.json.
  * UTC offsets are written with the hours in the minutes slot ("-00:05" means UTC-5).
    The time of day is kept exactly as written; the offset is recorded as `_tz_offset_h`.
  * Freedives (divemode "apnoe") have only two samples and no profile.
  * Samples run past the end of the dive; the profile is trimmed to the recorded duration.
  * Scuba records shorter than 5 minutes are flagged `suspect` (watch switched on by accident).
"""
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from ..model import new_dive

NS = {'u': 'http://www.streit.cc/uddf/3.2/'}
SUSPECT_UNDER_S = 300


def _text(el, path):
    x = el.find(path, NS)
    return x.text if x is not None else None


def parse_datetime(raw):
    """-> (date, 'HH:MM', offset_hours) from '2026-10-09T10:15:20.000-00:05'."""
    m = re.match(r'(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})(?::\d{2})?(?:\.\d+)?(?:([+-])(\d\d):(\d\d))?$', raw or '')
    if not m:
        return None, None, None
    date, hhmm, sign, hh, mm = m.groups()
    off = None
    if sign:
        hours = int(mm) if hh == '00' else int(hh)
        off = hours if sign == '+' else -hours
    return date, hhmm, off


def parse_root(root, diver):
    sites = {s.get('id'): (float(_text(s, 'u:geography/u:latitude')), float(_text(s, 'u:geography/u:longitude')))
             for s in root.findall('.//u:divesite/u:site', NS)}
    mixes = {m.get('id'): (float(_text(m, 'u:o2') or 0.21), float(_text(m, 'u:he') or 0.0))
             for m in root.findall('.//u:gasdefinitions/u:mix', NS)}
    dives = []
    for d in root.findall('.//u:profiledata/u:repetitiongroup/u:dive', NS):
        before = d.find('u:informationbeforedive', NS)
        after = d.find('u:informationafterdive', NS)
        ref = before.find('u:link', NS).get('ref')
        date, hhmm, off = parse_datetime(_text(before, 'u:datetime'))
        wps = d.findall('u:samples/u:waypoint', NS)
        mode = None
        gas_ref = None
        samples = []
        for w in wps:
            t, dep = _text(w, 'u:divetime'), _text(w, 'u:depth')
            if t is not None and dep is not None:
                samples.append([float(t), float(dep)])
            dm = w.find('u:divemode', NS)
            if dm is not None:
                mode = dm.get('type')
            sw = w.find('u:switchmix', NS)
            if sw is not None:
                gas_ref = sw.get('ref')
        if gas_ref is None:
            link = d.find('u:tankdata/u:link', NS)
            gas_ref = link.get('ref') if link is not None else None
        dur_s = float(_text(after, 'u:diveduration'))
        freedive = (mode or 'apnoe') == 'apnoe'
        lowt = _text(after, 'u:lowesttemperature')
        rating = _text(after, 'u:rating/u:ratingvalue')
        profile = None
        if not freedive:
            profile = [[int(t), round(dep, 1)] for t, dep in samples if t <= dur_s + 60]
            if len(profile) <= 2:
                profile = None
        o2, he = mixes.get(gas_ref, (None, None))
        dive = new_dive(
            id=f'{diver}:uddf:{d.get("id")}',
            diver=diver,
            sources=['oceanic'],
            source_ids={'oceanic': d.get('id')},
            date=date, time=hhmm, time_basis='local',
            lat=sites[ref][0], lon=sites[ref][1],
            max_depth_m=round(float(_text(after, 'u:greatestdepth')), 1),
            duration_min=round(dur_s / 60.0, 1),
            water_temp_c=round(float(lowt) - 273.15, 1) if lowt else None,
            dive_mode='freedive' if freedive else 'opencircuit',
            gas=None if freedive or o2 is None else {'o2': round(o2, 2), 'he': round(he or 0.0, 2), 'assumed': False},
            profile=profile,
            rating=int(rating) if rating else None,
            suspect=(not freedive) and dur_s < SUSPECT_UNDER_S,
        )
        dive['_site_ref'] = ref
        dive['_tz_offset_h'] = off
        dives.append(dive)
    return dives


def parse(path, diver):
    return parse_root(ET.parse(Path(path)).getroot(), diver)


def parse_text(text, diver):
    return parse_root(ET.fromstring(text), diver)
