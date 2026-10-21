"""Turn Shearwater times into local time, using data/clocks.json.

Shearwater Cloud gives a start time with no time zone, and on some trips it is true UTC while on
others the device clock was simply set to local time. data/clocks.json says which, per diver and trip:

    { "RA:2023-10": {"clock": "local"},                       # the device clock showed local time already
      "RA:2026-10": {"clock": "utc", "tz_offset_h": -5} }     # UTC; local = UTC - 5 hours

If the clock changed within a trip, key an entry by day ("RA:2025-01-30") or by dive id ("RA:sw:abc..."); the most
specific entry wins: dive id, then day (the date as the device recorded it), then trip.

Dives on trips that are not listed keep their time as UTC (the page labels it "UTC").
Oceanic+ is not touched: it records local time plus an offset, and the local time is right.
"""
from datetime import datetime, timedelta

from .sites import load_json


def localise(dives, path):
    """Rewrite date/time/time_basis of Shearwater dives. Returns how many dives were changed."""
    cfg = load_json(path, {})
    changed = 0
    for d in dives:
        c = cfg.get(d['id']) or cfg.get(f"{d['diver']}:{d['date']}") or cfg.get(f"{d['diver']}:{d.get('trip')}")
        if not c or d['time_basis'] != 'utc' or 'shearwater' not in d['sources'] or not d['time']:
            continue
        if c.get('clock') == 'local':
            d['time_basis'] = 'local'
        elif c.get('clock') == 'utc' and c.get('tz_offset_h') is not None:
            t = datetime.fromisoformat(f"{d['date']}T{d['time']}") + timedelta(hours=c['tz_offset_h'])
            d['date'], d['time'], d['time_basis'] = t.strftime('%Y-%m-%d'), t.strftime('%H:%M'), 'local'
        else:
            continue
        changed += 1
    return changed
