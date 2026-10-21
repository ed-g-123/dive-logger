"""Build data/merged_log.json from everything under data/.

    python3 -m pipeline.build

Folder layout (one folder per diver, named by the diver id in data/divers.json):

    data/divers.json
    data/divers/<ID>/padi/*.json            PADI logbook exports
    data/divers/<ID>/oceanic/*.uddf         Oceanic+ UDDF exports
    data/divers/<ID>/shearwater/*.json      slim extracts made by pipeline.extract_shearwater
    data/site_aliases.json  data/site_coords.json  data/trip_defaults.json  data/clocks.json  data/links.json   (shared)

Stages: read each source -> name sites -> merge each diver's sources -> link dives that
divers shared -> share positions within a link -> trips -> privacy filter -> write.
"""
import json
import sys
from datetime import date as _date
from pathlib import Path

from . import clocks, link, merge, publish, sites
from .adapters import oceanic, padi, shearwater

ROOT = Path(__file__).resolve().parent.parent
TRIP_GAP_DAYS = 7


def read_diver(folder, diver):
    """-> (device dives, padi dives) for one diver folder."""
    padi_dives, device = [], []
    for f in sorted((folder / 'padi').glob('*.json')):
        padi_dives += padi.parse(f, diver)
    for f in sorted((folder / 'oceanic').glob('*.uddf')):
        device += oceanic.parse(f, diver)
    for f in sorted((folder / 'shearwater').glob('*.json')):
        device += shearwater.parse(f, diver)
    return device, padi_dives


def build_trips(dives, gap_days=TRIP_GAP_DAYS):
    """Group dives of all divers into trips; a gap of more than gap_days starts a new trip."""
    trips, last = [], None
    ordered = sorted(dives, key=lambda d: d['date'] or '')
    for d in ordered:
        day = _date.fromisoformat(d['date'])
        if last is None or (day - last).days > gap_days:
            trips.append({'id': day.strftime('%Y-%m'), 'label': day.strftime('%b %Y'),
                          'start': d['date'], 'end': d['date'], 'n': 0})
        t = trips[-1]
        t['end'], t['n'] = d['date'], t['n'] + 1
        d['trip'] = t
        last = day
    seen = {}
    for t in trips:                              # two trips in one month get a suffix
        seen[t['id']] = seen.get(t['id'], 0) + 1
        if seen[t['id']] > 1:
            t['id'] += f'-{seen[t["id"]]}'
    for d in dives:
        d['trip'] = d['trip']['id']
    return trips


def build(root=ROOT, write=True, log=print):
    data = Path(root) / 'data'
    divers_cfg = json.loads((data / 'divers.json').read_text(encoding='utf-8'))
    manual = sites.load_json(data / 'links.json', {})

    all_dives = []
    for diver in divers_cfg:
        folder = data / 'divers' / diver
        if not folder.exists():
            log(f'  {diver}: no folder {folder.relative_to(root)}, skipped')
            continue
        device, padi_dives = read_diver(folder, diver)
        sites.name_oceanic_sites(device, data / 'site_aliases.json')
        merged = merge.merge_diver(device, padi_dives)
        log(f'  {diver}: {len(device)} device + {len(padi_dives)} PADI -> {len(merged)} dives')
        all_dives += merged

    groups, review = link.link_dives(all_dives, manual)
    link.share_details(all_dives)
    sites.apply_coords(all_dives, data / 'site_coords.json')
    all_dives.sort(key=merge.sort_key)
    trips = build_trips(all_dives)
    sites.apply_trip_defaults(all_dives, data / 'trip_defaults.json')
    clocks.localise(all_dives, data / 'clocks.json')
    sites.set_areas(all_dives)
    unplaced = sorted({d['site'] for d in all_dives if d['lat'] is None and d.get('site')})

    public, public_groups = publish.publish(all_dives, divers_cfg, groups)
    present = {d['diver'] for d in public}
    diver_list = [{'id': k, 'label': v.get('label', k), 'name': v.get('name', k), 'colour': v.get('colour', '#0e7c7b')}
                  for k, v in divers_cfg.items() if k in present]
    result = {'divers': diver_list, 'trips': trips, 'groups': public_groups, 'dives': public}

    if write:
        out = data / 'merged_log.json'
        out.write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding='utf-8')
        rev = data / 'review.json'
        if review:
            rev.write_text(json.dumps(review, indent=1), encoding='utf-8')
        elif rev.exists():
            rev.unlink()
        log(f'OK: {len(public)} dives, {len(groups)} shared, {len(trips)} trips -> {out.relative_to(root)}')
    flagged = [d for d in all_dives if d['suspect']]
    if flagged:
        log(f'Flagged (left out of totals): {len(flagged)}')
    if review:
        log(f'{len(review)} possible shared dive(s) need a decision: see data/review.json')
    if unplaced:
        log('No map position for: ' + ', '.join(unplaced) + '  (add to data/site_coords.json)')
    return result


if __name__ == '__main__':
    build()
    sys.exit(0)
