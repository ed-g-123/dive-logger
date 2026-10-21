"""Site names and map positions, shared by every diver.

  data/site_aliases.json   Oceanic+ site id -> name.  Unknown ids are added automatically
                           (guessed from REGIONS, else "lat, lon") so you can edit the file once.
  data/site_coords.json    site name -> {"lat", "lon"} for dives that only have a name (PADI,
                           Shearwater). Matching ignores case.
"""
import json
from pathlib import Path

REGIONS = [  # (name, lat_min, lat_max, lon_min, lon_max). Edit freely.
    ('Negril, Jamaica', 18.2, 18.4, -78.4, -78.2),
    ('Dahab, Egypt', 28.4, 28.6, 34.5, 34.6),
    ('Sharm el-Sheikh, Egypt', 27.7, 28.1, 34.2, 34.5),
    ('Cape Sounion, Greece', 37.6, 37.8, 23.8, 24.0),
    ('Tulum, Mexico', 20.0, 20.5, -87.7, -87.3),
    ('Cabo San Lucas, Mexico', 22.7, 23.0, -110.1, -109.8),
    ('Bahamas', 20.9, 27.3, -79.5, -72.7),
]


def guess_region(lat, lon):
    if lat is None or lon is None:
        return None
    for name, la0, la1, lo0, lo1 in REGIONS:
        if la0 <= lat <= la1 and lo0 <= lon <= lo1:
            return name
    return None


def load_json(path, default):
    p = Path(path)
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else default


def name_oceanic_sites(dives, aliases_path):
    """Give Oceanic+ dives a site name from the alias file, adding any new ids to it."""
    aliases = load_json(aliases_path, {})
    changed = False
    for d in dives:
        ref = d.get('_site_ref')
        if not ref:
            continue
        if ref not in aliases:
            aliases[ref] = guess_region(d['lat'], d['lon']) or f"{d['lat']:.3f}, {d['lon']:.3f}"
            changed = True
        d['site'] = aliases[ref]
    if changed:
        Path(aliases_path).write_text(json.dumps(aliases, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    return changed


def apply_coords(dives, coords_path):
    """Fill lat/lon from site_coords.json. Returns the sorted site names that still have no position."""
    coords = {k.lower(): v for k, v in load_json(coords_path, {}).items()}
    unplaced = set()
    for d in dives:
        if d['lat'] is not None or not d.get('site'):
            continue
        c = coords.get(d['site'].lower())
        if c and c.get('lat') is not None and c.get('lon') is not None:
            d['lat'], d['lon'] = c['lat'], c['lon']
        else:
            unplaced.add(d['site'])
    return sorted(unplaced)


def apply_trip_defaults(dives, path):
    """Last resort for dives still without a position: use the default for their diver and trip,
    e.g. {"RA:2024-02": {"lat": 20.21, "lon": -87.46, "area": "Tulum, Mexico"}} in data/trip_defaults.json.
    Needs the trip ids, so run it after trips are built. Returns the number of dives placed."""
    defaults = load_json(path, {})
    placed = 0
    for d in dives:
        c = defaults.get(f"{d['diver']}:{d.get('trip')}")
        if d['lat'] is None and c and c.get('lat') is not None and c.get('lon') is not None:
            d['lat'], d['lon'] = c['lat'], c['lon']
            if c.get('area'):
                d['area'] = c['area']
            placed += 1
    return placed


def set_areas(dives):
    for d in dives:
        if not d.get('area'):
            d['area'] = guess_region(d['lat'], d['lon'])
