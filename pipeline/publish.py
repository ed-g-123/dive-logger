"""The last step before anything is written to the public JSON: apply each diver's privacy settings.

Settings live in data/divers.json under "public". Anything not listed is treated as private,
except the profile and temperature, which are public unless switched off:

    "public": {"time_of_day": false, "buddies": false, "notes": false, "venue": false,
               "profile": true, "temperature": true, "links": true}

  time_of_day  show the start time (otherwise only the date)
  buddies      show buddy names          notes   show notes
  venue        show resort / venue names
  links        show that this diver shared a dive with someone else
Pipeline-only fields (source ids, device dive numbers) and any key starting with "_" are
always removed.
"""
from .model import PRIVATE_FIELDS

DEFAULT_PUBLIC = {'time_of_day': False, 'buddies': False, 'notes': False, 'venue': False,
                  'profile': True, 'temperature': True, 'links': True}


def settings_for(diver_cfg):
    s = dict(DEFAULT_PUBLIC)
    s.update((diver_cfg or {}).get('public', {}))
    return s


def publish(dives, divers_cfg, groups=()):
    """-> (public dives, public groups). Does not modify the inputs."""
    settings = {k: settings_for(v) for k, v in divers_cfg.items()}
    hidden_links = {d['group'] for d in dives if d['group'] and not settings[d['diver']]['links']}
    out = []
    for d in dives:
        s = settings[d['diver']]
        r = {k: v for k, v in d.items() if not k.startswith('_') and k not in PRIVATE_FIELDS}
        if s['venue']:
            r['venue'] = d.get('venue')
        if not s['time_of_day']:
            r['time'], r['time_basis'] = None, 'unknown'
        if not s['buddies']:
            r['buddies'] = None
        if not s['notes']:
            r['notes'] = None
        if not s['profile']:
            r['profile'] = None
        if not s['temperature']:
            r['water_temp_c'] = None
        if d['group'] in hidden_links:
            r['group'] = None
        out.append(r)
    pub_groups = [g for g in groups if g['id'] not in hidden_links]
    return out, pub_groups
