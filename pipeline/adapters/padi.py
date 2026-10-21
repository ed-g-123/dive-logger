"""PADI logbook JSON -> canonical dives.

PADI records carry a date but no usable time of day, no coordinates, no gas and no profile.
All PADI dives are treated as air (decision recorded in the README).
"""
import json
from pathlib import Path

from ..model import AIR, new_dive


def _logs(data):
    if isinstance(data, dict) and 'data' in data:
        return data['data'].get('logbook_logs', [])
    if isinstance(data, dict) and 'logbook_logs' in data:
        return data['logbook_logs']
    if isinstance(data, list):
        return data
    return [data]


def parse_text(text, diver):
    dives = []
    for log in _logs(json.loads(text)):
        dts = (log.get('depth_times') or [{}])[0]
        cond = (log.get('conditions') or [{}])[0]
        equip = (log.get('equipment') or [{}])[0]
        exp = (log.get('experiences') or [{}])[0]
        pid = log.get('id')
        kind = (log.get('log_type') or '') + ' ' + (log.get('dive_type') or '')
        dives.append(new_dive(
            id=f'{diver}:padi:{pid}',
            diver=diver,
            sources=['padi'],
            source_ids={'padi': str(pid)},
            date=(log.get('dive_date') or '')[:10] or None,
            time=None,                       # PADI's time of day is an entry timestamp, not the dive start
            title=log.get('dive_title'),
            site=log.get('dive_location'),
            max_depth_m=dts.get('max_depth'),
            duration_min=dts.get('bottom_time'),
            water_temp_c=cond.get('bottom_water_temp'),
            dive_mode='freedive' if 'free' in kind.lower() else 'opencircuit',
            gas=dict(AIR, assumed=True) if 'free' not in kind.lower() else None,
            buddies=exp.get('buddies'),
            notes=exp.get('notes'),
            dive_center=exp.get('dive_center'),
            dive_type=log.get('dive_type'),
            visibility=cond.get('visibility'),
            weight=equip.get('weight'),
            suit=equip.get('suit_type'),
        ))
    return dives


def parse(path, diver):
    return parse_text(Path(path).read_text(encoding='utf-8'), diver)
