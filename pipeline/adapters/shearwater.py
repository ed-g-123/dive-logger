"""Shearwater extract JSON (written by pipeline.extract_shearwater) -> canonical dives.

Shearwater start times are UTC (they come from the device's unix timestamp), so the time of
day is stored with time_basis "utc". The linker allows for whole-hour differences against
devices that record local time.
"""
import json
from pathlib import Path

from ..model import new_dive
from ..shearwater_db import FORMAT


def parse_data(data, diver):
    if data.get('format') != FORMAT:
        raise ValueError(f'not a Shearwater extract (format={data.get("format")!r}, expected {FORMAT!r})')
    dives = []
    for r in data['dives']:
        start = r['start_utc']                      # 2023-10-06T09:42Z
        duration = r.get('duration_s')
        gas = r.get('gas')
        mode = r.get('mode') or 'opencircuit'
        dives.append(new_dive(
            id=f'{diver}:sw:{r["id"]}',
            diver=diver,
            sources=['shearwater'],
            source_ids={'shearwater': r['id']},
            date=start[:10], time=start[11:16], time_basis='utc',
            number=r.get('dive_number'),
            site=r.get('site'),
            venue=r.get('venue'),
            max_depth_m=r.get('max_depth_m'),
            duration_min=round(duration / 60, 1) if duration else None,
            water_temp_c=r.get('temp_c'),
            dive_mode=mode,
            gas=dict(gas, assumed=False) if gas else None,
            profile=r.get('profile'),
            buddies=r.get('buddy'),
            notes=r.get('notes'),
            suspect=bool(duration is not None and duration < 300 and mode != 'freedive'),
        ))
    return dives


def parse(path, diver):
    return parse_data(json.loads(Path(path).read_text(encoding='utf-8')), diver)
