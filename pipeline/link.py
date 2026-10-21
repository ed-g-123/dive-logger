"""Link dives that two (or more) divers did together.

Each diver keeps their own record, because their computers measured slightly different
profiles. A "group" ties the records together. Nothing is merged or deleted.

Two dives from different divers are candidates when:
  * their dates are at most one day apart,
  * max depth is within 2.5 m and duration within 7 minutes (computers differ),
  * if both have a time of day, the gap between the times is a whole number of hours
    (give or take 20 minutes). Devices disagree about time zones (Oceanic+ may write local
    time, Shearwater writes UTC), so the clock time can differ by whole hours. Pairs that
    use the offset most dives in that diver pair and month agree on are preferred.
Dives with no time of day (PADI) only link on a much tighter depth and duration match.

Candidates are paired best-first. A pair is linked only if it is clearly the best match for
both dives; otherwise it goes to the review list. data/links.json can force or forbid links:

    {"link": [["EG:uddf:dive_1", "RA:sw:abc"]], "unlink": [["EG:uddf:dive_2", "RA:sw:def"]]}
"""
import hashlib
from collections import Counter
from datetime import datetime

MAX_DEPTH_GAP_M = 2.5            # two computers on the same dive can differ by a couple of metres
MAX_DURATION_GAP_MIN = 7.0       # and by several minutes (Oceanic+ counts surface time)
MAX_HOUR_RESIDUAL_MIN = 20
MAX_HOUR_OFFSET = 14
OFFSET_MISMATCH_PENALTY = 0.5    # per hour away from the clock offset most dives in that trip share
TIGHT_DEPTH_GAP_M = 1.0          # when a time of day is missing
TIGHT_DURATION_GAP_MIN = 2.0
AMBIGUITY_MARGIN = 0.3           # best match must beat the runner-up by this much


def eligible(d):
    return d['dive_mode'] in ('opencircuit', 'ccr') and not d['suspect'] and \
        d['date'] and d['max_depth_m'] is not None


def _minutes(d):
    if not d['time']:
        return None
    return datetime.fromisoformat(f"{d['date']}T{d['time']}").timestamp() / 60.0


def _day(d):
    return datetime.fromisoformat(d['date']).toordinal()


def measure(a, b):
    """-> (cost, whole_hours) or None when the two dives cannot be the same dive.

    `cost` is lower for closer matches. `whole_hours` is the clock offset between the two
    devices rounded to whole hours (None if either dive has no time of day).
    """
    if abs(_day(a) - _day(b)) > 1:
        return None
    depth_gap = abs(a['max_depth_m'] - b['max_depth_m'])
    dur_gap = 0.0
    both_dur = a['duration_min'] is not None and b['duration_min'] is not None
    if both_dur:
        dur_gap = abs(a['duration_min'] - b['duration_min'])
    ma, mb = _minutes(a), _minutes(b)
    if ma is None or mb is None:
        if a['date'] != b['date'] or not both_dur:
            return None
        if depth_gap > TIGHT_DEPTH_GAP_M or dur_gap > TIGHT_DURATION_GAP_MIN:
            return None
        return depth_gap / MAX_DEPTH_GAP_M + dur_gap / MAX_DURATION_GAP_MIN + 0.5, None
    if depth_gap > MAX_DEPTH_GAP_M or dur_gap > MAX_DURATION_GAP_MIN:
        return None
    delta = ma - mb
    hours = round(delta / 60.0)
    residual = abs(delta - 60.0 * hours)
    if residual > MAX_HOUR_RESIDUAL_MIN or abs(hours) > MAX_HOUR_OFFSET:
        return None
    return depth_gap / MAX_DEPTH_GAP_M + dur_gap / MAX_DURATION_GAP_MIN + residual / MAX_HOUR_RESIDUAL_MIN, hours


def match_cost(a, b):
    """Cost of pairing two dives, ignoring any trip-wide clock offset. None if not a candidate."""
    m = measure(a, b)
    return None if m is None else m[0]


def _dominant_offsets(cands, by_id):
    """For each (diver, diver, month), the whole-hour clock offset most dives agree on.

    Two devices usually differ by the same number of hours all trip (one writes UTC, the other
    local time), so back-to-back dives are paired using that shared offset.
    """
    best = {}                                    # dive id -> (cost, group key, hours)
    for cost, hours, x, y in cands:
        if hours is None:
            continue
        for dive in (x, y):
            if dive not in best or cost < best[dive][0]:
                a, b = by_id[x], by_id[y]
                key = (a['diver'], b['diver'], a['date'][:7])
                best[dive] = (cost, key, hours)
    votes = {}
    for cost, key, hours in best.values():
        votes.setdefault(key, Counter())[hours] += 1
    return {key: c.most_common(1)[0][0] for key, c in votes.items()}


