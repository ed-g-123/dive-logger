"""End to end: a small synthetic project folder goes in, merged_log.json comes out."""
import json
import tempfile
import unittest
from pathlib import Path

from helpers import padi, shearwater_db, uddf

from pipeline import build, shearwater_db as sw_db, sites

SAMPLES = [(0.0, 26, 21, 0), (12.0, 26, 21, 0), (18.4, 25, 21, 0), (4.0, 25, 21, 0)]


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        data = self.root / 'data'
        for d in ('EG/oceanic', 'EG/padi', 'RA/shearwater'):
            (data / 'divers' / d).mkdir(parents=True)
        (data / 'divers.json').write_text(json.dumps({
            'EG': {'label': 'EG', 'colour': '#111111', 'public': {'time_of_day': True}},
            'RA': {'label': 'RA', 'colour': '#222222'}}))
        # EG: one Oceanic+ dive (local time 09:30) and its PADI entry, plus one older PADI-only dive
        (data / 'divers/EG/oceanic/export.uddf').write_text(uddf([
            dict(id='dive_1', datetime='2026-10-07T09:30:00.000-00:05', greatest_depth=18.5, duration_s=2190)]))
        (data / 'divers/EG/padi/1.json').write_text(padi([
            dict(id=11, title='Reef', date='2026-10-07', site='Sandals Negril', depth=18.0, minutes=36),
            dict(id=12, title='OW1', date='2023-05-19', site='Sandals Negril', depth=18.0, minutes=40)]))
        # RA: the same dive on a Shearwater (UTC, 5 hours ahead) plus a solo dive on another trip
        db = self.root / 'sw.db'
        shearwater_db(db, [
            dict(id='A', date='2026-10-07 14:41:00', depth=18.7, length_s=2160, site='', start=1791384060,
                 samples=SAMPLES, location='Resort X', buddy='Pat', notes='secret'),
            dict(id='B', date='2024-02-02 09:09:00', depth=30.9, length_s=2386, site='Angelita', start=1706864940,
                 samples=SAMPLES)])
        sw_db.write_extract(db, data / 'divers/RA/shearwater/extracted.json')
        (data / 'site_coords.json').write_text(json.dumps({'sandals negril': {'lat': 18.33, 'lon': -78.34}}))
        self.result = build.build(self.root, log=lambda *_: None)
        self.dives = {d['id']: d for d in self.result['dives']}

    def test_counts_and_ids(self):
        self.assertEqual(len(self.result['dives']), 4)             # EG: merged + PADI-only; RA: 2
        self.assertIn('EG:uddf:dive_1', self.dives)
        self.assertEqual({d['diver'] for d in self.result['dives']}, {'EG', 'RA'})
        self.assertEqual([x['id'] for x in self.result['divers']], ['EG', 'RA'])

    def test_padi_names_and_coordinates_reach_the_device_dive(self):
        eg = self.dives['EG:uddf:dive_1']
        self.assertEqual((eg['site'], eg['title'], eg['sources']), ('Sandals Negril', 'Reef', ['padi', 'oceanic']))
        self.assertEqual((eg['lat'], eg['lon']), (18.3, -78.35))   # the device's own position wins
        padi_only = self.dives['EG:padi:12']
        self.assertEqual((padi_only['lat'], padi_only['lon']), (18.33, -78.34))   # from site_coords.json

    def test_shared_dive_is_linked_and_inherits_position_and_site(self):
        shared = [d for d in self.result['dives'] if d['group']]
        self.assertEqual(len(shared), 2)
        self.assertEqual(len(self.result['groups']), 1)
        ra = next(d for d in shared if d['diver'] == 'RA')
        self.assertEqual((ra['site'], ra['lat']), ('Sandals Negril', 18.3))

    def test_privacy_settings_are_applied(self):
        ra = next(d for d in self.result['dives'] if d['diver'] == 'RA')
        self.assertIsNone(ra['time'])
        self.assertIsNone(ra['buddies'])
        eg = self.dives['EG:uddf:dive_1']
        self.assertEqual(eg['time'], '09:30')
        text = (self.root / 'data/merged_log.json').read_text()
        for secret in ('Resort X', 'Pat', 'secret', 'SERIAL-SHOULD-NOT-LEAK', 'UUID-SHOULD-NOT-LEAK'):
            self.assertNotIn(secret, text)

    def test_trips_span_both_divers(self):
        labels = [t['label'] for t in self.result['trips']]
        self.assertEqual(labels, ['May 2023', 'Feb 2024', 'Oct 2026'])
        self.assertEqual({d['trip'] for d in self.result['dives'] if d['date'].startswith('2026')}, {'2026-10'})

    def test_alias_file_is_created_for_new_oceanic_sites(self):
        aliases = json.loads((self.root / 'data/site_aliases.json').read_text())
        self.assertEqual(aliases, {'site_a': 'Negril, Jamaica'})

    def test_existing_alias_is_never_overwritten(self):
        p = self.root / 'data/site_aliases.json'
        p.write_text(json.dumps({'site_a': 'My Reef'}))
        build.build(self.root, log=lambda *_: None)
        self.assertEqual(json.loads(p.read_text())['site_a'], 'My Reef')

    def test_output_is_valid_json_on_disk_and_deterministic(self):
        first = (self.root / 'data/merged_log.json').read_text()
        build.build(self.root, log=lambda *_: None)
        self.assertEqual((self.root / 'data/merged_log.json').read_text(), first)
        json.loads(first)

    def test_missing_diver_folder_is_skipped(self):
        cfg = self.root / 'data/divers.json'
        c = json.loads(cfg.read_text())
        c['ZZ'] = {}
        cfg.write_text(json.dumps(c))
        out = build.build(self.root, log=lambda *_: None)
        self.assertEqual(len(out['dives']), 4)


