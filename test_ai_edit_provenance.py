import copy,unittest
from ai_edit_provenance import ledger,seal,confirmed,review_context,observation_context
from ai_edit_review_policy import evidence_gate
from ai_edit_vision import clean_review

class ProvenanceTests(unittest.TestCase):
    def contract(self,goal='旅行记录'):
        return {'goal':goal,'must_keep':['保留原声'],'forbidden':['禁止出现品牌标识'],'acceptance':['节奏自然']}
    def snapshot(self,contract):
        body={'contract':contract,'messages':[{'role':'user','text':'保留原声，其他按确认卡。'}]}
        return {**body,'requirement_authority':seal(body,'hash','request'),'source_info':[{'id':'s','duration':5}],'_review_observed':[{'source_id':'s','at':2}]}
    def test_origin_not_inferred_from_assistant_history(self):
        c=self.contract();v=ledger(c,[{'role':'assistant','text':'禁止出现品牌标识'},{'role':'user','text':'保留原声'}])
        rows={r['text']:r for r in v['requirements']}
        self.assertEqual(rows['保留原声']['origin'],'user_verbatim')
        self.assertEqual(rows['禁止出现品牌标识']['origin'],'assistant_proposal')
        self.assertTrue(all(r['authority']=='proposed' for r in v['requirements']))
    def test_final_adoption_and_tamper_detection(self):
        s=self.snapshot(self.contract());self.assertTrue(confirmed(s))
        s['contract']['forbidden'].append('模型新增地点限制');self.assertFalse(confirmed(s))
        s=self.snapshot(self.contract());s['requirement_authority']['requirements'][0]['text']='变更';self.assertFalse(confirmed(s))
    def test_independent_review_excludes_previous_model_verdicts(self):
        s=self.snapshot(self.contract());s.update(inspection={'initial':{'limitations':['严重错位']}},plan={'risks':['必须棚拍']},instructions='被污染的总结')
        ctx=review_context(s)
        for key in ('inspection','plan','instructions'):self.assertNotIn(key,ctx)
        obs=observation_context({'initial':{'understanding':'新增要求','limitations':['否决'],'observations':[{'fact':'观察','inference':'猜测'}]}})
        self.assertNotIn('否决',str(obs));self.assertNotIn('新增要求',str(obs))
    def test_cross_products_and_noncommercial_background_not_veto(self):
        for goal in ('婴童用品给父母看','运动鞋面向老人','化妆品面向男性','宠物用品演示','旅行记录','采访人物纪录片','软件教程','生日家庭混剪'):
            with self.subTest(goal=goal):
                c=self.contract(goal);s=self.snapshot(c)
                raw={'summary':'背景错位','checks':[{'requirement':goal,'requirement_id':'goal','status':'fail','basis':'direct','evidence':'人物与受众不同，地点与用途不同','evidence_refs':[{'kind':'frame','source_id':'s','at':2}]}],'blocking_issues':['应该换场景'],'uncertainties':[]}
                v=evidence_gate(clean_review(raw),raw,c,s)
                self.assertFalse(v['blocking_issues']);self.assertTrue(v['quality_findings']);self.assertEqual(v['checks'][0]['status'],'unknown')
    def test_primary_frame_presence_required_not_model_risk_or_absence(self):
        c=self.contract();s=self.snapshot(c)
        row={'requirement':c['forbidden'][0],'requirement_id':'forbidden:0','status':'fail','basis':'direct','violation_kind':'observed_forbidden','relation':{'type':'literal_presence','subject':c['forbidden'][0]},'evidence':'2秒清晰可见禁用标识','evidence_refs':[{'kind':'frame','source_id':'s','at':2}]}
        raw={'summary':'检查','checks':[row],'blocking_issues':[],'uncertainties':[]}
        self.assertTrue(evidence_gate(clean_review(raw),raw,c,s)['blocking_issues'])
        for change in ({'basis':'inference'},{'violation_kind':'not_seen'},{'relation':{'type':'audience_fit','subject':c['forbidden'][0]}},{'relation':None}):
            r=copy.deepcopy(raw);r['checks'][0].update(change)
            self.assertFalse(evidence_gate(clean_review(r),r,c,s)['blocking_issues'])
        s.pop('requirement_authority');self.assertFalse(evidence_gate(clean_review(raw),raw,c,s)['blocking_issues'])
    def test_missing_required_action_is_unknown_not_absence_proof(self):
        c=self.contract();c['must_keep']=['完整保留拥抱动作'];s=self.snapshot(c)
        raw={'summary':'没看到拥抱','checks':[{'requirement':c['must_keep'][0],'requirement_id':'must_keep:0','status':'fail','basis':'direct','violation_kind':'not_seen','evidence':'两个样本没有拥抱','evidence_refs':[{'kind':'frame','source_id':'s','at':2}]}],'blocking_issues':[],'uncertainties':[]}
        v=evidence_gate(clean_review(raw),raw,c,s);self.assertFalse(v['blocking_issues']);self.assertEqual(v['checks'][0]['status'],'unknown')

if __name__=='__main__':unittest.main()
