import copy,unittest
from ai_edit_review_policy import evidence_gate,checklist,CONTEXT_RULES
from ai_edit_vision import clean_review,MAP_SYSTEM,DETAIL_SYSTEM
from ai_edit_requirements import SYSTEM,PLANNER

class ReviewPolicyTests(unittest.TestCase):
    def setUp(self):
        self.contract={'goal':'面向主妇的Kitchen Knife短视频','must_keep':['保留原声'],'forbidden':[],'acceptance':['英文短标题']}
        self.snap={'source_info':[{'id':'s','duration':7.104}],'_review_observed':[{'source_id':'s','at':3.5}]}
    def apply(self,row,blocks=None):
        raw={'summary':'模型认为场景不兼容','checks':[row],'blocking_issues':blocks or [],'uncertainties':[]}
        from ai_edit_provenance import seal
        snap={**self.snap,'contract':self.contract,'requirement_authority':seal({'contract':self.contract,'messages':[]},'test-confirmation','test-request')}
        return evidence_gate(clean_review(raw),raw,self.contract,snap)
    def row(self,**kw):
        return dict(requirement=self.contract['goal'],requirement_id='goal',status='fail',evidence='男性在户外，模型推断错位',basis='direct',evidence_refs=[{'kind':'frame','source_id':'s','at':3.5}],**kw)
    def test_original_audience_scene_case_is_advisory_not_a_pass(self):
        v=self.apply(self.row(),['男性不是主妇','不是厨房场景','大刀不是厨刀'])
        self.assertFalse(v['blocking_issues']);self.assertEqual(v['checks'][0]['status'],'unknown')
        self.assertTrue(any('不是厨房' in s for s in v['uncertainties']))
        self.assertIn('非新增要求',v['uncertainties'][0])
    def test_invented_hard_rule_cannot_block(self):
        row=self.row();row.update(requirement='必须厨房拍摄',requirement_id='must_keep:99')
        self.assertFalse(self.apply(row)['blocking_issues'])
    def test_empty_asr_is_not_proof_missing_original(self):
        row=self.row();row.update(requirement='保留原声',requirement_id='must_keep:0',basis='inference',evidence='ASR为空')
        self.assertFalse(self.apply(row)['blocking_issues'])
        row.update(basis='direct',evidence_refs=[{'kind':'plan','field':'sound'}])
        self.assertFalse(self.apply(row)['blocking_issues'])
    def test_explicit_location_with_direct_observed_frame_still_blocks(self):
        self.contract['forbidden'].append('禁止室外场景')
        row=self.row();row.update(requirement='禁止室外场景',requirement_id='forbidden:0',violation_kind='observed_forbidden',relation={'type':'literal_presence','subject':'禁止室外场景'},evidence='3.5秒明确见室外草坪和天空')
        v=self.apply(row);self.assertTrue(v['blocking_issues']);self.assertEqual(v['checks'][0]['status'],'fail')
    def test_non_observed_wrong_source_time_or_missing_refs_do_not_block(self):
        self.contract['must_keep'].append('必须室内拍摄')
        for refs in ([],[{'kind':'frame','source_id':'other','at':3.5}],[{'kind':'frame','source_id':'s','at':99}],[{'kind':'frame','source_id':'s','at':2}]):
            row=self.row();row.update(requirement='必须室内拍摄',requirement_id='must_keep:1',evidence_refs=refs)
            self.assertFalse(self.apply(row)['blocking_issues'])
    def test_all_model_stages_share_context_rules(self):
        for prompt in (SYSTEM,PLANNER,MAP_SYSTEM,DETAIL_SYSTEM):self.assertIn(CONTEXT_RULES,prompt)
        self.assertFalse(checklist(self.contract)[0]['hard'])

if __name__=='__main__':unittest.main()