class TripDefaultTests(unittest.TestCase):
    def test_default_places_only_unpositioned_dives_of_that_diver_and_trip(self):
        from helpers import dive
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'd.json'
            path.write_text(json.dumps({'RA:2024-02': {'lat': 20.2, 'lon': -87.4, 'area': 'Tulum, Mexico'}}))
            a = dive(id='1', diver='RA', trip='2024-02', lat=None, lon=None)
            b = dive(id='2', diver='RA', trip='2024-02', lat=1.0, lon=2.0)
            c = dive(id='3', diver='EG', trip='2024-02', lat=None, lon=None)
            d = dive(id='4', diver='RA', trip='2025-01', lat=None, lon=None)
            self.assertEqual(sites.apply_trip_defaults([a, b, c, d], path), 1)
            sites.set_areas([a, b, c, d])
        self.assertEqual((a['lat'], a['area']), (20.2, 'Tulum, Mexico'))
        self.assertEqual(b['lat'], 1.0)
        self.assertIsNone(c['lat'])
        self.assertIsNone(d['lat'])


class ClockTests(unittest.TestCase):
    def run_clock(self, cfg, **kw):
        from helpers import dive
        from pipeline import clocks
        d = dive(id='RA:sw:1', diver='RA', sources=['shearwater'], trip='2026-10', time_basis='utc', **kw)
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'c.json'
            p.write_text(json.dumps(cfg))
            n = clocks.localise([d], p)
        return d, n

    def test_utc_clock_is_shifted_to_local_time(self):
        d, n = self.run_clock({'RA:2026-10': {'clock': 'utc', 'tz_offset_h': -5}}, date='2026-10-07', time='14:41')
        self.assertEqual((d['date'], d['time'], d['time_basis'], n), ('2026-10-07', '09:41', 'local', 1))

    def test_shift_can_change_the_date(self):
        d, _ = self.run_clock({'RA:2026-10': {'clock': 'utc', 'tz_offset_h': -5}}, date='2026-10-07', time='02:10')
        self.assertEqual((d['date'], d['time']), ('2026-10-06', '21:10'))

    def test_local_clock_is_only_relabelled(self):
        d, _ = self.run_clock({'RA:2026-10': {'clock': 'local'}}, date='2026-10-07', time='14:41')
        self.assertEqual((d['time'], d['time_basis']), ('14:41', 'local'))

    def test_day_entry_beats_trip_entry(self):
        cfg = {'RA:2026-10': {'clock': 'utc', 'tz_offset_h': -5}, 'RA:2026-10-07': {'clock': 'local'}}
        d, _ = self.run_clock(cfg, date='2026-10-07', time='14:41')
        self.assertEqual((d['time'], d['time_basis']), ('14:41', 'local'))
        other, _ = self.run_clock(cfg, date='2026-10-08', time='14:41')
        self.assertEqual(other['time'], '09:41')

    def test_dive_id_entry_beats_day_entry(self):
        cfg = {'RA:2026-10-07': {'clock': 'local'}, 'RA:sw:1': {'clock': 'utc', 'tz_offset_h': -5}}
        d, _ = self.run_clock(cfg, date='2026-10-07', time='14:41')
        self.assertEqual(d['time'], '09:41')

    def test_unlisted_trip_stays_utc_and_oceanic_is_untouched(self):
        d, n = self.run_clock({}, date='2026-10-07', time='14:41')
        self.assertEqual((d['time'], d['time_basis'], n), ('14:41', 'utc', 0))
        from helpers import dive
        from pipeline import clocks
        o = dive(id='EG:1', trip='2026-10', time_basis='local', sources=['oceanic'], time='09:30')
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'c.json'
            p.write_text(json.dumps({'EG:2026-10': {'clock': 'utc', 'tz_offset_h': -5}}))
            self.assertEqual(clocks.localise([o], p), 0)
        self.assertEqual(o['time'], '09:30')


