import unittest
from unittest.mock import patch
import test_ai_edit_conversation as base
from ai_editing import Unknown
from ai_edit_duration import POLICY,sample_times,budget,diagnose

class DurationRepairTests(unittest.TestCase):
    setUp=base.ConversationTests.setUp
    tearDown=base.ConversationTests.tearDown
    login=base.ConversationTests.login
    account=base.ConversationTests.account
    enqueue=base.ConversationTests.enqueue
    sample=base.ConversationTests.sample
    create=base.ConversationTests.create
    get=base.ConversationTests.get
    ready=base.ConversationTests.ready
    submit=base.ConversationTests.submit
    analysis=base.ConversationTests.analysis
    plan=base.ConversationTests.plan

    def test_one_authorized_repair_then_real_export(self):
        p=self.ready();r=self.submit(p,duration_repair_authorized=True,execution_policy=POLICY)
        self.assertEqual(r.status_code,200,r.text);service=self.app.state.ai_editing
        with patch.object(service,'analyze',return_value=self.analysis()),patch.object(service,'plan',side_effect=[self.plan(p,end=.75,repeat=False),self.plan(p)]) as call:
            service.tick();service.tick();self.assertEqual(call.call_count,2)
            self.assertIn('duration_repair',call.call_args.args[0])
        p=self.get();self.assertEqual(p['body']['planning_passes'],2,p)
        self.assertEqual(len(p['body']['execution_candidates']),2)
        self.app.state.editor.tick();p=self.get()
        self.assertEqual(p['body']['export_status']['state'],'ready',p)
        self.assertEqual(len(self.member.get('/api/editor/projects').json()),1)

    def test_unknown_repair_preserves_first_and_does_not_retry(self):
        p=self.ready();self.submit(p,duration_repair_authorized=True,execution_policy=POLICY)
        service=self.app.state.ai_editing
        with patch.object(service,'analyze',return_value=self.analysis()),patch.object(service,'plan',side_effect=[self.plan(p,end=.75,repeat=False),Unknown('模拟修正请求结果未知')]) as call:
            service.tick();service.tick();self.assertEqual(call.call_count,2)
        p=self.get();self.assertEqual(p['jobs'][0]['state'],'unknown',p)
        self.assertEqual(len(p['body']['execution_candidates']),1)
        self.assertEqual(self.member.get('/api/editor/projects').json(),[])

    def test_two_bad_candidates_no_infinite_retry(self):
        p=self.ready();self.submit(p,duration_repair_authorized=True,execution_policy=POLICY)
        service=self.app.state.ai_editing
        with patch.object(service,'analyze',return_value=self.analysis()),patch.object(service,'plan',return_value=self.plan(p,end=.75,repeat=False)) as call:
            service.tick();service.tick();self.assertEqual(call.call_count,2)
        p=self.get();self.assertEqual(p['body']['execution_status'],'needs_review',p)
        self.assertEqual(len(p['body']['execution_candidates']),2)
        self.assertNotIn('export_id',p['body'])

    def test_sampling_and_duration_budget(self):
        for duration in [.1,2,15,600]:
            times=sample_times(duration)
            self.assertGreaterEqual(len(times),4);self.assertLessEqual(len(times),12)
            self.assertEqual(times[0],0);self.assertLess(times[-1],duration)
        snap={'brief':{'target':25},'source_info':[{'id':'a','duration':30}]}
        self.assertEqual(budget(snap)['target_frames'],600)
        plan={'duration':25,'shots':[{'source_id':'a','start':0,'end':14},{'source_id':'a','start':0,'end':11}]}
        self.assertTrue(diagnose(plan,snap)['issues'])

    def test_stale_policy_rejected(self):
        p=self.ready()
        self.assertEqual(self.submit(p,duration_repair_authorized=True,execution_policy='old').status_code,409)

if __name__=='__main__':unittest.main()
