"""Command line: turn a Shearwater Cloud .db into data/divers/<ID>/shearwater/extracted.json.

    python3 -m pipeline.extract_shearwater private/RA/shearwater/shearwater_cloud.db RA
    python3 -m pipeline.extract_shearwater my.db RA --keep buddy,notes   # keep optional fields
"""
import argparse
from pathlib import Path

from .shearwater_db import OPTIONAL_FIELDS, write_extract

ROOT = Path(__file__).resolve().parent.parent


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('db', help='path to the Shearwater Cloud .db file (keep it out of git)')
    ap.add_argument('diver', help='diver id, e.g. RA (must exist in data/divers.json)')
    ap.add_argument('--keep', default='', help=f'comma list of optional fields to keep: {", ".join(OPTIONAL_FIELDS)}')
    ap.add_argument('--out', help='output file (default data/divers/<ID>/shearwater/extracted.json)')
    args = ap.parse_args(argv)
    keep = tuple(x for x in args.keep.split(',') if x)
    bad = set(keep) - set(OPTIONAL_FIELDS)
    if bad:
        ap.error(f'unknown --keep field(s): {sorted(bad)}')
    out = Path(args.out) if args.out else ROOT / 'data' / 'divers' / args.diver / 'shearwater' / 'extracted.json'
    n = write_extract(args.db, out, keep)
    print(f'Wrote {n} dives -> {out}')
    if not keep:
        print('Left out: ' + ', '.join(OPTIONAL_FIELDS) + ' (use --keep to include them)')


if __name__ == '__main__':
    main()
