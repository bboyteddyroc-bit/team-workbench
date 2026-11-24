import unittest
from apify_grouping import group_by_options, partition_results, build_request

class GroupingTests(unittest.TestCase):
    def test_separates_owner_and_window_without_account_limit(self):
        rows = [dict(owner='u', handle=f'account{i}', start_at=1, end_at=2, timezone='UTC') for i in range(50)]
        rows.append(dict(owner='v', handle='account0', start_at=1, end_at=2, timezone='UTC'))
        rows.append(dict(owner='u', handle='other', start_at=1, end_at=3, timezone='UTC'))
        self.assertEqual([len(g) for g in group_by_options(rows)], [50, 1, 1])
    def test_duplicate_rejected(self):
        a = dict(owner='u', handle='@Demo', start_at=1, end_at=2, timezone='UTC')
        with self.assertRaises(ValueError): group_by_options([a, dict(a, handle='demo')])
    def test_unassigned_and_empty_are_visible(self):
        rows = [{'id':'123', 'authorMeta':{'name':'A'}}, {'id':'x','authorMeta':{'name':'a'}}, {'id':'456','authorMeta':{'name':'c'}}]
        out = partition_results(['a','b'], rows)
        self.assertEqual(len(out['accounts']['a']),1)
        self.assertEqual(out['empty_accounts'],['b'])
        self.assertEqual(len(out['unassigned']),2)
    def test_build_bounded_multi_profile_request(self):
        from datetime import datetime, timezone
        start = datetime(2026, 11, 1, tzinfo=timezone.utc).timestamp()
        rows = [dict(owner='u', handle=f'account{i}', start_at=start, end_at=start+86400, timezone='UTC') for i in range(20)]
        request = build_request(rows)
        self.assertEqual(len(request['json']['profiles']), 20)
        self.assertEqual(request['json']['resultsPerPage'], 1000000)
        self.assertEqual(request['json']['oldestPostDateUnified'], '2026-11-01')
        self.assertEqual(request['json']['newestPostDate'], '2026-11-01')
        self.assertEqual(request['params']['maxTotalChargeUsd'], 10)
        self.assertEqual(request['params']['maxItems'], 5000)
        with self.assertRaises(ValueError): build_request(rows, max_charge=10.01)
        with self.assertRaises(ValueError): build_request(rows + [dict(rows[0], owner='v')])

    def test_invalid_dataset_rejected(self):
        with self.assertRaises(ValueError): partition_results(['a'], {})

if __name__ == '__main__': unittest.main()
