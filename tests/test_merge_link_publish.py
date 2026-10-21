import unittest

from helpers import dive

from pipeline import link, merge, publish
from pipeline.model import AIR


def padi_dive(i, date, depth, minutes, **kw):
    return dive(id=f'EG:padi:{i}', sources=['padi'], source_ids={'padi': str(i)}, date=date, time=None,
                max_depth_m=depth, duration_min=minutes, gas=dict(AIR, assumed=True), **kw)


class MergeTests(unittest.TestCase):
    def test_padi_names_attach_to_the_device_dive(self):
        dev = dive(id='EG:uddf:a', date='2023-07-07', time='14:41', max_depth_m=26.3, duration_min=51.9,
                   water_temp_c=23.1, site='Cape Sounion, Greece', gas={'o2': 0.21, 'he': 0.0, 'assumed': False})
        p = padi_dive(1, '2023-07-07', 26.0, 52, site='Blue Canyon', title='Dive 2', buddies='A Buddy')
        out = merge.merge_diver([dev], [p])
        self.assertEqual(len(out), 1)
        m = out[0]
        self.assertEqual(m['id'], 'EG:uddf:a')                       # the device id is kept
        self.assertEqual(m['sources'], ['padi', 'oceanic'])
        self.assertEqual(m['site'], 'Blue Canyon')                   # PADI name wins
        self.assertEqual((m['title'], m['buddies']), ('Dive 2', 'A Buddy'))
        self.assertEqual((m['max_depth_m'], m['duration_min'], m['water_temp_c']), (26.3, 51.9, 23.1))   # device numbers win
        self.assertEqual(m['source_ids'], {'padi': '1', 'oceanic': '1'})

    def test_different_day_or_depth_does_not_match(self):
        dev = dive(date='2023-07-07', max_depth_m=26.0)
        out = merge.merge_diver([dev], [padi_dive(1, '2023-07-08', 26.0, 50), padi_dive(2, '2023-07-07', 33.0, 50)])
        self.assertEqual(len(out), 3)

    def test_one_device_dive_is_claimed_once(self):
        dev = dive(date='2023-07-07', max_depth_m=26.0, duration_min=52)
        close, far = padi_dive(1, '2023-07-07', 26.0, 52), padi_dive(2, '2023-07-07', 27.5, 40)
        out = merge.merge_diver([dev], [far, close])
        merged = [d for d in out if len(d['sources']) > 1]
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]['source_ids']['padi'], '1')       # the better fit
        self.assertEqual(len(out), 2)                                # the other PADI dive stays on its own

    def test_unmatched_padi_dive_is_kept_and_output_is_sorted(self):
        out = merge.merge_diver([dive(id='EG:uddf:b', date='2026-10-01')], [padi_dive(1, '2023-05-19', 18, 40)])
        self.assertEqual([d['date'] for d in out], ['2023-05-19', '2026-10-01'])


def ra(i='RA:sw:1', **kw):
    base = dict(id=i, diver='RA', sources=['shearwater'], source_ids={'shearwater': i})
    base.update(kw)
    return dive(**base)


