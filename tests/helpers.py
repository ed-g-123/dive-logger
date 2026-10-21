"""Shared test helpers: small synthetic dives and source files. No real personal data is used."""
import gzip
import json
import sqlite3
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.model import new_dive  # noqa: E402


def dive(**kw):
    """A canonical dive with sensible defaults for tests."""
    base = dict(id='EG:test:1', diver='EG', sources=['oceanic'], source_ids={'oceanic': '1'},
                date='2026-10-07', time='09:30', time_basis='unknown', max_depth_m=18.0,
                duration_min=36.0, dive_mode='opencircuit')
    base.update(kw)
    return new_dive(**base)


# ------------------------------------------------------------------ UDDF ----
def uddf(dives, sites=None, mixes=None):
    """Build a small UDDF document. Each dive is a dict:
       id, site, datetime, mode ('opencircuit' or 'apnoe'), duration_s, greatest_depth, low_temp_k, mix, samples, rating"""
    sites = sites or {'site_a': (18.3, -78.35)}
    mixes = mixes or {'air': 0.21, 'ean32': 0.32}
    s = ['<?xml version="1.0"?><uddf xmlns="http://www.streit.cc/uddf/3.2/" version="3.2.1">']
    s.append('<gasdefinitions>' + ''.join(
        f'<mix id="{k}"><name>{k}</name><o2>{v}</o2><n2>{1 - v}</n2><he>0</he></mix>' for k, v in mixes.items()) +
        '</gasdefinitions><divesite>' + ''.join(
        f'<site id="{k}"><name>{k}</name><geography><latitude>{la}</latitude><longitude>{lo}</longitude></geography></site>'
        for k, (la, lo) in sites.items()) + '</divesite><profiledata><repetitiongroup>')
    for d in dives:
        samples = d.get('samples', [(0, 0.0), (60, 10.0), (120, 18.0), (1800, 5.0), (2100, 0.0)])
        mode = d.get('mode', 'opencircuit')
        wps = ''.join(
            f'<waypoint><depth>{dep}</depth><divetime>{t}</divetime><temperature>300.15</temperature>' +
            (f'<switchmix ref="{d.get("mix", "air")}"/>' if i == 0 and mode != 'apnoe' else '') +
            (f'<divemode type="{mode}"/>' if i == 0 else '') + '</waypoint>'
            for i, (t, dep) in enumerate(samples))
        rating = f'<rating><ratingvalue>{d["rating"]}</ratingvalue></rating>' if d.get('rating') else ''
        s.append(
            f'<dive id="{d["id"]}"><informationbeforedive><link ref="{d.get("site", "site_a")}"/>'
            f'<datetime>{d["datetime"]}</datetime></informationbeforedive>'
            f'<samples>{wps}</samples>'
            f'<informationafterdive><lowesttemperature>{d.get("low_temp_k", 302.0)}</lowesttemperature>'
            f'<greatestdepth>{d["greatest_depth"]}</greatestdepth><diveduration>{d["duration_s"]}</diveduration>'
            f'{rating}</informationafterdive></dive>')
    s.append('</repetitiongroup></profiledata></uddf>')
    return ''.join(s)


# ------------------------------------------------------------------ PADI ----
def padi(logs):
    """logs: list of dicts with id, title, date, site, depth, minutes and optional buddies/notes."""
    out = []
    for g in logs:
        out.append({
            'id': g['id'], 'log_type': g.get('log_type', 'Recreational'), 'dive_type': g.get('dive_type', 'Boat'),
            'dive_title': g.get('title'), 'dive_date': g['date'] + 'T00:00:00', 'dive_location': g.get('site'),
            'depth_times': [{'max_depth': g.get('depth'), 'bottom_time': g.get('minutes'), 'time_in': None}],
            'conditions': [{'bottom_water_temp': g.get('temp'), 'visibility': None}],
            'equipment': [{'weight': g.get('weight'), 'suit_type': g.get('suit'), 'gas_mixture': None}],
            'experiences': [{'buddies': g.get('buddies'), 'notes': g.get('notes'), 'dive_center': g.get('centre')}],
        })
    return json.dumps({'data': {'logbook_logs': out}})


# ------------------------------------------------------------ Shearwater ----
def pnf_blob(samples):
    """samples: [(depth_m, temp_c, o2_pct, he_pct)] -> packed bytes as stored in log_data.data_bytes_1."""
    recs = bytearray()
    opening = bytearray(RECORD)
    opening[0] = 0x10
    recs += opening
    for depth, temp, o2, he in samples:
        r = bytearray(RECORD)
        r[0] = 0x01
        r[1:3] = struct.pack('>H', round(depth * 10))
        r[8], r[9] = o2, he
        r[14] = temp & 0xFF
        recs += r
    closing = bytearray(RECORD)
    closing[0] = 0x20
    recs += closing
    return struct.pack('<I', len(recs)) + gzip.compress(bytes(recs))


RECORD = 32


def shearwater_db(path, dives):
    """Create a minimal Shearwater Cloud style database. Each dive is a dict:
       id, date, depth, length_s, site, location, buddy, notes, number, start (unix), mode, samples, min_temp"""
    c = sqlite3.connect(path)
    c.execute('CREATE TABLE dive_details (DiveId varchar, DiveDate datetime, Depth varchar, DiveLengthTime varchar, '
              'Site varchar, Location varchar, Buddy varchar, Notes varchar, DiveNumber varchar, SerialNumber varchar)')
    c.execute('CREATE TABLE log_data (log_id varchar, data_bytes_1 blob, data_bytes_3 blob, calculated_values_from_samples varchar)')
    for d in dives:
        c.execute('INSERT INTO dive_details VALUES (?,?,?,?,?,?,?,?,?,?)',
                  (d['id'], d['date'], str(d['depth']), str(d['length_s']), d.get('site', ''), d.get('location', ''),
                   d.get('buddy', ''), d.get('notes', ''), str(d.get('number', '')), 'SERIAL-SHOULD-NOT-LEAK'))
        meta = {'StartTime': d['start'], 'Mode': d.get('mode', 6), 'UnitSystem': 0, 'DeviceUuid': 'UUID-SHOULD-NOT-LEAK'}
        c.execute('INSERT INTO log_data VALUES (?,?,?,?)',
                  (d['id'], pnf_blob(d['samples']), json.dumps(meta).encode(),
                   json.dumps({'MinTemp': d.get('min_temp', 25.0)})))
    c.commit()
    c.close()
