import json
import tempfile
import unittest
from pathlib import Path

from helpers import dive, padi, pnf_blob, shearwater_db, uddf  # noqa: F401  (also sets sys.path)

from pipeline.adapters import oceanic
from pipeline.adapters import padi as padi_adapter
from pipeline.adapters import shearwater as sw_adapter
from pipeline.model import new_dive
from pipeline import shearwater_db as sw_db


class ModelTests(unittest.TestCase):
    def test_unknown_field_is_an_error(self):
        with self.assertRaises(KeyError):
            new_dive(max_depth=3)                       # typo for max_depth_m

    def test_defaults(self):
        d = new_dive(id='x')
        self.assertFalse(d['suspect'])
        self.assertIsNone(d['group'])
        self.assertEqual(d['dive_mode'], 'opencircuit')


class OceanicTests(unittest.TestCase):
    def test_malformed_offsets(self):
        # hours are written in the minutes slot: -00:05 is UTC-5, +00:03 is UTC+3
        self.assertEqual(oceanic.parse_datetime('2026-10-09T10:15:20.000-00:05'), ('2026-10-09', '10:15', -5))
        self.assertEqual(oceanic.parse_datetime('2023-07-07T14:41:28.000+00:03'), ('2023-07-07', '14:41', 3))
        self.assertEqual(oceanic.parse_datetime('2023-07-07T14:41:28.000+02:00'), ('2023-07-07', '14:41', 2))
        self.assertEqual(oceanic.parse_datetime('garbage'), (None, None, None))

    def parse(self, dives, **kw):
        return oceanic.parse_text(uddf(dives, **kw), 'EG')

    def test_air_and_nitrox(self):
        air, nx = self.parse([
            dict(id='a', datetime='2026-10-09T10:15:00.000-00:05', greatest_depth=18.5, duration_s=2130),
            dict(id='b', datetime='2026-10-09T13:00:00.000-00:05', greatest_depth=30.0, duration_s=2400, mix='ean32')])
        self.assertEqual(air['id'], 'EG:uddf:a')
        self.assertEqual(air['gas'], {'o2': 0.21, 'he': 0.0, 'assumed': False})
        self.assertEqual(nx['gas']['o2'], 0.32)
        self.assertEqual((air['date'], air['time']), ('2026-10-09', '10:15'))
        self.assertEqual(air['max_depth_m'], 18.5)
        self.assertEqual(air['duration_min'], 35.5)
        self.assertEqual(air['water_temp_c'], 28.9)             # 302.05 K -> check below
        self.assertEqual(air['lat'], 18.3)

    def test_profile_is_trimmed_to_the_dive(self):
        samples = [(0, 0.0), (60, 10.0), (120, 18.0), (1800, 5.0), (3000, 0.0), (4000, 0.0)]
        d, = self.parse([dict(id='a', datetime='2026-10-09T10:15:00.000-00:05', greatest_depth=18.0,
                              duration_s=1900, samples=samples)])
        self.assertEqual(d['profile'][-1][0], 1800)             # 3000 s is more than a minute after the end
        self.assertEqual(d['profile'][0], [0, 0.0])

    def test_freedive_has_no_profile_or_gas(self):
        d, = self.parse([dict(id='f', datetime='2026-10-10T16:40:00.000-00:05', greatest_depth=1.2,
                              duration_s=240, mode='apnoe', samples=[(0, 0.0), (240, 0.0)])])
        self.assertEqual(d['dive_mode'], 'freedive')
        self.assertIsNone(d['profile'])
        self.assertIsNone(d['gas'])
        self.assertFalse(d['suspect'])                          # short is normal for a freedive

    def test_short_scuba_record_is_suspect(self):
        d, = self.parse([dict(id='s', datetime='2026-10-06T15:20:00.000-00:05', greatest_depth=1.1, duration_s=0,
                              samples=[(0, 1.1), (1, 1.1), (2, 1.1)])])
        self.assertTrue(d['suspect'])

    def test_site_ref_is_kept_for_naming(self):
        d, = self.parse([dict(id='a', datetime='2026-10-09T10:15:00.000-00:05', greatest_depth=18.5, duration_s=2130)])
        self.assertEqual(d['_site_ref'], 'site_a')
        self.assertIsNone(d['site'])


