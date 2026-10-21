"""Read a Shearwater Cloud database (.db, SQLite) and write a slim "extract" JSON.

The raw database holds device serial numbers, app/device UUIDs, exact timestamps, resort
names and more. It must NOT be committed. This module turns it into a small file with only
what the dashboard needs, and that file is what the build reads:

    python3 -m pipeline.extract_shearwater private/RA/shearwater/shearwater_cloud.db RA

Layout of the database (as found in a real export, format "sw-pnf"):
  * dive_details   one row per dive: date, max depth (m), length (s), site, location, buddy, notes
  * log_data       per dive: data_bytes_1 = 4-byte little-endian size + gzip of 32-byte records
                              data_bytes_3 = JSON with StartTime (unix, UTC), Mode, UnitSystem
                              calculated_values_from_samples = JSON with Min/Average/MaxTemp
  * In a sample record (type byte 0x01, one every 10 s): bytes 1-2 depth (big endian, tenths of
    a metre), byte 8 oxygen %, byte 9 helium %, byte 14 temperature (signed, degrees C).
"""
import gzip
import hashlib
import json
import sqlite3
import struct
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

RECORD = 32
SAMPLE = 0x01
SAMPLE_INTERVAL_S = 10
FORMAT = 'shearwater-extract/1'

# Shearwater "Mode" values -> our modes (6 = open circuit recreational in the real export)
MODE_MAP = {0: 'ccr', 1: 'opencircuit', 2: 'gauge', 3: 'ccr', 4: 'opencircuit',
            5: 'ccr', 6: 'opencircuit', 7: 'freedive'}

# Fields that identify people or places beyond the dive site; dropped unless asked for.
OPTIONAL_FIELDS = ('venue', 'buddy', 'notes')


def decode_pnf(blob, imperial=False):
    """Packed sample data -> [(depth_m, temp_c, o2_pct, he_pct), ...], one per 10 seconds."""
    raw = gzip.decompress(blob[4:])
    out = []
    for i in range(0, len(raw) - RECORD + 1, RECORD):
        rec = raw[i:i + RECORD]
        if rec[0] != SAMPLE:
            continue
        depth = struct.unpack('>H', rec[1:3])[0] / 10.0
        temp = struct.unpack('b', rec[14:15])[0]
        if imperial:
            depth, temp = depth * 0.3048, (temp - 32) * 5 / 9
        out.append((depth, temp, rec[8], rec[9]))
    return out


def _json(blob):
    if blob is None:
        return {}
    try:
        return json.loads(blob if isinstance(blob, str) else blob.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        return {}


def _float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def read_dives(db_path, keep=()):
    """Yield one slim dict per dive. `keep` names optional fields to retain (see OPTIONAL_FIELDS)."""
    conn = sqlite3.connect(f'file:{Path(db_path).as_posix()}?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        'SELECT d.DiveId, d.DiveDate, d.Depth, d.DiveLengthTime, d.Site, d.Location, d.Buddy, d.Notes, '
        '       d.DiveNumber, l.data_bytes_1, l.data_bytes_3, l.calculated_values_from_samples '
        'FROM dive_details d LEFT JOIN log_data l ON l.log_id = d.DiveId ORDER BY d.DiveDate').fetchall()
    conn.close()
    for r in rows:
        meta = _json(r['data_bytes_3'])
        calc = _json(r['calculated_values_from_samples'])
        imperial = meta.get('UnitSystem') == 1
        if meta.get('StartTime'):
            start = datetime.fromtimestamp(int(meta['StartTime']), tz=timezone.utc)
        else:
            start = datetime.fromisoformat(r['DiveDate']).replace(tzinfo=timezone.utc)
        samples = []
        if r['data_bytes_1']:
            try:
                samples = decode_pnf(r['data_bytes_1'], imperial)
            except (OSError, EOFError, struct.error):
                samples = []
        gas = None
        if samples:
            o2, he = Counter((s[2], s[3]) for s in samples).most_common(1)[0][0]
            gas = {'o2': round(o2 / 100, 2), 'he': round(he / 100, 2)}
        depth = _float(r['Depth'])
        if depth is None and samples:
            depth = round(max(s[0] for s in samples), 1)
        dive = {
            'id': 'sw' + hashlib.sha1(str(r['DiveId']).encode()).hexdigest()[:10],
            'start_utc': start.strftime('%Y-%m-%dT%H:%MZ'),     # to the minute; seconds are not needed
            'dive_number': int(r['DiveNumber']) if str(r['DiveNumber'] or '').isdigit() else None,
            'max_depth_m': depth,
            'duration_s': int(float(r['DiveLengthTime'])) if _float(r['DiveLengthTime']) else None,
            'site': (r['Site'] or '').strip() or None,
            'mode': MODE_MAP.get(meta.get('Mode'), 'opencircuit'),
            'gas': gas,
            'temp_c': _float(calc.get('MinTemp')),
            'profile': [[i * SAMPLE_INTERVAL_S, round(s[0], 1)] for i, s in enumerate(samples)] or None,
        }
        for name, col in (('venue', 'Location'), ('buddy', 'Buddy'), ('notes', 'Notes')):
            if name in keep:
                dive[name] = (r[col] or '').strip() or None
        yield dive


def write_extract(db_path, out_path, keep=()):
    dives = list(read_dives(db_path, keep))
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps({'format': FORMAT, 'dives': dives}, separators=(',', ':')), encoding='utf-8')
    return len(dives)
