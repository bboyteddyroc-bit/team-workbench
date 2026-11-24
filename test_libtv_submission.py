import unittest
from unittest.mock import patch
from libtv_gateway import run_video

class SubmissionTests(unittest.TestCase):
    def test_empty_node_is_not_running(self):
        stages=[]
        with patch('libtv_gateway.cli') as cli, patch('libtv_gateway.node_output',return_value=([],'',None,False,True)):
            with self.assertRaisesRegex(RuntimeError,'未检测到生成任务'):run_video('p','.',stages.append)
            self.assertEqual(cli.call_count,1)
        self.assertFalse(any('排队或生成中' in s for s in stages))
    def test_confirmed_task(self):
        stages=[]
        with patch('libtv_gateway.cli') as cli, patch('libtv_gateway.node_output',return_value=([],'',1,True,True)):
            run_video('p','.',stages.append)
            self.assertEqual(cli.call_count,1)
        self.assertIn('已确认任务',stages[-1])
    def test_failed_command_with_completed_output_is_recoverable(self):
        with patch('libtv_gateway.cli',side_effect=RuntimeError('network')) as cli,patch('libtv_gateway.node_output',return_value=(['https://x/v.mp4'],'',2,True,True)):
            run_video('p','.',lambda s:None)
            self.assertEqual(cli.call_count,1)
    def test_unknown_is_not_replayed(self):
        with patch('libtv_gateway.cli',side_effect=RuntimeError('network')) as cli,patch('libtv_gateway.node_output',side_effect=RuntimeError('network')):
            with self.assertRaisesRegex(RuntimeError,'无法确认'):run_video('p','.',lambda s:None)
            self.assertEqual(cli.call_count,1)
    def test_provider_failure(self):
        with patch('libtv_gateway.cli') as cli,patch('libtv_gateway.node_output',return_value=([],'审核失败',3,True,True)):
            with self.assertRaisesRegex(RuntimeError,'审核失败'):run_video('p','.',lambda s:None)
            self.assertEqual(cli.call_count,1)
if __name__=='__main__':unittest.main()