class LinkTests(unittest.TestCase):
    def test_whole_hour_clock_difference_still_links(self):
        eg = dive(id='EG:1', time='09:30', max_depth_m=18.2, duration_min=36.5)
        r = ra(time='14:41', time_basis='utc', max_depth_m=18.7, duration_min=36.3)      # 5h11m later
        groups, review = link.link_dives([eg, r])
        self.assertEqual(len(groups), 1)
        self.assertEqual(eg['group'], r['group'])
        self.assertEqual(review, [])

    def test_different_diver_pair_needs_close_depth_and_duration(self):
        eg = dive(id='EG:1', time='09:30', max_depth_m=18.0, duration_min=36)
        for r in (ra(time='09:30', max_depth_m=24.0, duration_min=36),      # too deep a difference
                  ra(time='09:30', max_depth_m=18.0, duration_min=50)):     # too long a difference
            groups, _ = link.link_dives([dict(eg), r])
            self.assertEqual(groups, [])

    def test_clock_gap_that_is_not_whole_hours_does_not_link(self):
        eg = dive(id='EG:1', time='09:30')
        r = ra(time='10:05')                                               # 35 minutes apart
        self.assertEqual(link.link_dives([eg, r])[0], [])

    def test_same_diver_dives_never_link(self):
        a, b = dive(id='EG:1'), dive(id='EG:2')
        self.assertEqual(link.link_dives([a, b])[0], [])

    def test_trip_wide_offset_separates_back_to_back_dives(self):
        # two similar dives per diver; RA's clock is 5 hours ahead on both
        e1 = dive(id='EG:1', time='09:30', max_depth_m=18.7, duration_min=36.5)
        e2 = dive(id='EG:2', time='11:33', max_depth_m=18.7, duration_min=41.5)
        r1 = ra('RA:1', time='14:41', max_depth_m=18.7, duration_min=36.3)
        r2 = ra('RA:2', time='16:44', max_depth_m=18.7, duration_min=41.1)
        groups, review = link.link_dives([e1, e2, r1, r2])
        self.assertEqual(review, [])
        self.assertEqual(e1['group'], r1['group'])
        self.assertEqual(e2['group'], r2['group'])
        self.assertNotEqual(e1['group'], e2['group'])

    def test_genuinely_ambiguous_pair_goes_to_review(self):
        e1 = dive(id='EG:1', time='09:30', max_depth_m=18.0, duration_min=36)
        e2 = dive(id='EG:2', time='09:30', max_depth_m=18.0, duration_min=36)   # an identical twin
        r = ra(time='09:30', max_depth_m=18.0, duration_min=36)
        groups, review = link.link_dives([e1, e2, r])
        self.assertEqual(groups, [])
        self.assertTrue(review)
        self.assertIsNone(r['group'])

    def test_manual_link_settles_a_review_question(self):
        e1 = dive(id='EG:1', time='09:30', max_depth_m=18.0, duration_min=36)
        e2 = dive(id='EG:2', time='09:30', max_depth_m=18.0, duration_min=36)
        r = ra(time='09:30', max_depth_m=18.0, duration_min=36)
        groups, review = link.link_dives([e1, e2, r], {'link': [['EG:2', 'RA:sw:1']]})
        self.assertEqual(len(groups), 1)
        self.assertEqual(review, [])

    def test_dives_without_time_need_a_tight_match(self):
        p = dive(id='EG:padi:1', sources=['padi'], time=None, max_depth_m=18.0, duration_min=40)
        near = ra(time='10:00', max_depth_m=18.5, duration_min=41)
        far = ra('RA:sw:2', time='10:00', max_depth_m=21.0, duration_min=41)
        self.assertEqual(len(link.link_dives([dict(p), near])[0]), 1)
        self.assertEqual(link.link_dives([dict(p), far])[0], [])

    def test_suspect_and_freedives_are_not_linked(self):
        eg = dive(id='EG:1', suspect=True)
        self.assertEqual(link.link_dives([eg, ra()])[0], [])
        self.assertEqual(link.link_dives([dive(id='EG:2', dive_mode='freedive'), ra(dive_mode='freedive')])[0], [])

    def test_manual_link_and_unlink(self):
        eg, r = dive(id='EG:1', max_depth_m=18.0), ra(max_depth_m=30.0)         # nothing automatic
        groups, _ = link.link_dives([eg, r], {'link': [['EG:1', 'RA:sw:1']]})
        self.assertEqual(groups[0]['method'], 'manual')
        eg2, r2 = dive(id='EG:1'), ra()                                         # would link automatically
        groups, _ = link.link_dives([eg2, r2], {'unlink': [['RA:sw:1', 'EG:1']]})
        self.assertEqual(groups, [])

    def test_group_never_holds_two_dives_of_one_diver(self):
        e1, e2 = dive(id='EG:1'), dive(id='EG:2')
        r = ra()
        groups, _ = link.link_dives([e1, e2, r], {'link': [['EG:1', 'RA:sw:1'], ['EG:2', 'RA:sw:1']]})
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]['members']), 2)

    def test_group_ids_are_stable(self):
        def run():
            eg, r = dive(id='EG:1'), ra()
            return link.link_dives([eg, r])[0][0]['id']
        self.assertEqual(run(), run())

    def test_share_details_fills_gaps_only(self):
        eg = dive(id='EG:1', site='Gordon Reef', lat=27.98, lon=34.45)
        r = ra(site=None, lat=None, lon=None)
        link.link_dives([eg, r])
        link.share_details([eg, r])
        self.assertEqual((r['site'], r['lat'], r['lon']), ('Gordon Reef', 27.98, 34.45))
        eg2, r2 = dive(id='EG:1', site='Gordon Reef', lat=1.0, lon=2.0), ra(site='Ras Bob', lat=3.0, lon=4.0)
        link.link_dives([eg2, r2])
        link.share_details([eg2, r2])
        self.assertEqual((r2['site'], r2['lat']), ('Ras Bob', 3.0))            # nothing overwritten


class PublishTests(unittest.TestCase):
    CFG = {'EG': {'public': {'time_of_day': True, 'buddies': True, 'notes': True, 'venue': True}},
           'RA': {}}                                                           # RA: all defaults (private)

    def dives(self):
        kw = dict(time='09:30', buddies='A Buddy', notes='a note', venue='Some Resort', number=7,
                  water_temp_c=27.0, profile=[[0, 0.0], [10, 5.0]])
        e = dive(id='EG:1', **kw)
        e['_site_ref'] = 'site_x'
        return [e, ra(**kw)]

    def test_defaults_are_private(self):
        out, _ = publish.publish(self.dives(), self.CFG)
        eg, r = out
        self.assertEqual((eg['time'], eg['buddies'], eg['notes'], eg['venue']), ('09:30', 'A Buddy', 'a note', 'Some Resort'))
        self.assertEqual((r['time'], r['buddies'], r['notes']), (None, None, None))
        self.assertNotIn('venue', r)
        self.assertEqual(r['time_basis'], 'unknown')
        self.assertEqual(r['water_temp_c'], 27.0)                              # public by default
        self.assertIsNotNone(r['profile'])

    def test_pipeline_fields_never_leave(self):
        for d in publish.publish(self.dives(), self.CFG)[0]:
            self.assertNotIn('source_ids', d)
            self.assertNotIn('number', d)
            self.assertFalse([k for k in d if k.startswith('_')])

    def test_inputs_are_not_modified(self):
        dives = self.dives()
        publish.publish(dives, self.CFG)
        self.assertEqual(dives[1]['time'], '09:30')

    def test_profile_and_temperature_can_be_hidden(self):
        cfg = {'EG': {}, 'RA': {'public': {'profile': False, 'temperature': False}}}
        r = publish.publish(self.dives(), cfg)[0][1]
        self.assertIsNone(r['profile'])
        self.assertIsNone(r['water_temp_c'])

    def test_hiding_links_removes_the_group_for_everyone_in_it(self):
        eg, r = dive(id='EG:1'), ra()
        groups, _ = link.link_dives([eg, r])
        cfg = {'EG': {}, 'RA': {'public': {'links': False}}}
        dives, pub_groups = publish.publish([eg, r], cfg, groups)
        self.assertEqual(pub_groups, [])
        self.assertEqual([d['group'] for d in dives], [None, None])
        self.assertIsNotNone(eg['group'])                                      # the input is untouched


if __name__ == '__main__':
    unittest.main()
