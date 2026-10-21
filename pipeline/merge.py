"""Merge one diver's sources into one list of dives.

Device sources (Oceanic+, Shearwater) hold the measured numbers and the profile. PADI holds
the names: title, site, buddies, notes. A PADI dive and a device dive are the same dive when
they are on the same date and their max depths are within 3 m. Matching is a best-fit
assignment, so one device dive can never be claimed by two PADI dives.

Device wins:  depth, duration, temperature, gas, profile, time of day.
PADI wins:    site name and title (when PADI has one). PADI also fills any empty field.
"""

MAX_DEPTH_GAP_M = 3.0
DURATION_SCALE_MIN = 15.0          # only used to rank candidates, never to reject

FILL_FROM_PADI = ('title', 'buddies', 'notes', 'dive_center', 'dive_type', 'visibility', 'weight', 'suit')


def _candidates(padi, device):
    out = []
    for pi, p in enumerate(padi):
        for di, d in enumerate(device):
            if p['date'] != d['date']:
                continue
            gap = 0.0
            if p['max_depth_m'] is not None and d['max_depth_m'] is not None:
                gap = abs(p['max_depth_m'] - d['max_depth_m'])
                if gap > MAX_DEPTH_GAP_M:
                    continue
            cost = gap / MAX_DEPTH_GAP_M
            if p['duration_min'] is not None and d['duration_min'] is not None:
                cost += abs(p['duration_min'] - d['duration_min']) / DURATION_SCALE_MIN
            out.append((cost, pi, di))
    return sorted(out)


def _absorb(device, padi):
    """Return a copy of `device` annotated with PADI's names."""
    rec = dict(device)
    rec['sources'] = ['padi'] + [s for s in device['sources'] if s != 'padi']
    rec['source_ids'] = dict(padi['source_ids'], **device['source_ids'])
    if padi.get('site'):
        rec['site'] = padi['site']
    for k in FILL_FROM_PADI:
        if rec.get(k) in (None, '') and padi.get(k) not in (None, ''):
            rec[k] = padi[k]
    return rec


def sort_key(d):
    return (d['date'] or '', d['time'] or '', d['id'])


def merge_diver(device_dives, padi_dives):
    """-> merged list sorted by date and time."""
    used_p, used_d, pairs = set(), set(), {}
    for cost, pi, di in _candidates(padi_dives, device_dives):
        if pi in used_p or di in used_d:
            continue
        used_p.add(pi)
        used_d.add(di)
        pairs[di] = pi
    merged = []
    for di, d in enumerate(device_dives):
        merged.append(_absorb(d, padi_dives[pairs[di]]) if di in pairs else d)
    merged.extend(p for pi, p in enumerate(padi_dives) if pi not in used_p)
    return sorted(merged, key=sort_key)