class PadiTests(unittest.TestCase):
    def test_sparse_record(self):
        d, = padi_adapter.parse_text(padi([dict(id=9910020, title='OW1', date='2023-05-19', site='Sandals Negril',
                                                depth=18.0, minutes=40)]), 'EG')
        self.assertEqual(d['id'], 'EG:padi:9910020')
        self.assertEqual(d['date'], '2023-05-19')
        self.assertIsNone(d['time'])                            # PADI time of day is not used
        self.assertEqual(d['gas'], {'o2': 0.21, 'he': 0.0, 'assumed': True})
        self.assertIsNone(d['water_temp_c'])
        self.assertEqual(d['max_depth_m'], 18.0)

    def test_full_record_and_wrapper_shapes(self):
        text = padi([dict(id=1, title='T', date='2023-07-07', site='Blue Canyon', depth=26.0, minutes=52,
                          temp=23.0, buddies='A Buddy', centre='A Club', weight=8.0, suit='FullSuit_5mm')])
        d, = padi_adapter.parse_text(text, 'EG')
        self.assertEqual((d['buddies'], d['dive_center'], d['weight'], d['suit']), ('A Buddy', 'A Club', 8.0, 'FullSuit_5mm'))
        bare = json.dumps(json.loads(text)['data']['logbook_logs'])         # a bare list also works
        self.assertEqual(len(padi_adapter.parse_text(bare, 'EG')), 1)

    def test_diver_id_goes_into_the_dive_id(self):
        d, = padi_adapter.parse_text(padi([dict(id=7, date='2023-05-19', depth=10, minutes=30)]), 'RA')
        self.assertEqual((d['id'], d['diver']), ('RA:padi:7', 'RA'))


class ShearwaterDecodeTests(unittest.TestCase):
    SAMPLES = [(0.0, 26, 32, 0), (12.3, 26, 32, 0), (25.9, 25, 32, 0), (5.0, 25, 32, 0)]

    def test_decode_pnf(self):
        out = sw_db.decode_pnf(pnf_blob(self.SAMPLES))
        self.assertEqual([round(s[0], 1) for s in out], [0.0, 12.3, 25.9, 5.0])
        self.assertEqual((out[0][1], out[0][2], out[0][3]), (26, 32, 0))     # temperature, o2 %, he %

    def test_negative_temperature_is_signed(self):
        out = sw_db.decode_pnf(pnf_blob([(3.0, -2, 21, 0)]))
        self.assertEqual(out[0][1], -2)

    def test_imperial_units_are_converted(self):
        out = sw_db.decode_pnf(pnf_blob([(100.0, 68, 21, 0)]), imperial=True)   # 100 ft, 68 F
        self.assertAlmostEqual(out[0][0], 30.48, places=2)
        self.assertAlmostEqual(out[0][1], 20.0, places=1)


class ShearwaterExtractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / 'sw.db'
        shearwater_db(self.db, [dict(
            id='1398730011696585372', date='2023-10-06 09:42:52', depth=25.9, length_s=3013, site='Far Garden',
            location='Some Resort', buddy='Pat', notes='nice', number=1, start=1696585372,
            samples=ShearwaterDecodeTests.SAMPLES, min_temp=25.0)])

    def test_default_extract_drops_venue_buddy_notes(self):
        d, = list(sw_db.read_dives(self.db))
        for field in ('venue', 'buddy', 'notes'):
            self.assertNotIn(field, d)
        text = json.dumps(d)
        self.assertNotIn('SERIAL-SHOULD-NOT-LEAK', text)
        self.assertNotIn('UUID-SHOULD-NOT-LEAK', text)
        self.assertNotIn('Some Resort', text)

    def test_keep_option(self):
        d, = list(sw_db.read_dives(self.db, keep=('buddy', 'venue')))
        self.assertEqual((d['buddy'], d['venue']), ('Pat', 'Some Resort'))
        self.assertNotIn('notes', d)

    def test_fields(self):
        d, = list(sw_db.read_dives(self.db))
        self.assertEqual(d['start_utc'], '2023-10-06T09:42Z')              # unix 1696585372, seconds dropped
        self.assertEqual(d['max_depth_m'], 25.9)
        self.assertEqual(d['duration_s'], 3013)
        self.assertEqual(d['site'], 'Far Garden')
        self.assertEqual(d['gas'], {'o2': 0.32, 'he': 0.0})
        self.assertEqual(d['mode'], 'opencircuit')
        self.assertEqual(d['temp_c'], 25.0)
        self.assertEqual(d['profile'][1], [10, 12.3])
        self.assertTrue(d['id'].startswith('sw') and len(d['id']) == 12)
        self.assertNotIn('1398730011696585372', d['id'])                   # raw id is not exposed

    def test_write_extract_round_trips_through_the_adapter(self):
        out = Path(self.tmp.name) / 'extracted.json'
        self.assertEqual(sw_db.write_extract(self.db, out), 1)
        d, = sw_adapter.parse(out, 'RA')
        self.assertEqual((d['id'][:6], d['diver'], d['date'], d['time'], d['time_basis']),
                         ('RA:sw:', 'RA', '2023-10-06', '09:42', 'utc'))
        self.assertEqual(d['duration_min'], 50.2)
        self.assertEqual(d['gas'], {'o2': 0.32, 'he': 0.0, 'assumed': False})

    def test_adapter_rejects_other_json(self):
        with self.assertRaises(ValueError):
            sw_adapter.parse_data({'format': 'something-else', 'dives': []}, 'RA')

    def test_short_dive_is_suspect(self):
        d, = sw_adapter.parse_data({'format': sw_db.FORMAT, 'dives': [
            {'id': 'x', 'start_utc': '2024-01-01T10:00Z', 'max_depth_m': 1.0, 'duration_s': 60}]}, 'RA')
        self.assertTrue(d['suspect'])


if __name__ == '__main__':
    unittest.main()
