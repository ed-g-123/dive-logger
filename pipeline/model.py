"""The canonical dive record.

Every adapter (PADI, Oceanic+, Shearwater) returns dicts with exactly these keys, so the
merge, link and publish steps never need to know which file format a dive came from.
"""

AIR = {'o2': 0.21, 'he': 0.0}

# key -> default
FIELDS = {
    'id': None,              # "<diver>:<source>:<source id>", stable between runs
    'diver': None,           # diver id, e.g. "EG"
    'sources': None,         # e.g. ["oceanic"], ["padi", "oceanic"]
    'source_ids': None,      # id of this dive inside each source (private)
    'date': None,            # YYYY-MM-DD, as written by the source
    'time': None,            # HH:MM, as written by the source (see time_basis)
    'time_basis': 'unknown', # "local", "utc" or "unknown"
    'number': None,          # dive number on the device, if it has one (private)
    'title': None,
    'site': None,            # public site name
    'venue': None,           # resort / hotel / dive centre location (private by default)
    'area': None,            # region name guessed from coordinates
    'lat': None,
    'lon': None,
    'max_depth_m': None,
    'duration_min': None,
    'water_temp_c': None,
    'dive_mode': 'opencircuit',  # opencircuit, freedive, ccr, gauge
    'gas': None,             # {"o2": 0.32, "he": 0.0, "assumed": False}
    'profile': None,         # [[seconds, depth_m], ...]
    'buddies': None,
    'notes': None,
    'dive_center': None,
    'dive_type': None,
    'visibility': None,
    'weight': None,
    'suit': None,
    'rating': None,
    'suspect': False,        # looks like an accidental recording; left out of totals
    'trip': None,            # set by the build step
    'group': None,           # set by the link step: dives two divers shared
}

# Fields that exist only to run the pipeline or are sensitive by default.
# The publish step removes them unless the diver's settings allow them.
PRIVATE_FIELDS = ('source_ids', 'number', 'venue')


def new_dive(**kw):
    """A canonical dive with defaults filled in. Unknown keys are an error (catches typos)."""
    unknown = set(kw) - set(FIELDS)
    if unknown:
        raise KeyError(f'unknown dive field(s): {sorted(unknown)}')
    d = dict(FIELDS)
    d.update(kw)
    return d