def _auto_pairs(dives):
    by_id = {d['id']: d for d in dives}
    elig = [d for d in dives if eligible(d)]
    raw = []
    for i, a in enumerate(elig):
        for b in elig[i + 1:]:
            if a['diver'] == b['diver']:
                continue
            m = measure(a, b)
            if m is not None:
                raw.append((m[0], m[1], a['id'], b['id']))
    dominant = _dominant_offsets(raw, by_id)
    cands = []
    for cost, hours, x, y in raw:
        if hours is not None:
            a, b = by_id[x], by_id[y]
            cost += OFFSET_MISMATCH_PENALTY * abs(hours - dominant[(a['diver'], b['diver'], a['date'][:7])])
        cands.append((cost, x, y))
    cands.sort()
    by_dive = {}
    for c, x, y in cands:
        by_dive.setdefault(x, []).append((c, y))
        by_dive.setdefault(y, []).append((c, x))

    def runner_up(dive, partner):
        others = [c for c, p in by_dive[dive] if p != partner]
        return min(others) if others else None

    used, pairs, review = set(), [], []
    for c, x, y in cands:
        if x in used or y in used:
            continue
        ambiguous = False
        for dive, partner in ((x, y), (y, x)):
            ru = runner_up(dive, partner)
            if ru is not None and ru - c < AMBIGUITY_MARGIN:
                ambiguous = True
        if ambiguous:
            review.append({'a': x, 'b': y, 'cost': round(c, 2)})
            continue
        used.update((x, y))
        pairs.append((x, y, 'auto'))
    return pairs, review


def _group_id(members):
    return 'g' + hashlib.sha1(min(members).encode()).hexdigest()[:8]


def link_dives(dives, manual=None):
    """Set d['group'] on linked dives. -> (groups, review). Mutates `dives`."""
    manual = manual or {}
    by_id = {d['id']: d for d in dives}
    pairs, review = _auto_pairs(dives)
    forbidden = {frozenset(p) for p in manual.get('unlink', [])}
    pairs = [(x, y, m) for x, y, m in pairs if frozenset((x, y)) not in forbidden]
    for x, y in manual.get('link', []):
        if x in by_id and y in by_id and frozenset((x, y)) not in forbidden:
            pairs.append((x, y, 'manual'))

    # union-find; a group may hold at most one dive per diver
    parent = {}

    def find(a):
        parent.setdefault(a, a)
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    members = {}
    methods = {}
    for x, y, method in pairs:
        rx, ry = find(x), find(y)
        mx = members.setdefault(rx, {x})
        my = members.setdefault(ry, {y})
        if rx == ry:
            continue
        if {by_id[i]['diver'] for i in mx} & {by_id[i]['diver'] for i in my}:
            continue                                        # would put two dives of one diver in a group
        parent[ry] = rx
        members[rx] = mx | my
        methods[rx] = 'manual' if 'manual' in (method, methods.get(rx), methods.get(ry)) else 'auto'

    groups = []
    for root, ids in members.items():
        if find(root) != root or len(ids) < 2:
            continue
        gid = _group_id(ids)
        for i in ids:
            by_id[i]['group'] = gid
        first = min((by_id[i] for i in ids), key=lambda d: (d['date'], d['time'] or ''))
        groups.append({'id': gid, 'date': first['date'], 'members': sorted(ids),
                       'method': methods.get(root, 'auto'), 'confidence': 'high'})
    groups.sort(key=lambda g: (g['date'], g['id']))
    # a question is settled once either dive has been linked (automatically or by links.json)
    review = [r for r in review if not by_id[r['a']]['group'] and not by_id[r['b']]['group']]
    return groups, review


def share_details(dives):
    """Within a group, copy a missing map position or site name from a partner."""
    groups = {}
    for d in dives:
        if d['group']:
            groups.setdefault(d['group'], []).append(d)
    for members in groups.values():
        placed = next((m for m in members if m['lat'] is not None and m['lon'] is not None), None)
        named = next((m for m in members if m['site']), None)
        for m in members:
            if placed and m['lat'] is None:
                m['lat'], m['lon'] = placed['lat'], placed['lon']
            if named and not m['site']:
                m['site'] = named['site']