class TripTests(unittest.TestCase):
    def test_gap_starts_new_trip_and_same_month_gets_suffix(self):
        from helpers import dive
        ds = [dive(id=str(i), date=d) for i, d in enumerate(['2026-10-01', '2026-10-05', '2026-10-20', '2026-10-21'])]
        trips = build.build_trips(ds)
        self.assertEqual([t['id'] for t in trips], ['2026-10', '2026-10-2'])
        self.assertEqual([d['trip'] for d in ds], ['2026-10', '2026-10', '2026-10-2', '2026-10-2'])


class NamedTripTests(unittest.TestCase):
    def dives(self, *dates):
        from helpers import dive
        return [dive(id=str(i), date=d) for i, d in enumerate(dates)]

    def test_named_range_claims_dives_of_all_divers_and_rest_is_automatic(self):
        ds = self.dives('2026-10-04', '2026-10-09', '2026-11-20', '2026-11-21')
        trips = build.build_trips(ds, [{'id': 'jamaica-2026', 'name': 'Jamaica', 'start': '2026-10-01', 'end': '2026-10-10'}])
        self.assertEqual([(t['id'], t['label'], t['n']) for t in trips], [('jamaica-2026', 'Jamaica', 2), ('2026-11', 'Nov 2026', 2)])
        self.assertEqual([d['trip'] for d in ds], ['jamaica-2026', 'jamaica-2026', '2026-11', '2026-11'])
        self.assertTrue(trips[0]['named'])
        self.assertNotIn('named', trips[1])

    def test_named_trip_with_no_dives_is_left_out(self):
        trips = build.build_trips(self.dives('2026-10-04'), [{'id': 'x', 'name': 'X', 'start': '2020-01-01', 'end': '2020-01-05'}])
        self.assertEqual([t['id'] for t in trips], ['2026-10'])

    def test_trips_are_listed_by_date_and_use_real_dive_dates(self):
        ds = self.dives('2024-02-02', '2023-05-20')
        trips = build.build_trips(ds, [{'id': 'tulum', 'name': 'Tulum', 'start': '2024-01-01', 'end': '2024-03-01'}])
        self.assertEqual([t['id'] for t in trips], ['2023-05', 'tulum'])
        self.assertEqual((trips[1]['start'], trips[1]['end']), ('2024-02-02', '2024-02-02'))

    def test_automatic_id_never_reuses_a_chosen_id(self):
        ds = self.dives('2026-10-04', '2026-11-20')
        trips = build.build_trips(ds, [{'id': '2026-11', 'name': 'Mine', 'start': '2026-10-01', 'end': '2026-10-10'}])
        self.assertEqual(sorted(t['id'] for t in trips), ['2026-11', '2026-11-auto'])

    def test_bad_config_is_an_error(self):
        with self.assertRaises(ValueError):
            build.build_trips(self.dives('2026-10-04'), [{'id': 'a', 'start': '2026-10-10', 'end': '2026-10-01'}])
        with self.assertRaises(ValueError):
            build.build_trips(self.dives('2026-10-04'), [{'id': 'a', 'start': '2026-10-01', 'end': '2026-10-10'},
                                                         {'id': 'a', 'start': '2026-11-01', 'end': '2026-11-10'}])


class SiteTests(unittest.TestCase):
    def test_guess_region(self):
        self.assertEqual(sites.guess_region(18.33, -78.35), 'Negril, Jamaica')
        self.assertIsNone(sites.guess_region(0, 0))
        self.assertIsNone(sites.guess_region(None, None))


if __name__ == '__main__':
    unittest.main()
