import unittest
from unittest.mock import patch
import test_ai_edit_general as base

class NativePipelineTests(base.GeneralTests):
    # Retain fixture helpers, but run only explicitly declared native-pipeline tests.
    def test_native_inspection_two_sources_to_export(self):
        import json
        p=self.general();self.assertEqual(self.start(p).status_code,200)
        service=self.app.state.ai_editing
        first=self.mapping();second={**self.mapping(),'observations':[{**self.mapping()['observations'][0],'source_id':self.tid2}]}
        with patch.object(service,'analyze',return_value=self.analysis()),patch('asr.configured_key',return_value='fake'),patch('ai_edit_native_video.read_video',side_effect=[json.dumps(first),json.dumps(second)]) as video,patch.object(service,'plan',return_value=self.plan(p)) as planner,patch('ai_edit_vision.request',side_effect=[base.REVIEW,base.REVIEW]):
            service.tick();p=self.get();self.assertEqual(p['jobs'][0]['state'],'ready',p);self.assertEqual(p['body']['export_status']['state'],'queued',p)
            self.assertEqual(video.call_count,2)
            observations=planner.call_args.args[0]['inspection']['initial']['observations']
            self.assertEqual({r['source_id'] for r in observations},{self.tid,self.tid2})
            self.app.state.editor.tick();p=self.get();self.assertEqual(p['body']['export_status']['state'],'ready')
            service.tick();p=self.get();self.assertEqual(p['body']['review_status'],'reviewed')
        self.assertEqual(len(self.member.get('/api/editor/projects').json()[0]['body']['clips']),2)

    def test_native_pipeline_to_editable_export(self):
        p=self.general();self.assertEqual(self.start(p).status_code,200)
        service=self.app.state.ai_editing
        mapping=self.mapping()
        native={'initial':mapping,'detail':None,'method':'native-video-audio-v2','native_video':True}
        with patch.object(service,'analyze',return_value=self.analysis()),patch('ai_edit_native_video.inspect',return_value=native) as inspect,patch.object(service,'plan',return_value=self.plan(p)) as planner,patch('ai_edit_vision.request',side_effect=[base.REVIEW,base.REVIEW]) as review:
            service.tick();p=self.get();self.assertEqual(p['jobs'][0]['state'],'ready',p);self.assertEqual(p['body']['export_status']['state'],'queued',p)
            self.assertTrue(planner.call_args.args[0]['inspection']['native_video'])
            self.app.state.editor.tick();p=self.get();self.assertEqual(p['body']['export_status']['state'],'ready',p)
            service.tick();p=self.get();self.assertEqual(p['body']['review_status'],'reviewed',p)
            self.assertEqual(inspect.call_count,1);self.assertEqual(review.call_count,2)
        project=self.member.get('/api/editor/projects').json()[0]
        self.assertEqual(len(project['body']['clips']),2)
        self.assertEqual(self.member.get('/api/editor/exports/'+p['body']['export_id']+'/video').status_code,200)
